#!/usr/bin/env python3
"""5-Layer User-Perspective End-to-End Verification Suite for CineForge Studio.

Starts isolated instances of:
  1. `automation/film/farm_server.py` (isolated --farm-dir + --token-env, never touches renders/farm/token)
  2. `studio/server.py --guest` (isolated STUDIO_DB_PATH + STUDIO_FARM_DIR, never touches studio.db)

Tests:
  Layer 1 : Real H3 novice E2E completion via real farm_server -> playable MP4 + HTTP 206 Range
  Layer 1b: Real V2V cat-swap E2E via real farm_server -> /lab/src & /lab/kf & traversal 404 & pixel-diff + 2x side-by-side width
  Layer 2 : Multi-guest session isolation (403), workspace demo write lock (403), 5x click deduplication, duration clamp, quota (429), cancel frees slot, bad upload (400)
  Layer 3 : Guest security & protocol audit (no secret/path leaks, 403 notebook, real ?t=&w= protocol in .ipynb)
"""

from __future__ import annotations

import concurrent.futures
import http.client
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDIO_DIR = ROOT / "studio"
FARM_SERVER = (
    ROOT / "tools" / "film" / "farm_server.py"
    if (ROOT / "tools" / "film" / "farm_server.py").is_file()
    else (ROOT / "automation" / "film" / "farm_server.py")
)
STUDIO_SERVER = STUDIO_DIR / "server.py"
FFMPEG_BIN = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
FFPROBE_BIN = shutil.which("ffprobe") or "/usr/bin/ffprobe"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio import pipeline_bridge as bridge  # noqa: E402

FORBIDDEN_SECRET_PATTERNS = (
    "hf_",
    "sk-",
    "trycloudflare.com",
    "127.0.0.1:41520/c/",
    "renders/farm/token",
)


def _find_free_port(exclude: set[int]) -> int:
    for _ in range(60):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            if port not in exclude:
                return port
    raise RuntimeError("No free port available")


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(k, None)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["no_proxy"] = "127.0.0.1,localhost"
    if extra:
        env.update(extra)
    return env


