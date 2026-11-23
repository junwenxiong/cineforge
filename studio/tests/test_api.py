#!/usr/bin/env python3
"""Comprehensive API, security, and E2E verification suite for CineForge Studio.

Uses Python 3.14 stdlib only. Starts studio/server.py on a temporary free port
(never 8765), runs full verification, and cleans up all temporary test data.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDIO_DIR = ROOT / "studio"
SERVER_SCRIPT = STUDIO_DIR / "server.py"
DB_PATH = STUDIO_DIR / "data" / "studio.db"

FORBIDDEN_SECRET_PATTERNS = (
    "hf_",
    "sk-",
    "trycloudflare.com",
    "127.0.0.1:41520/c/",
)

# Valid 1x1 dark-gold PNG for upload tests
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
TEST_EVAL_REVIEWER = "__studio_test_qa_verifier__"


def find_free_port(exclude: set[int] | None = None) -> int:
    exclude = exclude or {8765}
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            if port not in exclude:
                return port
    raise RuntimeError("Unable to find free port")


def is_image_bytes(data: bytes) -> bool:
    if len(data) < 12:
        return False
    # JPEG, PNG, WEBP, GIF
    if data.startswith(b"\xff\xd8\xff"):
        return True
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    if data.startswith((b"GIF87a", b"GIF89a")):
        return True
    return False


def cleanup_test_artifacts(project_ids: set[str], uploaded_rel_paths: set[str]) -> None:
    """Remove temporary studio_test_* files and test rows from SQLite."""
    for pid in sorted(project_ids):
        if not pid or not pid.startswith("studio_"):
            continue
        for target in (
            ROOT / "workflows" / pid,
            ROOT / "films" / pid,
            ROOT / "assets" / pid,
            ROOT / "videos" / pid,
        ):
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
        for folder in (
            STUDIO_DIR / "data" / "previews",
            STUDIO_DIR / "data" / "dispatch",
            STUDIO_DIR / "data" / "thumbs",
        ):
            if folder.exists():
                for item in folder.glob(f"*{pid}*"):
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)

    for rel in sorted(uploaded_rel_paths):
        p = (ROOT / rel).resolve()
        uploads_root = (STUDIO_DIR / "data" / "uploads").resolve()
        if str(p).startswith(str(uploads_root)) and p.exists():
            p.unlink(missing_ok=True)

    # Also clean any studio_test_* files left in studio/data/uploads
    uploads_dir = STUDIO_DIR / "data" / "uploads"
    if uploads_dir.exists():
        for item in uploads_dir.glob("*studio_test*"):
            if item.is_file():
                item.unlink(missing_ok=True)

    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        try:
            cur = conn.cursor()
            tables = [
                row[0]
                for row in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            for tbl in tables:
                cols = [
                    r[1]
                    for r in cur.execute(f'PRAGMA table_info("{tbl}")').fetchall()
                ]
                for pid in project_ids:
                    if not pid.startswith("studio_"):
                        continue
                    if "id" in cols and tbl in ("projects", "studio_projects"):
                        cur.execute(f'DELETE FROM "{tbl}" WHERE id = ?', (pid,))
                    if "project_id" in cols:
                        cur.execute(f'DELETE FROM "{tbl}" WHERE project_id = ?', (pid,))
                if "reviewer_name" in cols:
                    cur.execute(
                        f'DELETE FROM "{tbl}" WHERE reviewer_name = ?',
                        (TEST_EVAL_REVIEWER,),
                    )
            conn.commit()
        finally:
            conn.close()


class StudioAPITest(unittest.TestCase):
    server_proc: subprocess.Popen | None = None
    port: int = 0
    base_url: str = ""
    created_project_ids: set[str] = set()
    uploaded_rel_paths: set[str] = set()
    server_log_path: Path | None = None

    @classmethod
    def setUpClass(cls) -> None:
        assert SERVER_SCRIPT.exists(), f"Missing {SERVER_SCRIPT}"
        cls.created_project_ids = set()
        cls.uploaded_rel_paths = set()
        cls.port = find_free_port(exclude={8765, 8866})
        assert cls.port != 8765
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        cls.server_log_path = Path("/tmp") / f"cineforge_test_api_{cls.port}.log"
        log_fh = open(cls.server_log_path, "wb")
        cls._log_fh = log_fh
        cls.server_proc = subprocess.Popen(
            [
                sys.executable,
                str(SERVER_SCRIPT),
                "--host",
                "127.0.0.1",
                "--port",
                str(cls.port),
            ],
            cwd=str(ROOT),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
        )

        # Wait for health endpoint (allow time for initial thumbnail generation)
        deadline = time.time() + 45.0
        last_err = None
        while time.time() < deadline:
            if cls.server_proc.poll() is not None:
                log_fh.flush()
                log_text = cls.server_log_path.read_text(errors="replace")
                raise RuntimeError(
                    f"studio/server.py exited early (code={cls.server_proc.returncode}):\n{log_text}"
                )
            try:
                status, data, _ = cls._http_request("GET", "/api/health", timeout=3)
                if status == 200 and json.loads(data).get("ok") is True:
                    return
            except Exception as exc:  # noqa: BLE001
                last_err = exc
            time.sleep(0.35)
        log_fh.flush()
        log_text = cls.server_log_path.read_text(errors="replace")
        raise RuntimeError(
            f"Server failed to become healthy within 45s (last_err={last_err}):\n{log_text}"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.server_proc is not None:
            try:
                cls.server_proc.terminate()
                cls.server_proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                cls.server_proc.kill()
                cls.server_proc.wait(timeout=5)
            cls.server_proc = None
        if hasattr(cls, "_log_fh") and cls._log_fh:
            cls._log_fh.close()
        if cls.server_log_path and cls.server_log_path.exists():
            cls.server_log_path.unlink(missing_ok=True)
        cleanup_test_artifacts(cls.created_project_ids, cls.uploaded_rel_paths)

    @classmethod
    def _http_request(
        cls,
        method: str,
        path: str,
        body: bytes | dict | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        max_read: int | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        req_headers = dict(headers or {})
        payload: bytes | None = None
        if isinstance(body, dict):
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json; charset=utf-8")
        elif isinstance(body, (bytes, bytearray)):
            payload = bytes(body)

        conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=timeout)
        try:
            conn.request(method, path, body=payload, headers=req_headers)
            resp = conn.getresponse()
            if max_read is not None:
                data = resp.read(max_read)
            else:
                data = resp.read()
            resp_headers = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, data, resp_headers
        finally:
            conn.close()

    def _get_json(self, path: str, expected_status: int = 200) -> dict:
        status, data, _ = self._http_request("GET", path)
        self.assertEqual(
            status,
            expected_status,
            f"GET {path} returned {status}, body={data[:400]!r}",
        )
        return json.loads(data.decode("utf-8"))

    def _post_json(
        self, path: str, payload: dict, expected_statuses: tuple[int, ...] = (200, 201)
    ) -> tuple[int, dict]:
        status, data, _ = self._http_request("POST", path, body=payload)
        self.assertIn(
            status,
            expected_statuses,
            f"POST {path} returned {status}, body={data[:400]!r}",
        )
        return status, json.loads(data.decode("utf-8"))

    def test_01_health_and_static_root(self) -> None:
        res = self._get_json("/api/health")
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("port"), self.port)

        status, body, headers = self._http_request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn(b"app.js", body)

    def test_02_showcase_media_and_http_range(self) -> None:
        showcase = self._get_json("/api/showcase")
        hero = showcase.get("hero", [])
        items = showcase.get("items", [])
        self.assertIsInstance(hero, list)
        self.assertIsInstance(items, list)
        self.assertGreater(len(hero), 0, "showcase.hero must be non-empty")
        self.assertGreater(len(items), 0, "showcase.items must be non-empty")
        self.assertIn("stats", showcase)

        # Verify every poster_url returns 200 valid image bytes
        poster_urls: set[str] = set()
        video_urls: list[str] = []
        for entry in list(hero) + list(items):
            poster = entry.get("poster_url")
            self.assertTrue(poster, f"Missing poster_url on showcase item {entry.get('id')}")
            poster_urls.add(poster)
            vurl = entry.get("video_url")
            if vurl and vurl not in video_urls:
                video_urls.append(vurl)

        for purl in sorted(poster_urls):
            st, img_bytes, _ = self._http_request("GET", purl)
            self.assertEqual(st, 200, f"Poster failed ({st}): {purl}")
            self.assertTrue(
                is_image_bytes(img_bytes),
                f"Poster is not valid image bytes: {purl} (len={len(img_bytes)})",
            )

        # Verify at least 2 video_url endpoints return 200 (read first 4KB only)
        self.assertGreaterEqual(len(video_urls), 2, "Need at least 2 video_url entries")
        mp4_target = None
        for vurl in video_urls[:3]:
            st, chunk, hdrs = self._http_request("GET", vurl, max_read=4096)
            self.assertEqual(st, 200, f"Video URL failed ({st}): {vurl}")
            self.assertGreater(len(chunk), 0, f"Empty video body: {vurl}")
            if ".mp4" in vurl.lower() and mp4_target is None:
                mp4_target = vurl

        self.assertIsNotNone(mp4_target, "Expected at least one .mp4 video_url")
        # Verify HTTP Range: bytes=0-1023 returns 206 Partial Content with 1024 bytes
        st, chunk, hdrs = self._http_request(
            "GET", mp4_target, headers={"Range": "bytes=0-1023"}
        )
        self.assertEqual(st, 206, f"Range request expected 206, got {st} for {mp4_target}")
        self.assertEqual(len(chunk), 1024, f"Expected 1024 bytes, got {len(chunk)}")
        content_range = hdrs.get("content-range", "")
        self.assertTrue(
            content_range.startswith("bytes 0-1023/"),
            f"Unexpected Content-Range: {content_range!r}",
        )
        self.assertEqual(hdrs.get("accept-ranges", "").lower(), "bytes")

        # Also check a mid-file range
        st2, chunk2, hdrs2 = self._http_request(
            "GET", mp4_target, headers={"Range": "bytes=1024-2047"}
        )
        self.assertEqual(st2, 206)
        self.assertEqual(len(chunk2), 1024)
        self.assertTrue(hdrs2.get("content-range", "").startswith("bytes 1024-2047/"))

    def test_03_templates_and_preview_images(self) -> None:
        tpl = self._get_json("/api/templates")
        styles = tpl.get("styles", [])
        story_presets = tpl.get("story_presets", [])
        v2v_presets = tpl.get("v2v_presets", [])
        self.assertGreater(len(styles), 0, "templates.styles must be non-empty")
        self.assertGreater(len(story_presets), 0, "templates.story_presets must be non-empty")
        self.assertGreater(len(v2v_presets), 0, "templates.v2v_presets must be non-empty")

        preview_urls: set[str] = set()
        for s in styles:
            purl = s.get("preview_url")
            self.assertTrue(purl, f"Style missing preview_url: {s}")
            preview_urls.add(purl)
        for p in list(story_presets) + list(v2v_presets):
            if p.get("preview_url"):
                preview_urls.add(p["preview_url"])

        for purl in sorted(preview_urls):
            st, img_bytes, _ = self._http_request("GET", purl)
            self.assertEqual(st, 200, f"Template preview failed ({st}): {purl}")
            self.assertTrue(
                is_image_bytes(img_bytes),
                f"Template preview is not valid image: {purl}",
            )

    def test_04_security_and_secret_hygiene(self) -> None:
        blocked_paths = [
            ".env",
            "renders/farm/token",
            "renders/farm/farm.log",
            "../.env",
            "../../etc/passwd",
            "automation/film/farm_server.py",
            "workflows/starcore/film.json",
            "studio/server.py",
            "studio/data/studio.db",
        ]
        for rel in blocked_paths:
            q = urllib.parse.quote(rel, safe="/")
            st, body, _ = self._http_request("GET", f"/api/media?path={q}")
            self.assertIn(
                st,
                (403, 404),
                f"Security violation: /api/media?path={rel} returned {st} (body={body[:120]!r})",
            )

        # Also test encoded dot-dot traversal directly
        st, _, _ = self._http_request("GET", "/api/media?path=%2e%2e%2f.env")
        self.assertIn(st, (403, 404))

        # Verify /api/farm/status never leaks secrets or internal tunnels
        st, raw_bytes, _ = self._http_request("GET", "/api/farm/status")
        self.assertEqual(st, 200)
        text = raw_bytes.decode("utf-8", errors="replace")
        for forbidden in FORBIDDEN_SECRET_PATTERNS:
            self.assertNotIn(
                forbidden,
                text,
                f"Secret leak detected in /api/farm/status: found {forbidden!r}",
            )
        farm_data = json.loads(text)
        self.assertIsInstance(farm_data, dict)
        # Incremental checks (#16): telemetry array & idle_guard
        telemetry = farm_data.get("telemetry")
        self.assertIsInstance(telemetry, list, "GET /api/farm/status must include telemetry list")
        self.assertGreaterEqual(len(telemetry), 12, f"Expected >= 12 telemetry points, got {len(telemetry)}")
        for pt in telemetry:
            self.assertIn("label", pt)
            self.assertIn("shot_sec", pt)
            self.assertIn("throughput_per_hr", pt)
            self.assertIn(pt.get("source"), ("measured", "baseline"))
        idle_guard = farm_data.get("idle_guard")
        self.assertIsInstance(idle_guard, dict, "GET /api/farm/status must include idle_guard dict")
        self.assertTrue(idle_guard.get("enabled"))
        self.assertGreater(int(idle_guard.get("timeout_min", 0)), 0)
        self.assertTrue(farm_data.get("gdrive_cache_supported"))

    def test_04b_colab_notebook_and_share_info(self) -> None:
        # 1. GET /api/farm/colab-notebook returns valid nbformat 4 ipynb without secrets
        st, raw, hdrs = self._http_request("GET", "/api/farm/colab-notebook")
        self.assertEqual(st, 200, f"GET /api/farm/colab-notebook returned {st}")
        ct = hdrs.get("content-type", "")
        self.assertIn("ipynb", ct.lower(), f"Expected ipynb content-type, got {ct!r}")
        cd = hdrs.get("content-disposition", "")
        self.assertIn("CineForge_Colab_Worker.ipynb", cd)

        nb_text = raw.decode("utf-8")
        for forbidden in FORBIDDEN_SECRET_PATTERNS + ("/mnt/", "/home/", "C:\\"):
            self.assertNotIn(
                forbidden,
                nb_text,
                f"Sensitive pattern leaked in colab-notebook: {forbidden!r}",
            )
        nb = json.loads(nb_text)
        self.assertEqual(nb.get("nbformat"), 4)
        self.assertGreaterEqual(len(nb.get("cells", [])), 2)
        all_code = "\n".join(
            "".join(c.get("source", [])) if isinstance(c.get("source"), list) else str(c.get("source", ""))
            for c in nb.get("cells", [])
        )
        self.assertIn("unassign", all_code, "Notebook must include idle runtime.unassign() guard")
        self.assertTrue(
            "drive.mount" in all_code or "USE_GDRIVE_CACHE" in all_code,
            "Notebook must include Google Drive cache support",
        )

        # 2. GET /api/share/info returns 200 with zero secret leaks
        st2, raw2, _ = self._http_request("GET", "/api/share/info")
        self.assertEqual(st2, 200, f"GET /api/share/info returned {st2}")
        share_text = raw2.decode("utf-8")
        for forbidden in FORBIDDEN_SECRET_PATTERNS:
            self.assertNotIn(forbidden, share_text, f"Secret leaked in /api/share/info: {forbidden!r}")
        share = json.loads(share_text)
        self.assertIn(share.get("mode"), ("guest", "host"))
        self.assertIsInstance(share.get("invite_required"), bool)
        self.assertIn("guest_public_cmd", share)
        self.assertTrue(len(str(share.get("invite_copy_zh", ""))) > 10)

    def test_05_workspace_projects_discovery(self) -> None:
        plist = self._get_json("/api/projects")
        projects = plist.get("projects", [])
        ids = {p["id"] for p in projects}
        self.assertIn("starcore", ids, f"Missing starcore in projects: {ids}")
        self.assertIn("classics", ids, f"Missing classics in projects: {ids}")

        for pid, query in (("starcore", "?limit=30"), ("classics", "")):
            detail = self._get_json(f"/api/projects/{pid}{query}")
            self.assertIn("project", detail)
            self.assertEqual(detail["project"]["id"], pid)
            stages = detail.get("stages", [])
            self.assertEqual(len(stages), 6, f"{pid} should have 6 stages")
            dag = detail.get("dag", {})
            self.assertGreater(len(dag.get("nodes", [])), 0, f"{pid} dag.nodes empty")
            self.assertGreater(len(dag.get("edges", [])), 0, f"{pid} dag.edges empty")
            self.assertGreater(len(detail.get("scenes", [])), 0, f"{pid} scenes empty")
            shots = detail.get("shots", [])
            self.assertGreater(len(shots), 0, f"{pid} shots empty")
            if pid == "starcore":
                self.assertLessEqual(len(shots), 30)

    def test_06_upload_image(self) -> None:
        png_bytes = base64.b64decode(TINY_PNG_B64)
        st, raw, _ = self._http_request(
            "POST",
            "/api/uploads?filename=studio_test_ref.png",
            body=png_bytes,
            headers={"Content-Type": "image/png"},
        )
        self.assertIn(st, (200, 201), f"Upload failed ({st}): {raw[:300]!r}")
        res = json.loads(raw.decode("utf-8"))
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("kind"), "image")
        rel_path = res.get("rel_path", "")
        if rel_path:
            self.uploaded_rel_paths.add(rel_path)
        media_url = res.get("url")
        self.assertTrue(media_url)
        st2, fetched, _ = self._http_request("GET", media_url)
        self.assertEqual(st2, 200)
        self.assertTrue(is_image_bytes(fetched))

    def test_07_e2e_create_patch_render_dispatch(self) -> None:
        # 1. Create project
        payload = {
            "title": "test_qa_e2e_film",
            "idea": "一只戴着护目镜的橘猫在雨夜天台发现神秘发光星核，决定踏上奇幻冒险。",
            "mode": "original",
            "style_id": "pixar_3d",
            "duration_sec": 30,
            "aspect": "16:9",
            "character_name": "小橘",
            "ref_image_urls": [],
            "creator_name": "QA测试",
        }
        status, created = self._post_json("/api/projects", payload, expected_statuses=(201,))
        self.assertEqual(status, 201)
        proj = created.get("project", {})
        pid = proj.get("id", "")
        self.assertTrue(pid.startswith("studio_"), f"Expected studio_* id, got {pid!r}")
        self.created_project_ids.add(pid)

        # Verify on-disk CineForge files materialized
        wf_root = ROOT / "workflows" if (ROOT / "workflows").is_dir() else (ROOT / "films")
        film_json = wf_root / pid / "film.json"
        s01_json = wf_root / pid / "shots" / "S01.json"
        self.assertTrue(film_json.exists(), f"Missing {film_json}")
        self.assertTrue(s01_json.exists(), f"Missing {s01_json}")
        film_obj = json.loads(film_json.read_text(encoding="utf-8"))
        s01_obj = json.loads(s01_json.read_text(encoding="utf-8"))
        self.assertIsInstance(film_obj, dict)
        self.assertTrue(bool(s01_obj))

        # 2. Fetch detail and PATCH a shot to approved
        detail = self._get_json(f"/api/projects/{pid}")
        shots = detail.get("shots", [])
        self.assertGreaterEqual(len(shots), 4, f"Expected 4-8 generated shots, got {len(shots)}")
        shot0 = shots[0]
        sid = shot0["id"]

        st, raw, _ = self._http_request(
            "PATCH",
            f"/api/projects/{pid}/shots/{sid}",
            body={"status": "approved", "notes": "QA verified shot"},
        )
        self.assertEqual(st, 200, f"PATCH shot failed ({st}): {raw[:300]!r}")
        patched = json.loads(raw.decode("utf-8"))
        self.assertEqual(patched["shot"]["status"], "approved")

        # Verify persistence across re-fetch
        detail_after = self._get_json(f"/api/projects/{pid}")
        shot0_after = next(s for s in detail_after["shots"] if s["id"] == sid)
        self.assertEqual(shot0_after["status"], "approved")
        self.assertEqual(shot0_after.get("notes"), "QA verified shot")

        # Verify retake endpoint on shot 1
        sid1 = shots[1]["id"]
        _, retake_res = self._post_json(
            f"/api/projects/{pid}/shots/{sid1}/retake",
            {"reason": "测试重拍光影微调", "prompt": shots[1].get("prompt", "")},
            expected_statuses=(200,),
        )
        self.assertEqual(retake_res["shot"]["status"], "retake")

        # Verify advance-stage endpoint
        _, adv_res = self._post_json(
            f"/api/projects/{pid}/advance-stage",
            {"stage": "script"},
            expected_statuses=(200,),
        )
        self.assertTrue(adv_res.get("ok"))

        # 3. Render real preview via ffmpeg and poll job until completed
        _, render_res = self._post_json(
            f"/api/projects/{pid}/render-preview",
            {},
            expected_statuses=(200, 201, 202),
        )
        self.assertTrue(render_res.get("ok"))
        job_id = render_res.get("job_id")
        self.assertTrue(job_id, f"Missing job_id in render-preview response: {render_res}")

        deadline = time.time() + 90.0
        final_job = None
        while time.time() < deadline:
            job_resp = self._get_json(f"/api/jobs/{job_id}")
            job = job_resp.get("job", job_resp)
            jst = str(job.get("status", "")).lower()
            if jst in ("completed", "done", "succeeded"):
                final_job = job
                break
            if jst in ("failed", "error"):
                self.fail(f"render-preview job failed: {job}")
            time.sleep(0.5)

        self.assertIsNotNone(final_job, f"render-preview job {job_id} timed out")

        # Check MP4 exists on disk and passes ffprobe decode check
        preview_mp4 = STUDIO_DIR / "data" / "previews" / f"{pid}_preview.mp4"
        self.assertTrue(preview_mp4.exists(), f"Expected rendered preview MP4 at {preview_mp4}")
        self.assertGreater(preview_mp4.stat().st_size, 1024)

        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,codec_name,width,height",
                "-of",
                "json",
                str(preview_mp4),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(probe.returncode, 0, f"ffprobe failed: {probe.stderr}")
        probe_data = json.loads(probe.stdout)
        streams = probe_data.get("streams", [])
        codec_types = {s.get("codec_type") for s in streams}
        self.assertIn("video", codec_types, f"No video stream in preview MP4: {probe_data}")
        self.assertIn("audio", codec_types, f"No audio stream in preview MP4: {probe_data}")
        duration = float(probe_data.get("format", {}).get("duration", 0))
        self.assertGreater(duration, 0.5, f"Preview duration too short: {duration}")

        # Verify preview MP4 is also accessible via HTTP with Range 206
        st_v, chunk_v, _ = self._http_request(
            "GET",
            f"/api/media?path=studio/data/previews/{pid}_preview.mp4",
            headers={"Range": "bytes=0-1023"},
        )
        self.assertEqual(st_v, 206)
        self.assertEqual(len(chunk_v), 1024)

        # 4. Dispatch cloud
        _, dispatch_res = self._post_json(
            f"/api/projects/{pid}/dispatch-cloud",
            {},
            expected_statuses=(200, 201),
        )
        self.assertTrue(dispatch_res.get("ok"))
        manifest_path = dispatch_res.get("manifest_path", "")
        self.assertTrue(manifest_path, f"Missing manifest_path: {dispatch_res}")
        mp = Path(manifest_path)
        if not mp.is_absolute():
            mp = ROOT / manifest_path
        self.assertTrue(mp.exists(), f"Dispatch manifest not found on disk: {mp}")
        manifest_obj = json.loads(mp.read_text(encoding="utf-8"))
        self.assertIsInstance(manifest_obj, dict)
        snippet = dispatch_res.get("colab_snippet", "")
        self.assertTrue(len(snippet) > 20, "colab_snippet should be non-empty")
        for forbidden in FORBIDDEN_SECRET_PATTERNS:
            self.assertNotIn(forbidden, snippet, f"Secret leaked in colab_snippet: {forbidden}")

    def test_08_evaluations_roundtrip(self) -> None:
        before = self._get_json("/api/evaluations")
        self.assertGreaterEqual(len(before.get("missions", [])), 3)
        before_count = int(before.get("summary", {}).get("count", 0))

        payload = {
            "reviewer_name": TEST_EVAL_REVIEWER,
            "role": "产品/运营",
            "work_title": "《星核黎明》",
            "project_id": "starcore",
            "aesthetic": 5,
            "consistency": 5,
            "ease_of_use": 4,
            "value": 5,
            "would_share": True,
            "comment": "端到端自动化评测验证通过，工作流看板非常直观！",
        }
        st, created = self._post_json("/api/evaluations", payload, expected_statuses=(201,))
        self.assertEqual(st, 201)
        self.assertIn("review", created)
        self.assertIn("summary", created)

        after = self._get_json("/api/evaluations")
        self.assertEqual(int(after["summary"]["count"]), before_count + 1)
        names = [r.get("reviewer_name") for r in after.get("reviews", [])]
        self.assertIn(TEST_EVAL_REVIEWER, names)

        # Invalid score rejected
        bad_payload = dict(payload, aesthetic=9)
        st_bad, _, _ = self._http_request("POST", "/api/evaluations", body=bad_payload)
        self.assertEqual(st_bad, 400, f"Expected 400 for out-of-range score, got {st_bad}")

    def test_09_sse_events_headers(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", "/api/events")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            ct = resp.getheader("Content-Type", "")
            self.assertIn("text/event-stream", ct)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