def _probe_mp4(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            FFPROBE_BIN,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    vs = [s for s in streams if s.get("codec_type") == "video"]
    aus = [s for s in streams if s.get("codec_type") == "audio"]
    dur = float((data.get("format") or {}).get("duration") or 0.0)
    return {
        "duration": dur,
        "width": int(vs[0]["width"]) if vs else 0,
        "height": int(vs[0]["height"]) if vs else 0,
        "has_video": bool(vs),
        "has_audio": bool(aus),
    }


def _sample_rgb_frame(path: Path, seek_sec: float, size: str = "160x120") -> bytes:
    proc = subprocess.run(
        [
            FFMPEG_BIN,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{seek_sec:.2f}",
            "-i",
            str(path),
            "-vframes",
            "1",
            "-s",
            size,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        capture_output=True,
        timeout=15,
        check=True,
    )
    return proc.stdout


def _mean_abs_diff(buf_a: bytes, buf_b: bytes) -> float:
    n = min(len(buf_a), len(buf_b))
    if n <= 0:
        return 0.0
    total = sum(abs(a - b) for a, b in zip(buf_a[:n], buf_b[:n]))
    return total / n


def _gen_png_bytes(tmp_dir: Path, name: str, color: str) -> bytes:
    out = tmp_dir / name
    subprocess.run(
        [
            FFMPEG_BIN,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x240",
            "-frames:v",
            "1",
            str(out),
        ],
        check=True,
        timeout=15,
    )
    return out.read_bytes()


def _gen_motion_mp4(tmp_dir: Path, name: str, bg: str, box_color: str, dur: float = 2.0, size: str = "640x480", freq: int = 330) -> bytes:
    out = tmp_dir / name
    vf = (
        f"drawbox=x=40:y=60:w=160:h=120:color={box_color}:t=fill,"
        f"drawbox=x=240:y=140:w=90:h=90:color=white@0.9:t=fill,"
        "hue=h=360*t"
    )
    subprocess.run(
        [
            FFMPEG_BIN,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-t",
            f"{dur:.2f}",
            "-i",
            f"color=c={bg}:s={size}:r=24",
            "-f",
            "lavfi",
            "-t",
            f"{dur:.2f}",
            "-i",
            f"sine=frequency={freq}:sample_rate=44100",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-shortest",
            str(out),
        ],
        check=True,
        timeout=25,
    )
    return out.read_bytes()


class UserE2ETests(unittest.TestCase):
    tmp_ctx: tempfile.TemporaryDirectory[str]
    tmp_dir: Path
    farm_dir: Path
    farm_port: int
    studio_port: int
    farm_token: str
    farm_proc: subprocess.Popen[bytes]
    studio_proc: subprocess.Popen[bytes]
    created_pids: set[str]
    created_shot_ids: set[str]
    uploaded_rel_paths: set[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp_ctx = tempfile.TemporaryDirectory(prefix="cineforge_user_e2e_")
        cls.tmp_dir = Path(cls.tmp_ctx.name)
        cls.farm_dir = cls.tmp_dir / "farm"
        cls.farm_dir.mkdir(parents=True, exist_ok=True)
        cls.db_path = cls.tmp_dir / "studio_e2e.db"
        cls.farm_token = secrets.token_urlsafe(16)

        cls.farm_port = _find_free_port({8765, 8866, 8871})
        cls.studio_port = _find_free_port({8765, 8866, 8871, cls.farm_port})
        cls.created_pids = set()
        cls.created_shot_ids = set()
        cls.uploaded_rel_paths = set()

        farm_log = (cls.tmp_dir / "farm.log").open("wb")
        studio_log = (cls.tmp_dir / "studio.log").open("wb")
        cls._log_handles = [farm_log, studio_log]

        cls.farm_proc = subprocess.Popen(
            [
                sys.executable,
                str(FARM_SERVER),
                "--port",
                str(cls.farm_port),
                "--farm-dir",
                str(cls.farm_dir),
                "--token-env",
                "TEST_FARM_TOKEN",
            ],
            cwd=str(ROOT),
            env=_clean_env({"TEST_FARM_TOKEN": cls.farm_token}),
            stdout=farm_log,
            stderr=subprocess.STDOUT,
        )

        # Wait for isolated farm_server health
        cls._wait_http("127.0.0.1", cls.farm_port, f"/status?t={cls.farm_token}&w=probe", 20.0)

        cls.studio_proc = subprocess.Popen(
            [
                sys.executable,
                str(STUDIO_SERVER),
                "--host",
                "127.0.0.1",
                "--port",
                str(cls.studio_port),
                "--guest",
                "--farm-port",
                str(cls.farm_port),
                "--max-guest-jobs",
                "3",
                "--max-guest-duration",
                "30",
            ],
            cwd=str(ROOT),
            env=_clean_env(
                {
                    "STUDIO_FARM_DIR": str(cls.farm_dir),
                    "STUDIO_DB_PATH": str(cls.db_path),
                }
            ),
            stdout=studio_log,
            stderr=subprocess.STDOUT,
        )
        cls._wait_http("127.0.0.1", cls.studio_port, "/api/health", 25.0)

    @classmethod
    def tearDownClass(cls) -> None:
        for proc in (getattr(cls, "studio_proc", None), getattr(cls, "farm_proc", None)):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    proc.kill()
        for fh in getattr(cls, "_log_handles", []):
            try:
                fh.close()
            except OSError:
                pass

        # Clean every project/shot/upload artifact created in workspace
        for pid in sorted(cls.created_pids):
            if not pid.startswith("studio_"):
                continue
            for folder in (ROOT / "workflows" / pid, ROOT / "films" / pid, ROOT / "assets" / pid, ROOT / "videos" / pid):
                shutil.rmtree(folder, ignore_errors=True)
            for store_dir in (
                STUDIO_DIR / "data" / "previews",
                STUDIO_DIR / "data" / "dispatch",
                STUDIO_DIR / "data" / "thumbs",
            ):
                if store_dir.is_dir():
                    for p in store_dir.glob(f"*{pid}*"):
                        if p.is_dir():
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            p.unlink(missing_ok=True)
            renders_root = ROOT / "renders"
            if renders_root.is_dir():
                for p in renders_root.glob(f"{pid}*"):
                    shutil.rmtree(p, ignore_errors=True)
            v2v_dir = renders_root / "lab" / "v2v_studio"
            if v2v_dir.is_dir():
                for p in v2v_dir.glob(f"{pid}*"):
                    p.unlink(missing_ok=True)

        for sid in sorted(cls.created_shot_ids):
            if not sid.startswith("studio_"):
                continue
            shutil.rmtree(ROOT / "renders" / sid, ignore_errors=True)
            (ROOT / "renders" / "lab" / "v2v_studio" / f"{sid}.mp4").unlink(missing_ok=True)

        uploads_root = (STUDIO_DIR / "data" / "uploads").resolve()
        for rel in sorted(cls.uploaded_rel_paths):
            abs_p = (ROOT / rel).resolve()
            if uploads_root in abs_p.parents and abs_p.is_file():
                abs_p.unlink(missing_ok=True)

        cls.tmp_ctx.cleanup()

    @classmethod
    def _wait_http(cls, host: str, port: int, path: str, timeout: float) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                conn = http.client.HTTPConnection(host, port, timeout=2.0)
                conn.request("GET", path)
                resp = conn.getresponse()
                resp.read()
                conn.close()
                if resp.status == 200:
                    return
            except OSError:
                pass
            time.sleep(0.25)
        raise TimeoutError(f"Service http://{host}:{port}{path} did not become ready in {timeout}s")

    def _req(
        self,
        port: int,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        raw_body: bytes | None = None,
        headers: dict[str, str] | None = None,
        session_id: str | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        hdrs = dict(headers or {})
        if session_id:
            hdrs["X-Studio-Session"] = session_id
        body_bytes: bytes | None = raw_body
        if json_body is not None:
            body_bytes = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20.0)
        try:
            conn.request(method, path, body=body_bytes, headers=hdrs)
            resp = conn.getresponse()
            data = resp.read()
            resp_headers = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, resp_headers, data
        finally:
            conn.close()

    def _api(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        raw_body: bytes | None = None,
        headers: dict[str, str] | None = None,
        session_id: str | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        st, hdrs, raw = self._req(
            self.studio_port,
            method,
            path,
            json_body=json_body,
            raw_body=raw_body,
            headers=headers,
            session_id=session_id,
        )
        parsed = json.loads(raw.decode("utf-8")) if raw and hdrs.get("content-type", "").startswith("application/json") else raw
        return st, hdrs, parsed

    def _poll_until(self, pred, timeout: float = 25.0, interval: float = 0.35):
        deadline = time.time() + timeout
        last_err = None
        while time.time() < deadline:
            try:
                val = pred()
                if val:
                    return val
            except Exception as exc:  # noqa: BLE001
                last_err = exc
            time.sleep(interval)
        raise AssertionError(f"Condition timed out after {timeout}s (last_err={last_err})")

    def test_01_h3_novice_real_farm_e2e_and_range_playback(self) -> None:
        # Anonymous guest visits without X-Studio-Session -> must receive studio_sid cookie
        st0, hdrs0, sess0 = self._api("GET", "/api/session")
        self.assertEqual(st0, 200)
        self.assertEqual(sess0["mode"], "guest")
        self.assertTrue(sess0["farm_online"])
        self.assertIn("studio_sid=", hdrs0.get("set-cookie", ""))
        sid_a = sess0["session_id"]

        # Create 15s original project with auto_dispatch=True (1-click novice flow)
        st_c, _, resp_c = self._api(
            "POST",
            "/api/projects",
            session_id=sid_a,
            json_body={
                "title": "test_h3_novice_e2e",
                "idea": "雨夜屋檐下小黑猫递给快递员一把发光雨伞",
                "mode": "original",
                "style_id": "pixar_3d",
                "duration_sec": 15,
                "aspect": "16:9",
                "auto_dispatch": True,
            },
        )
        self.assertEqual(st_c, 201, msg=str(resp_c))
        pid = resp_c["project"]["id"]
        self.created_pids.add(pid)
        self.assertTrue(resp_c["cloud_dispatch"]["ok"])
        self.assertIsNotNone(resp_c["cloud_job"])

        # Record shots for thorough cleanup
        _, _, detail0 = self._api("GET", f"/api/projects/{pid}", session_id=sid_a)
        for sh in detail0["shots"]:
            self.created_shot_ids.add(sh["id"])

        # Quota updated immediately (3 -> 2 remaining)
        _, _, sess_after = self._api("GET", "/api/session", session_id=sid_a)
        self.assertEqual(sess_after["used_cloud_jobs"], 1)
        self.assertEqual(sess_after["remaining_cloud_jobs"], 2)

        # Wait until coordinator stages studio_h3_queue.json onto isolated farm_dir
        self._poll_until(lambda: (self.farm_dir / "studio_h3_queue.json").is_file(), timeout=15.0)

        # Act as real Colab H3 worker talking ONLY to farm_server HTTP endpoints
        colors = [("#dc2626", "yellow", 280), ("#0284c7", "lime", 360), ("#7c3aed", "orange", 440), ("#059669", "white", 520)]
        claimed_ids: list[str] = []
        for idx in range(12):
            st_cl, _, cl_bytes = self._req(
                self.farm_port,
                "POST",
                f"/claim?t={self.farm_token}&w=mock_h3&films=studio",
                raw_body=b"{}",
            )
            if st_cl == 204 or not cl_bytes:
                break
            self.assertEqual(st_cl, 200)
            job = json.loads(cl_bytes.decode("utf-8"))
            shot_id = job["id"]
            self.assertTrue(shot_id.startswith(pid), msg=f"Claimed unexpected shot: {shot_id}")
            claimed_ids.append(shot_id)
            self.created_shot_ids.add(shot_id)

            # Verify /ref/ delivers real image bytes
            self.assertTrue(job["refs"], "Claimed H3 shot must include ref URL")
            ref_url = job["refs"][0]["url"]
            sep = "&" if "?" in ref_url else "?"
            st_ref, _, ref_data = self._req(self.farm_port, "GET", f"{ref_url}{sep}t={self.farm_token}&w=mock_h3")
            self.assertEqual(st_ref, 200)
            self.assertGreater(len(ref_data), 100)

            bg, box, freq = colors[idx % len(colors)]
            mp4_bytes = _gen_motion_mp4(self.tmp_dir, f"h3_{shot_id}.mp4", bg, box, dur=2.2, size="640x360", freq=freq)
            meta = urllib.parse.quote(json.dumps({"wall_sec": 3.5}))
            st_res, _, _ = self._req(
                self.farm_port,
                "POST",
                f"/result/{shot_id}?t={self.farm_token}&w=mock_h3&meta={meta}",
                raw_body=mp4_bytes,
            )
            self.assertEqual(st_res, 200)

        self.assertGreaterEqual(len(claimed_ids), 3)

        # Wait for CloudCoordinator to finish assembling playable final MP4
        def _is_final_ready():
            _, _, det = self._api("GET", f"/api/projects/{pid}", session_id=sid_a)
            cq = det.get("cloud_job") or {}
            if cq.get("status") == "failed":
                raise AssertionError(f"H3 cloud job failed: {cq}")
            if cq.get("status") == "completed" and det["project"].get("final_video_url"):
                return det
            return None

        final_det = self._poll_until(_is_final_ready, timeout=25.0)
        final_url = final_det["project"]["final_video_url"]
        self.assertIn(pid, final_url)

        # Verify HTTP 206 Range and playable H.264/AAC MP4 via ffprobe
        st_m, _, full_mp4 = self._req(self.studio_port, "GET", final_url)
        self.assertEqual(st_m, 200)
        st_r, hdr_r, partial = self._req(self.studio_port, "GET", final_url, headers={"Range": "bytes=0-1023"})
        self.assertEqual(st_r, 206)
        self.assertEqual(len(partial), 1024)
        self.assertIn("bytes 0-1023/", hdr_r.get("content-range", ""))

        dl_path = self.tmp_dir / f"{pid}_downloaded.mp4"
        dl_path.write_bytes(full_mp4)
        info = _probe_mp4(dl_path)
        self.assertTrue(info["has_video"])
        self.assertTrue(info["has_audio"])
        self.assertGreater(info["duration"], 4.0)

        # Non-static check across concatenated shots
        f_start = _sample_rgb_frame(dl_path, 0.4)
        f_end = _sample_rgb_frame(dl_path, max(1.0, info["duration"] - 0.8))
        self.assertGreater(_mean_abs_diff(f_start, f_end), 12.0, "Final assembled H3 video must not be a static frame")

    def test_02_v2v_real_farm_e2e_and_pixel_diff_side_by_side(self) -> None:
        sid_v = "guest_v2v_user_01"
        png_bytes = _gen_png_bytes(self.tmp_dir, "cat_ref.png", "#f59e0b")
        st_up_img, _, up_img = self._api(
            "POST",
            "/api/uploads?filename=test_cat_ref.png",
            raw_body=png_bytes,
            headers={"Content-Type": "image/png"},
            session_id=sid_v,
        )
        self.assertEqual(st_up_img, 200)
        self.uploaded_rel_paths.add(up_img["rel_path"])

        src_mp4_bytes = _gen_motion_mp4(self.tmp_dir, "human_src.mp4", "#1d4ed8", "cyan", dur=3.5, size="640x480", freq=220)
        st_up_vid, _, up_vid = self._api(
            "POST",
            "/api/uploads?filename=test_human_src.mp4",
            raw_body=src_mp4_bytes,
            headers={"Content-Type": "video/mp4"},
            session_id=sid_v,
        )
        self.assertEqual(st_up_vid, 200)
        self.uploaded_rel_paths.add(up_vid["rel_path"])

        st_c, _, resp_c = self._api(
            "POST",
            "/api/projects",
            session_id=sid_v,
            json_body={
                "title": "test_v2v_cat_e2e",
                "idea": "把办公室自拍人物变成橘猫发言人",
                "mode": "v2v",
                "style_id": "cat_classics_v2v",
                "duration_sec": 15,
                "aspect": "4:3",
                "ref_image_urls": [up_img["url"]],
                "source_video_url": up_vid["url"],
                "auto_dispatch": True,
            },
        )
        self.assertEqual(st_c, 201, msg=str(resp_c))
        pid = resp_c["project"]["id"]
        self.created_pids.add(pid)

        # Wait until farm_server exposes v2v_studio jobs
        def _get_v2v_jobs():
            st, _, raw = self._req(
                self.farm_port,
                "GET",
                f"/lab/jobs?m=v2v_studio&t={self.farm_token}&w=mock_v2v",
            )
            if st != 200:
                return None
            jobs = json.loads(raw.decode("utf-8"))
            mine = [j for j in jobs if str(j.get("id", "")).startswith(pid)]
            return mine or None

        v2v_jobs = self._poll_until(_get_v2v_jobs, timeout=15.0)

        # Verify traversal defense on /lab/kf and /lab/src
        st_trav1, _, _ = self._req(self.farm_port, "GET", f"/lab/kf?p=../../.env&t={self.farm_token}&w=mock_v2v")
        self.assertEqual(st_trav1, 404)
        st_trav2, _, _ = self._req(self.farm_port, "GET", f"/lab/src?p=../../.env&t={self.farm_token}&w=mock_v2v")
        self.assertEqual(st_trav2, 404)

        for idx, job in enumerate(v2v_jobs):
            shot_id = job["id"]
            self.created_shot_ids.add(shot_id)

            # Verify /lab/src serves the uploaded MP4 & /lab/kf serves the staged PNG
            src_q = urllib.parse.quote(job["source_url"], safe="")
            kf_q = urllib.parse.quote(job["keyframe"], safe="")
            st_s, _, s_bytes = self._req(self.farm_port, "GET", f"/lab/src?p={src_q}&t={self.farm_token}&w=mock_v2v")
            self.assertEqual(st_s, 200)
            self.assertGreater(len(s_bytes), 500)
            st_k, _, k_bytes = self._req(self.farm_port, "GET", f"/lab/kf?p={kf_q}&t={self.farm_token}&w=mock_v2v")
            self.assertEqual(st_k, 200)
            self.assertTrue(k_bytes.startswith(b"\x89PNG"))

            cat_mp4 = _gen_motion_mp4(self.tmp_dir, f"cat_{shot_id}.mp4", "#f59e0b", "#7c2d12", dur=1.4, size="640x480", freq=440 + idx * 60)
            st_u, _, _ = self._req(
                self.farm_port,
                "POST",
                f"/lab/upload/v2v_studio/{shot_id}.mp4?t={self.farm_token}&w=mock_v2v",
                raw_body=cat_mp4,
            )
            self.assertEqual(st_u, 200)

        def _is_v2v_done():
            _, _, det = self._api("GET", f"/api/projects/{pid}", session_id=sid_v)
            cq = det.get("cloud_job") or {}
            if cq.get("status") == "failed":
                raise AssertionError(f"V2V failed: {cq}")
            p = det["project"]
            if cq.get("status") == "completed" and p.get("final_video_url") and p.get("side_by_side_url"):
                return det
            return None

        det = self._poll_until(_is_v2v_done, timeout=25.0)
        clean_url = det["project"]["final_video_url"]
        sbs_url = det["project"]["side_by_side_url"]

        st1, _, clean_bytes = self._req(self.studio_port, "GET", clean_url)
        st2, _, sbs_bytes = self._req(self.studio_port, "GET", sbs_url)
        self.assertEqual(st1, 200)
        self.assertEqual(st2, 200)

        clean_path = self.tmp_dir / f"{pid}_clean.mp4"
        sbs_path = self.tmp_dir / f"{pid}_sbs.mp4"
        src_path = self.tmp_dir / "human_src.mp4"
        clean_path.write_bytes(clean_bytes)
        sbs_path.write_bytes(sbs_bytes)

        clean_info = _probe_mp4(clean_path)
        sbs_info = _probe_mp4(sbs_path)
        self.assertTrue(clean_info["has_video"] and clean_info["has_audio"])
        self.assertTrue(sbs_info["has_video"] and sbs_info["has_audio"])
        self.assertEqual(sbs_info["width"], clean_info["width"] * 2, "Side-by-side width must equal 2x clean width")

        # Pixel diff proves transformed cat video meaningfully differs from blue human source
        mae = _mean_abs_diff(_sample_rgb_frame(src_path, 0.5), _sample_rgb_frame(clean_path, 0.5))
        self.assertGreater(mae, 35.0, f"V2V output should differ strongly from input source (mae={mae:.1f})")

    def test_03_multi_guest_isolation_idempotency_quota_cancel_and_hygiene(self) -> None:
        sid_owner = "guest_owner_iso"
        sid_other = "guest_intruder_iso"

        st_c, _, resp_c = self._api(
            "POST",
            "/api/projects",
            session_id=sid_owner,
            json_body={
                "title": "test_iso_project_alpha",
                "idea": "孤立测试项目：小猫修复月球望远镜",
                "duration_sec": 180,  # Should be clamped to 30 in guest mode
                "auto_dispatch": False,
            },
        )
        self.assertEqual(st_c, 201)
        pid = resp_c["project"]["id"]
        self.created_pids.add(pid)

        # Verify guest duration was clamped <= 30s (so <= 8 shots & target_seconds <= 30)
        st_own_det, _, own_det = self._api("GET", f"/api/projects/{pid}", session_id=sid_owner)
        self.assertEqual(st_own_det, 200)
        self.assertLessEqual(len(own_det["shots"]), 8, "Guest duration must be clamped <= 30s")
        self.assertLessEqual(own_det["scenes"][0]["target_seconds"], 30)
        first_shot_id = own_det["shots"][0]["id"]
        self.created_shot_ids.add(first_shot_id)

        # Other guest cannot see owner's studio_* project in list
        _, _, list_other = self._api("GET", "/api/projects", session_id=sid_other)
        other_ids = {p["id"] for p in list_other["projects"]}
        self.assertNotIn(pid, other_ids)

        # Other guest gets 403 on owner's detail, patch, preview, dispatch
        st_g, _, _ = self._api("GET", f"/api/projects/{pid}", session_id=sid_other)
        self.assertEqual(st_g, 403)
        st_p, _, _ = self._api(
            "PATCH",
            f"/api/projects/{pid}/shots/{first_shot_id}",
            session_id=sid_other,
            json_body={"summary_zh": "hijack"},
        )
        self.assertEqual(st_p, 403)
        st_d, _, _ = self._api("POST", f"/api/projects/{pid}/dispatch-cloud", session_id=sid_other, json_body={})
        self.assertEqual(st_d, 403)

        # Workspace demos are read-only in guest mode (403)
        st_demo, _, _ = self._api("POST", "/api/projects/starcore/dispatch-cloud", session_id=sid_other, json_body={})
        self.assertEqual(st_demo, 403)

        # Rapid 5x concurrent dispatch by owner must deduplicate into 1 queue job & 1 quota slot
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results = list(
                pool.map(
                    lambda _: self._api("POST", f"/api/projects/{pid}/dispatch-cloud", session_id=sid_owner, json_body={}),
                    range(5),
                )
            )
        statuses = [r[0] for r in results]
        self.assertTrue(all(s == 200 for s in statuses), msg=str(results))
        job_ids = {r[2]["job_id"] for r in results}
        self.assertEqual(len(job_ids), 1, f"5x rapid dispatch must create 1 cloud job, got {job_ids}")
        qid1 = next(iter(job_ids))
        self.assertNotIn("colab_snippet", results[0][2])

        # Other guest cannot view or cancel owner's queue job
        st_q403, _, _ = self._api("GET", f"/api/queue/{qid1}", session_id=sid_other)
        self.assertEqual(st_q403, 403)
        st_qc403, _, _ = self._api("POST", f"/api/queue/{qid1}/cancel", session_id=sid_other, json_body={})
        self.assertEqual(st_qc403, 403)

        # Cancel frees quota cleanly
        st_can, _, can_body = self._api("POST", f"/api/queue/{qid1}/cancel", session_id=sid_owner, json_body={})
        self.assertEqual(st_can, 200)
        self.assertEqual(can_body["job"]["status"], "canceled")

        # Create 4 distinct projects & fill 3/3 quota -> 4th must return 429
        for i in range(4):
            _, _, r_p = self._api(
                "POST",
                "/api/projects",
                session_id=sid_owner,
                json_body={"title": f"test_quota_{i}", "idea": f"配额测试作品 {i}", "duration_sec": 15},
            )
            qid_p = r_p["project"]["id"]
            self.created_pids.add(qid_p)
            st_dp, _, dp_body = self._api("POST", f"/api/projects/{qid_p}/dispatch-cloud", session_id=sid_owner, json_body={})
            if i < 3:
                self.assertEqual(st_dp, 200, msg=str(dp_body))
            else:
                self.assertEqual(st_dp, 429, msg=f"4th active/done job should hit quota 429, got {dp_body}")

        # Bad upload returns 400
        st_bad, _, _ = self._api(
            "POST",
            "/api/uploads?filename=bad_script.txt",
            raw_body=b"not an image or video",
            headers={"Content-Type": "text/plain"},
            session_id=sid_owner,
        )
        self.assertEqual(st_bad, 400)

        # Layer 3: Guest security & notebook protocol check
        st_nb, _, _ = self._api("GET", "/api/farm/colab-notebook", session_id=sid_owner)
        self.assertEqual(st_nb, 403)
        st_sh, _, sh_body = self._api("GET", "/api/share/info", session_id=sid_owner)
        self.assertEqual(st_sh, 200)
        self.assertNotIn("lan_cmd", sh_body)
        self.assertNotIn("public_cmd", sh_body)
        self.assertNotIn("colab_notebook_url", sh_body)

        for ep in ("/api/session", "/api/projects", "/api/share/info", "/api/farm/status"):
            _, _, body_obj = self._api("GET", ep, session_id=sid_owner)
            blob = json.dumps(body_obj, ensure_ascii=False)
            for pat in FORBIDDEN_SECRET_PATTERNS:
                self.assertNotIn(pat, blob, f"Forbidden secret pattern {pat!r} leaked on {ep}")

        # Verify host .ipynb notebook uses real urlencode({"t": FARM_TOKEN, "w": WORKER_NAME}) /boot.py /lab/file/ltx_v2v.py protocol (no X-Farm-Token)
        nb = bridge.build_colab_worker_notebook()
        nb_src = "\n".join("".join(cell.get("source") or []) for cell in nb.get("cells") or [])
        self.assertIn("/boot.py", nb_src)
        self.assertIn("/lab/file/ltx_v2v.py", nb_src)
        self.assertIn("urlencode", nb_src)
        self.assertIn('"t": FARM_TOKEN', nb_src)
        self.assertNotIn("X-Farm-Token", nb_src)


if __name__ == "__main__":
    unittest.main()
