"""Shared cloud compute coordinator bridging Studio projects to farm_server.py (H3 + LTX-2.5 V2V)."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import PREVIEWS_DIR, ROOT, ensure_data_dirs
from . import workflow_engine as wf_engine
from .db import ACTIVE_CLOUD_STATUSES, StudioDB

FFMPEG_BIN = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
FFPROBE_BIN = shutil.which("ffprobe") or "/usr/bin/ffprobe"

# Map preset finished cat videos in videos/classics/ back to authentic human sources in sources/classics/
V2V_RAW_SOURCE_MAP = {
    "videos/classics/三国演义_俺也一样_cat.mp4": "sources/classics/sg_taoyuan.mp4",
    "videos/classics/三国演义_俺也一样_side_by_side.mp4": "sources/classics/sg_taoyuan.mp4",
    "videos/classics/西游记_偷吃人参果_cat.mp4": "sources/classics/xy_renshenguo.mp4",
    "videos/classics/西游记_偷吃人参果_side_by_side.mp4": "sources/classics/xy_renshenguo.mp4",
    "videos/classics/红楼梦_刘姥姥进大观园_cat.mp4": "sources/classics/hlm_liulaolao.mp4",
    "videos/classics/红楼梦_刘姥姥进大观园_side_by_side.mp4": "sources/classics/hlm_liulaolao.mp4",
}


def _media_url(rel_path: str) -> str:
    norm = str(rel_path).replace("\\", "/").lstrip("/")
    return f"/api/media?path={quote(norm, safe='/')}"


def _extract_rel(url_or_path: str | None) -> str | None:
    if not url_or_path:
        return None
    s = str(url_or_path).strip()
    if s.startswith("/api/media"):
        parsed = urlparse(s)
        raw = (parse_qs(parsed.query).get("path") or [None])[0]
        return unquote(raw) if raw else None
    if s.startswith("http://") or s.startswith("https://"):
        return None
    return s.lstrip("/")


def _check_tcp_open(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return default


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _probe_video(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size < 512:
        return {"ok": False, "duration": 0.0, "width": 0, "height": 0, "has_video": False, "has_audio": False}
    try:
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
            timeout=12,
        )
        if proc.returncode != 0:
            return {"ok": False, "duration": 0.0, "width": 0, "height": 0, "has_video": False, "has_audio": False}
        data = json.loads(proc.stdout or "{}")
        streams = data.get("streams") or []
        v_streams = [s for s in streams if s.get("codec_type") == "video"]
        a_streams = [s for s in streams if s.get("codec_type") == "audio"]
        dur = float((data.get("format") or {}).get("duration") or 0.0)
        w = int(v_streams[0].get("width") or 0) if v_streams else 0
        h = int(v_streams[0].get("height") or 0) if v_streams else 0
        return {
            "ok": bool(v_streams) and dur > 0.1 and w > 0 and h > 0,
            "duration": dur,
            "width": w,
            "height": h,
            "has_video": bool(v_streams),
            "has_audio": bool(a_streams),
        }
    except (subprocess.SubprocessError, ValueError, json.JSONDecodeError, OSError):
        return {"ok": False, "duration": 0.0, "width": 0, "height": 0, "has_video": False, "has_audio": False}


def _aspect_dims_for_h3(aspect: str) -> tuple[int, int]:
    if aspect == "9:16":
        return 720, 1280
    if aspect == "4:3":
        return 960, 720
    return 1280, 720


def _aspect_dims_for_v2v(aspect: str) -> tuple[int, int]:
    if aspect == "9:16":
        return 768, 1280
    if aspect == "16:9":
        return 1280, 768
    return 1024, 768


def _assemble_concat_mp4(clips: list[Path], out_abs: Path, dims: tuple[int, int]) -> None:
    """Normalize and concatenate shot clips into a playable H.264/AAC MP4 with +faststart."""
    if not clips:
        raise ValueError("No valid rendered clips to assemble")
    w, h = dims
    tmp_abs = out_abs.with_suffix(".tmp.mp4")
    norm_files: list[Path] = []
    work_dir = out_abs.parent / f".concat_{out_abs.stem}_{uuid.uuid4().hex[:6]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        for idx, clip in enumerate(clips):
            info = _probe_video(clip)
            if not info["ok"]:
                continue
            seg_out = work_dir / f"seg_{idx:03d}.mp4"
            vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=#07080B,fps=24,setsar=1"
            if info["has_audio"]:
                cmd = [
                    FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(clip),
                    "-vf", vf,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
                    str(seg_out),
                ]
            else:
                dur = max(0.5, info["duration"])
                cmd = [
                    FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(clip),
                    "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-vf", vf,
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k", "-shortest",
                    str(seg_out),
                ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if proc.returncode == 0 and seg_out.is_file():
                norm_files.append(seg_out)

        if not norm_files:
            raise RuntimeError("Failed to normalize rendered clips")

        if len(norm_files) == 1:
            cmd = [
                FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(norm_files[0]), "-c", "copy", "-movflags", "+faststart", str(tmp_abs),
            ]
        else:
            list_file = work_dir / "list.txt"
            list_file.write_text(
                "\n".join(f"file '{p.resolve().as_posix()}'" for p in norm_files),
                encoding="utf-8",
            )
            cmd = [
                FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-c", "copy", "-movflags", "+faststart", str(tmp_abs),
            ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if proc.returncode != 0 or not _probe_video(tmp_abs)["ok"]:
            raise RuntimeError(f"FFmpeg concat failed: {proc.stderr[-300:]}")
        tmp_abs.replace(out_abs)
    finally:
        if tmp_abs.exists():
            tmp_abs.unlink(missing_ok=True)
        shutil.rmtree(work_dir, ignore_errors=True)


def _assemble_side_by_side(
    src_mp4: Path,
    cat_mp4: Path,
    out_abs: Path,
    dims: tuple[int, int],
) -> None:
    """Create a 2x-wide side-by-side comparison MP4 (left: original, right: cat V2V)."""
    w, h = dims
    cat_info = _probe_video(cat_mp4)
    if not cat_info["ok"]:
        raise RuntimeError("Invalid V2V final MP4 for side-by-side assembly")
    dur = max(0.5, cat_info["duration"])
    tmp_abs = out_abs.with_suffix(".tmp.mp4")
    audio_map = "1:a:0" if cat_info["has_audio"] else "0:a:0?"
    vf = (
        f"[0:v]trim=duration={dur:.3f},setpts=PTS-STARTPTS,"
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=#07080B,fps=24,setsar=1[vleft];"
        f"[1:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=#07080B,fps=24,setsar=1[vright];"
        f"[vleft][vright]hstack=inputs=2[vout]"
    )
    cmd = [
        FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src_mp4),
        "-i", str(cat_mp4),
        "-filter_complex", vf,
        "-map", "[vout]",
        "-map", audio_map,
        "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
        "-movflags", "+faststart",
        str(tmp_abs),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 or not _probe_video(tmp_abs)["ok"]:
        raise RuntimeError(f"FFmpeg side-by-side assembly failed: {proc.stderr[-300:]}")
    tmp_abs.replace(out_abs)


class CloudCoordinator:
    """Coordinates serialized FIFO H3 and V2V Studio jobs with farm_server.py."""

    def __init__(
        self,
        db: StudioDB,
        broadcast: Callable[[str, dict[str, Any]], None],
        *,
        farm_port: int = 8765,
        farm_dir: Path | None = None,
        poll_interval: float = 0.8,
    ) -> None:
        self.db = db
        self.broadcast = broadcast
        self.farm_port = int(farm_port)
        env_farm = os.environ.get("STUDIO_FARM_DIR")
        self.farm_dir = Path(farm_dir) if farm_dir else (Path(env_farm) if env_farm else (ROOT / "renders" / "farm"))
        self.poll_interval = max(0.25, float(poll_interval))
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        # Runtime per-job tracking of target shot IDs & source metadata
        self._job_ctx: dict[str, dict[str, Any]] = {}

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop, name="cineforge-cloud-coordinator", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=3.0)

    def is_farm_online(self) -> bool:
        return _check_tcp_open("127.0.0.1", self.farm_port)

    def _enrich_job(self, job: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(job)
        enriched["queue_pos"] = self.db.get_queue_position(job["id"]) if job["status"] in ACTIVE_CLOUD_STATUSES else 0
        enriched["farm_online"] = self.is_farm_online()
        return enriched

    def enqueue(
        self,
        *,
        project_id: str,
        owner_session: str,
        mode: str,
        manifest_path: str,
        total_shots: int,
    ) -> tuple[dict[str, Any], bool]:
        with self._lock:
            existing = self.db.get_active_cloud_job_for_project(project_id)
            if existing:
                return self._enrich_job(existing), True

            job_id = f"cq_{uuid.uuid4().hex[:10]}"
            norm_mode = mode if mode in ("v2v", "ltx") else "original"
            farm_up = self.is_farm_online()
            rec = self.db.enqueue_cloud_job(
                {
                    "id": job_id,
                    "project_id": project_id,
                    "owner_session": owner_session,
                    "mode": norm_mode,
                    "status": "queued",
                    "progress": 8,
                    "stage_label": "已进入云端影棚队列" if farm_up else "等待云端影棚上线",
                    "message": (
                        "已排入共享算力队列，即将开始逐镜渲染..."
                        if farm_up
                        else "已排入共享影棚队列，等待云端显卡上线后自动开拍（可先看本地分镜预演）"
                    ),
                    "total_shots": max(1, int(total_shots)),
                    "done_shots": 0,
                    "failed_shots": 0,
                    "manifest_path": manifest_path,
                }
            )
            enriched = self._enrich_job(rec)
            self.broadcast("cloud_queue_updated", {"job": enriched, "project_id": project_id})
            return enriched, False

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self.db.cancel_cloud_job(job_id)
            if not job:
                return None
            self._prune_project_from_farm_files(job["project_id"], job["mode"])
            self._job_ctx.pop(job_id, None)
            enriched = self._enrich_job(job)
            self.broadcast("cloud_queue_updated", {"job": enriched, "project_id": job["project_id"]})
            return enriched

    def get_queue_summary(self, *, owner_session: str | None = None) -> dict[str, Any]:
        active = self.db.list_cloud_queue(active_only=True, limit=100)
        recent = self.db.list_cloud_queue(owner_session=owner_session, active_only=False, limit=30)
        visible_active = [
            self._enrich_job(j)
            for j in active
            if (owner_session is None or j.get("owner_session") == owner_session)
        ]
        return {
            "farm_online": self.is_farm_online(),
            "active_count": len(active),
            "active": visible_active,
            "h3_active": sum(1 for j in active if j["mode"] == "original"),
            "ltx_active": sum(1 for j in active if j["mode"] == "ltx"),
            "v2v_active": sum(1 for j in active if j["mode"] == "v2v"),
            "jobs": [self._enrich_job(j) for j in recent],
        }

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._step_lane("original")
                self._step_lane("ltx")
                self._step_lane("v2v")
            except Exception:
                # Never allow transient filesystem/db hiccup to kill coordinator thread
                pass
            self._stop_event.wait(self.poll_interval)

    def _prune_project_from_farm_files(self, project_id: str, mode: str) -> None:
        if mode == "v2v":
            qname = "lab_jobs_v2v_studio.json"
        elif mode == "ltx":
            qname = "lab_jobs_ltx_studio.json"
        else:
            qname = "studio_h3_queue.json"
        qfile = self.farm_dir / qname
        items = _read_json(qfile, [])
        if isinstance(items, list):
            prefix = f"{project_id}_"
            kept = [
                it for it in items
                if isinstance(it, dict)
                and it.get("project_id") != project_id
                and not str(it.get("id", "")).startswith(prefix)
            ]
            if len(kept) != len(items):
                _atomic_write_json(qfile, kept)

    def _update_and_broadcast(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        updated = self.db.update_cloud_job(job_id, **fields)
        if updated:
            enriched = self._enrich_job(updated)
            self.broadcast("cloud_queue_updated", {"job": enriched, "project_id": updated["project_id"]})
            return enriched
        return None

    def _step_lane(self, mode: str) -> None:
        lane_jobs = [
            j for j in self.db.list_cloud_queue(active_only=True, limit=100)
            if j["mode"] == mode
        ]
        if not lane_jobs:
            return

        active = lane_jobs[0]
        farm_online = self.is_farm_online()

        # Update queued waiting jobs' messages if needed
        for pos_idx, qj in enumerate(lane_jobs, start=1):
            if qj["status"] != "queued":
                continue
            if qj["id"] != active["id"]:
                lbl = f"队列排队中（第 {pos_idx} 位）"
                msg = f"前方还有 {pos_idx - 1} 个影片正在拍片，请稍候..."
                if qj["stage_label"] != lbl or qj["message"] != msg:
                    self._update_and_broadcast(qj["id"], stage_label=lbl, message=msg)

        if active["status"] == "queued":
            if not farm_online:
                lbl = "等待云端影棚上线"
                msg = f"已排入第 {self.db.get_queue_position(active['id'])} 位，等待云端显卡上线自动开拍（可先看本地分镜预演）"
                if active["stage_label"] != lbl or active["message"] != msg:
                    self._update_and_broadcast(active["id"], stage_label=lbl, message=msg)
                return

            if mode == "original":
                self._stage_h3_job(active)
            elif mode == "ltx":
                self._stage_ltx_job(active)
            else:
                self._stage_v2v_job(active)
            return

        if mode == "original":
            self._poll_h3_job(active)
        elif mode == "ltx":
            self._poll_ltx_job(active)
        else:
            self._poll_v2v_job(active)

    # ---------- Lane 1: MiniMax H3 Original Films ----------

    def _load_project_shots_with_overlays(self, project_id: str) -> list[dict[str, Any]]:
        s01_path = ROOT / "workflows" / project_id / "shots" / "S01.json"
        if not s01_path.is_file():
            alt = ROOT / "films" / project_id / "shots" / "S01.json"
            if alt.is_file():
                s01_path = alt
        shots = _read_json(s01_path, []) or []
        overlays = self.db.get_shot_overlays(project_id)
        merged: list[dict[str, Any]] = []
        for sh in shots:
            if not isinstance(sh, dict) or not sh.get("id"):
                continue
            item = dict(sh)
            ov = overlays.get(item["id"])
            if ov:
                if ov.get("status"):
                    item["status"] = ov["status"]
                if ov.get("summary_zh") is not None:
                    item["summary_zh"] = ov["summary_zh"]
                if ov.get("prompt") is not None:
                    item["prompt"] = ov["prompt"]
            merged.append(item)
        return merged

    def _ensure_h3_refs(self, project_id: str, raw_refs: list[str]) -> list[str]:
        valid: list[str] = []
        assets_root = (ROOT / "assets").resolve()
        for r in raw_refs:
            p = (ROOT / r).resolve()
            if assets_root in p.parents and p.is_file():
                valid.append(p.relative_to(ROOT.resolve()).as_posix())
        if not valid:
            refs_dir = ROOT / "assets" / project_id / "refs"
            if refs_dir.is_dir():
                for img in sorted(refs_dir.iterdir()):
                    if img.is_file() and img.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                        valid.append(img.relative_to(ROOT).as_posix())
                        break
        if not valid:
            for fb_rel in (
                "assets/starlight_arm/s01_first.jpg",
                "docs/showcase/media/sanguo_anye.webp",
                "docs/showcase/media/starcore_battle.webp",
            ):
                fb = ROOT / fb_rel
                if fb.is_file():
                    if fb_rel.startswith("assets/"):
                        valid.append(fb_rel)
                    else:
                        refs_dir = ROOT / "assets" / project_id / "refs"
                        refs_dir.mkdir(parents=True, exist_ok=True)
                        dst = refs_dir / f"ref_fb{fb.suffix}"
                        if not dst.is_file():
                            shutil.copy2(fb, dst)
                        valid.append(dst.relative_to(ROOT).as_posix())
                    break
        return valid

    def _stage_h3_job(self, job: dict[str, Any]) -> None:
        pid = job["project_id"]
        shots = self._load_project_shots_with_overlays(pid)
        if not shots:
            self._update_and_broadcast(
                job["id"],
                status="failed",
                progress=100,
                stage_label="分镜脚本缺失",
                error="Missing shots",
                message="未找到该项目的分镜脚本",
            )
            return

        saved_wf = wf_engine.load_saved_workflow(pid)
        wf_ov = wf_engine.extract_runtime_overrides(saved_wf) if saved_wf else {}

        queue_entries: list[dict[str, Any]] = []
        target_ids: list[str] = []
        for idx, sh in enumerate(shots):
            sid = str(sh["id"])
            target_ids.append(sid)
            raw_mp4 = ROOT / "renders" / sid / "raw.mp4"
            job_json = _read_json(ROOT / "renders" / sid / "job.json", {})
            if raw_mp4.is_file() and isinstance(job_json, dict) and job_json.get("status") == "completed":
                continue
            entry: dict[str, Any] = {
                "id": sid,
                "project_id": pid,
                "prompt": str(wf_ov.get("prompt_override") or sh.get("prompt") or sh.get("summary_zh") or "Cinematic film shot"),
                "seconds": int(round(float(wf_ov.get("seconds") or sh.get("seconds") or 5))),
                "refs": self._ensure_h3_refs(pid, list(sh.get("refs") or [])),
            }
            for k in ("steps", "width", "height", "lora_strength", "sampler_name"):
                if k in wf_ov and wf_ov[k] is not None:
                    entry[k] = wf_ov[k]
            if wf_ov.get("seed"):
                entry["seed"] = int(wf_ov["seed"]) + idx
            queue_entries.append(entry)

        self._job_ctx[job["id"]] = {"shot_ids": target_ids}
        qfile = self.farm_dir / "studio_h3_queue.json"
        _atomic_write_json(qfile, queue_entries)

        total = len(target_ids)
        done = total - len(queue_entries)
        pct = 15 + int(70 * done / max(1, total))
        self._update_and_broadcast(
            job["id"],
            status="rendering",
            progress=pct,
            stage_label="AI 云端逐镜拍片中",
            message=f"正在云端 GPU 逐镜生成（{done}/{total} 镜完成）",
            total_shots=total,
            done_shots=done,
            failed_shots=0,
        )

    def _poll_h3_job(self, job: dict[str, Any]) -> None:
        pid = job["project_id"]
        ctx = self._job_ctx.get(job["id"])
        if not ctx:
            shots = self._load_project_shots_with_overlays(pid)
            ctx = {"shot_ids": [str(s["id"]) for s in shots]}
            self._job_ctx[job["id"]] = ctx

        shot_ids: list[str] = ctx["shot_ids"]
        total = max(1, len(shot_ids))
        valid_clips: list[Path] = []
        failed_count = 0

        for sid in shot_ids:
            raw_mp4 = ROOT / "renders" / sid / "raw.mp4"
            job_json = _read_json(ROOT / "renders" / sid / "job.json", {})
            if raw_mp4.is_file() and isinstance(job_json, dict) and job_json.get("status") == "completed":
                if _probe_video(raw_mp4)["ok"]:
                    valid_clips.append(raw_mp4)
                    ov = self.db.get_shot_overlay(pid, sid) or {}
                    if ov.get("status") in (None, "draft", "rendering", "retake"):
                        self.db.upsert_shot_overlay(pid, sid, {"status": "review"})
                        self.broadcast(
                            "shot_updated",
                            {
                                "project_id": pid,
                                "shot_id": sid,
                                "shot": {
                                    "id": sid,
                                    "status": "review",
                                    "video_url": _media_url(f"renders/{sid}/raw.mp4"),
                                },
                            },
                        )
                    continue

            claim_json = _read_json(ROOT / "renders" / sid / "claim.json", {})
            if isinstance(claim_json, dict) and claim_json.get("status") == "failed" and int(claim_json.get("attempts") or 0) >= 3:
                failed_count += 1

        done_count = len(valid_clips)
        pct = 15 + int(70 * (done_count + failed_count) / total)
        if done_count != job["done_shots"] or failed_count != job["failed_shots"]:
            self._update_and_broadcast(
                job["id"],
                status="rendering",
                progress=pct,
                done_shots=done_count,
                failed_shots=failed_count,
                stage_label="AI 云端逐镜拍片中",
                message=f"正在云端 GPU 逐镜生成（{done_count}/{total} 镜完成）",
            )

        if done_count + failed_count < total:
            return

        self._prune_project_from_farm_files(pid, "original")
        if done_count == 0:
            self._update_and_broadcast(
                job["id"],
                status="failed",
                progress=100,
                stage_label="云端拍片失败",
                error="All shots failed",
                message="所有镜头均未能完成渲染，请检查或简化描述后重试",
            )
            return

        self._update_and_broadcast(
            job["id"],
            status="assembling",
            progress=90,
            stage_label="正在自动拼接配乐成片",
            message="分镜已全部出片，正在合成为可播放 MP4 成片...",
        )
        try:
            ensure_data_dirs()
            proj = self.db.get_studio_project(pid) or {}
            dims = _aspect_dims_for_h3(str(proj.get("aspect") or "16:9"))
            final_abs = PREVIEWS_DIR / f"{pid}_final.mp4"
            _assemble_concat_mp4(valid_clips, final_abs, dims)
            final_rel = f"studio/data/previews/{pid}_final.mp4"
            final_url = _media_url(final_rel)
            states = {
                "script": "done", "refs": "done", "storyboard": "done",
                "render": "done", "qa": "done", "master": "done",
            }
            self.db.update_studio_project(pid, final_video_url=final_url, stage_index=5, stages_state=states)
            self.db.upsert_stage_override(pid, stage_index=5, stages_state=states)
            self._update_and_broadcast(
                job["id"],
                status="completed",
                progress=100,
                stage_label="成片已生成",
                message="全部镜头渲染并拼接完成，可直接播放或下载！",
                done_shots=done_count,
                failed_shots=failed_count,
                output_url=final_url,
            )
        except Exception as exc:  # noqa: BLE001
            self._update_and_broadcast(
                job["id"],
                status="failed",
                progress=100,
                stage_label="成片拼接失败",
                error=str(exc)[:200],
                message=f"成片合成失败：{str(exc)[:140]}",
            )

    # ---------- Lane 1b: LTX-2.5 Original Films ----------

    def _stage_ltx_job(self, job: dict[str, Any]) -> None:
        pid = job["project_id"]
        studio_proj = self.db.get_studio_project(pid) or {}
        shots = self._load_project_shots_with_overlays(pid)
        if not shots:
            self._update_and_broadcast(
                job["id"],
                status="failed",
                progress=100,
                stage_label="分镜脚本缺失",
                error="Missing shots",
                message="未找到该项目的分镜脚本",
            )
            return

        saved_wf = wf_engine.load_saved_workflow(pid)
        wf_ov = wf_engine.extract_runtime_overrides(saved_wf) if saved_wf else {}
        dims = (int(wf_ov.get("width") or 1344), int(wf_ov.get("height") or 768))
        ltx_out_dir = ROOT / "renders" / "lab" / "ltx_studio"
        entries: list[dict[str, Any]] = []
        shot_ids: list[str] = []
        for idx, sh in enumerate(shots):
            sid = str(sh["id"])
            shot_ids.append(sid)
            out_mp4 = ltx_out_dir / f"{sid}_distilled.mp4"
            if out_mp4.is_file() and _probe_video(out_mp4)["ok"]:
                continue
            kf_rel = self._stage_v2v_kf(pid, sid, studio_proj, dims)
            base_seed = int(wf_ov.get("seed") or 42)
            entries.append(
                {
                    "id": sid,
                    "project_id": pid,
                    "seconds": max(3, min(10, int(round(float(wf_ov.get("seconds") or sh.get("seconds") or 5))))),
                    "keyframe": kf_rel,
                    "prompt": str(wf_ov.get("prompt_override") or sh.get("prompt") or sh.get("summary_zh") or "Cinematic film shot"),
                    "seed": base_seed + idx,
                }
            )

        self._job_ctx[job["id"]] = {"shot_ids": shot_ids, "dims": dims}
        qfile = self.farm_dir / "lab_jobs_ltx_studio.json"
        _atomic_write_json(qfile, entries)

        total = len(shot_ids)
        done = total - len(entries)
        pct = 15 + int(70 * done / max(1, total))
        self._update_and_broadcast(
            job["id"],
            status="rendering",
            progress=pct,
            stage_label="LTX-2.5 云端逐镜拍片中",
            message=f"正在云端 GPU 用 LTX-2.5 逐镜生成（{done}/{total} 镜完成）",
            total_shots=total,
            done_shots=done,
            failed_shots=0,
        )

    def _poll_ltx_job(self, job: dict[str, Any]) -> None:
        pid = job["project_id"]
        ctx = self._job_ctx.get(job["id"])
        if not ctx:
            shots = self._load_project_shots_with_overlays(pid)
            ctx = {"shot_ids": [str(s["id"]) for s in shots], "dims": (1344, 768)}
            self._job_ctx[job["id"]] = ctx

        shot_ids: list[str] = ctx["shot_ids"]
        total = max(1, len(shot_ids))
        ltx_dir = ROOT / "renders" / "lab" / "ltx_studio"
        valid_clips: list[Path] = []
        for sid in shot_ids:
            mp4 = ltx_dir / f"{sid}_distilled.mp4"
            if not mp4.is_file():
                alt = ltx_dir / f"{sid}_dfr.mp4"
                if alt.is_file():
                    mp4 = alt
            if mp4.is_file() and _probe_video(mp4)["ok"]:
                valid_clips.append(mp4)
                ov = self.db.get_shot_overlay(pid, sid) or {}
                if ov.get("status") in (None, "draft", "rendering", "retake"):
                    self.db.upsert_shot_overlay(pid, sid, {"status": "review"})
                    rel = mp4.relative_to(ROOT).as_posix()
                    self.broadcast(
                        "shot_updated",
                        {
                            "project_id": pid,
                            "shot_id": sid,
                            "shot": {"id": sid, "status": "review", "video_url": _media_url(rel)},
                        },
                    )

        done_count = len(valid_clips)
        pct = 15 + int(70 * done_count / total)
        if done_count != job["done_shots"]:
            self._update_and_broadcast(
                job["id"],
                status="rendering",
                progress=pct,
                done_shots=done_count,
                stage_label="LTX-2.5 云端逐镜拍片中",
                message=f"正在云端 GPU 用 LTX-2.5 逐镜生成（{done_count}/{total} 镜完成）",
            )

        if done_count < total:
            return

        self._prune_project_from_farm_files(pid, "ltx")
        self._update_and_broadcast(
            job["id"],
            status="assembling",
            progress=90,
            stage_label="正在自动拼接 LTX-2.5 成片",
            message="分镜已全部出片，正在合成为可播放 MP4 成片...",
        )
        try:
            ensure_data_dirs()
            proj = self.db.get_studio_project(pid) or {}
            dims = _aspect_dims_for_h3(str(proj.get("aspect") or "16:9"))
            final_abs = PREVIEWS_DIR / f"{pid}_final.mp4"
            _assemble_concat_mp4(valid_clips, final_abs, dims)
            final_url = _media_url(f"studio/data/previews/{pid}_final.mp4")
            states = {
                "script": "done", "refs": "done", "storyboard": "done",
                "render": "done", "qa": "done", "master": "done",
            }
            self.db.update_studio_project(pid, final_video_url=final_url, stage_index=5, stages_state=states)
            self.db.upsert_stage_override(pid, stage_index=5, stages_state=states)
            self._update_and_broadcast(
                job["id"],
                status="completed",
                progress=100,
                stage_label="LTX-2.5 成片已生成",
                message="全部镜头渲染并拼接完成，可直接播放或下载！",
                done_shots=done_count,
                output_url=final_url,
            )
        except Exception as exc:  # noqa: BLE001
            self._update_and_broadcast(
                job["id"],
                status="failed",
                progress=100,
                stage_label="成片拼接失败",
                error=str(exc)[:200],
                message=f"LTX-2.5 成片合成失败：{str(exc)[:140]}",
            )

    # ---------- Lane 2: LTX-2.5 V2V Cat-Swap Films ----------

    def _resolve_v2v_source(self, project_id: str, studio_proj: dict[str, Any]) -> str:
        raw_url = studio_proj.get("source_video_url")
        rel = _extract_rel(raw_url)
        if rel and rel in V2V_RAW_SOURCE_MAP:
            mapped = V2V_RAW_SOURCE_MAP[rel]
            if (ROOT / mapped).is_file():
                return mapped
        if rel and (rel.startswith("sources/") or rel.startswith("studio/data/uploads/")):
            p = (ROOT / rel).resolve()
            if p.is_file():
                return p.relative_to(ROOT.resolve()).as_posix()
        # If user selected a clip outside sources/ & uploads/, copy into uploads so /lab/src can serve it
        if rel and (ROOT / rel).is_file():
            ensure_data_dirs()
            dst = ROOT / "studio" / "data" / "uploads" / f"src_{project_id}.mp4"
            if not dst.is_file():
                shutil.copy2(ROOT / rel, dst)
            return dst.relative_to(ROOT).as_posix()
        # Final fallback to classic Three Kingdoms human source or showcase clip
        for fb in ("sources/classics/sg_taoyuan.mp4", "docs/showcase/media/sanguo_anye.mp4"):
            if (ROOT / fb).is_file():
                if fb.startswith("sources/"):
                    return fb
                ensure_data_dirs()
                dst = ROOT / "studio" / "data" / "uploads" / f"src_{project_id}.mp4"
                if not dst.is_file():
                    shutil.copy2(ROOT / fb, dst)
                return dst.relative_to(ROOT).as_posix()
        raise FileNotFoundError("No usable V2V source video found")

    def _stage_v2v_kf(self, project_id: str, shot_id: str, studio_proj: dict[str, Any], dims: tuple[int, int]) -> str:
        kf_dir = ROOT / "assets" / project_id / "lab_kf_ltx"
        kf_dir.mkdir(parents=True, exist_ok=True)
        kf_abs = kf_dir / f"{shot_id}.png"
        if not kf_abs.is_file():
            src_img: Path | None = None
            for u in studio_proj.get("ref_images") or []:
                rel = _extract_rel(u)
                if rel and (ROOT / rel).is_file():
                    src_img = ROOT / rel
                    break
            if src_img is None:
                refs_dir = ROOT / "assets" / project_id / "refs"
                if refs_dir.is_dir():
                    for p in sorted(refs_dir.iterdir()):
                        if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                            src_img = p
                            break
            if src_img is None:
                for fb_rel in ("assets/classics/refs/zhangfei.png", "docs/showcase/media/sanguo_anye.webp"):
                    fb = ROOT / fb_rel
                    if fb.is_file():
                        src_img = fb
                        break
            w, h = dims
            if src_img is not None:
                proc = subprocess.run(
                    [
                        FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(src_img),
                        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}",
                        "-frames:v", "1", str(kf_abs),
                    ],
                    capture_output=True,
                    timeout=20,
                )
                if proc.returncode != 0 or not kf_abs.is_file():
                    shutil.copy2(src_img, kf_abs)
            else:
                subprocess.run(
                    [
                        FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", f"color=c=#F5B041:s={w}x{h}",
                        "-frames:v", "1", str(kf_abs),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=15,
                )
        return kf_abs.relative_to(ROOT).as_posix()

    def _stage_v2v_job(self, job: dict[str, Any]) -> None:
        pid = job["project_id"]
        studio_proj = self.db.get_studio_project(pid) or {}
        shots = self._load_project_shots_with_overlays(pid)
        if not shots:
            self._update_and_broadcast(
                job["id"],
                status="failed",
                progress=100,
                stage_label="分镜脚本缺失",
                error="Missing shots",
                message="未找到该 V2V 项目的分镜脚本",
            )
            return

        try:
            src_rel = self._resolve_v2v_source(pid, studio_proj)
        except Exception as exc:  # noqa: BLE001
            self._update_and_broadcast(
                job["id"],
                status="failed",
                progress=100,
                stage_label="原片素材不可用",
                error=str(exc),
                message="未找到可用的原片视频素材",
            )
            return

        src_abs = ROOT / src_rel
        src_info = _probe_video(src_abs)
        if not src_info["ok"]:
            self._update_and_broadcast(
                job["id"],
                status="failed",
                progress=100,
                stage_label="原片无法解码",
                error="Corrupt source video",
                message="上传或选中的原片视频损坏，无法解码",
            )
            return

        src_dur = max(1.0, float(src_info["duration"]))
        dims = _aspect_dims_for_v2v(str(studio_proj.get("aspect") or "4:3"))
        v2v_opts = studio_proj.get("v2v_options") or {}
        clean_band = bool(v2v_opts.get("desub", True))
        no_audio = not bool(v2v_opts.get("keep_audio", True))

        # Keep V2V responsive: partition source duration cleanly across up to 4 shots
        target_shots = shots[:4] if src_dur <= 20 else shots[:6]
        seg_count = max(1, len(target_shots))
        seg_dur = max(1.5, min(8.0, src_dur / seg_count))

        v2v_entries: list[dict[str, Any]] = []
        shot_ids: list[str] = []
        v2v_out_dir = ROOT / "renders" / "lab" / "v2v_studio"
        for i, sh in enumerate(target_shots):
            sid = str(sh["id"])
            shot_ids.append(sid)
            start_t = round(min(max(0.0, src_dur - 1.0), i * seg_dur), 2)
            dur_t = round(min(seg_dur, max(1.0, src_dur - start_t)), 2)
            out_mp4 = v2v_out_dir / f"{sid}.mp4"
            if out_mp4.is_file() and _probe_video(out_mp4)["ok"]:
                continue
            kf_rel = self._stage_v2v_kf(pid, sid, studio_proj, dims)
            v2v_entries.append(
                {
                    "id": sid,
                    "project_id": pid,
                    "source_url": src_rel,
                    "start": start_t,
                    "dur": dur_t,
                    "control": "depth",
                    "keyframe": kf_rel,
                    "prompt": str(sh.get("prompt") or sh.get("summary_zh") or "Anthropomorphic cat reenactment"),
                    "width": dims[0],
                    "height": dims[1],
                    "seed": 42 + i,
                    "clean_band": clean_band,
                    "no_audio": no_audio,
                }
            )

        self._job_ctx[job["id"]] = {
            "shot_ids": shot_ids,
            "src_rel": src_rel,
            "dims": dims,
        }
        qfile = self.farm_dir / "lab_jobs_v2v_studio.json"
        _atomic_write_json(qfile, v2v_entries)

        total = len(shot_ids)
        done = total - len(v2v_entries)
        pct = 15 + int(70 * done / max(1, total))
        self._update_and_broadcast(
            job["id"],
            status="rendering",
            progress=pct,
            stage_label="AI 猫咪换角渲染中",
            message=f"正在执行原声口型与去字幕猫咪重绘（{done}/{total} 段完成）",
            total_shots=total,
            done_shots=done,
            failed_shots=0,
        )

    def _poll_v2v_job(self, job: dict[str, Any]) -> None:
        pid = job["project_id"]
        studio_proj = self.db.get_studio_project(pid) or {}
        ctx = self._job_ctx.get(job["id"])
        if not ctx:
            shots = self._load_project_shots_with_overlays(pid)
            src_rel = self._resolve_v2v_source(pid, studio_proj)
            dims = _aspect_dims_for_v2v(str(studio_proj.get("aspect") or "4:3"))
            src_info = _probe_video(ROOT / src_rel)
            seg_count = len(shots[:4]) if src_info["duration"] <= 20 else len(shots[:6])
            ctx = {"shot_ids": [str(s["id"]) for s in shots[:seg_count]], "src_rel": src_rel, "dims": dims}
            self._job_ctx[job["id"]] = ctx

        shot_ids: list[str] = ctx["shot_ids"]
        total = max(1, len(shot_ids))
        v2v_dir = ROOT / "renders" / "lab" / "v2v_studio"
        valid_clips: list[Path] = []
        for sid in shot_ids:
            mp4 = v2v_dir / f"{sid}.mp4"
            if mp4.is_file() and _probe_video(mp4)["ok"]:
                valid_clips.append(mp4)
                ov = self.db.get_shot_overlay(pid, sid) or {}
                if ov.get("status") in (None, "draft", "rendering", "retake"):
                    self.db.upsert_shot_overlay(pid, sid, {"status": "review"})
                    self.broadcast(
                        "shot_updated",
                        {
                            "project_id": pid,
                            "shot_id": sid,
                            "shot": {
                                "id": sid,
                                "status": "review",
                                "video_url": _media_url(f"renders/lab/v2v_studio/{sid}.mp4"),
                            },
                        },
                    )

        done_count = len(valid_clips)
        pct = 15 + int(70 * done_count / total)
        if done_count != job["done_shots"]:
            self._update_and_broadcast(
                job["id"],
                status="rendering",
                progress=pct,
                done_shots=done_count,
                stage_label="AI 猫咪换角渲染中",
                message=f"正在执行原声口型与去字幕猫咪重绘（{done_count}/{total} 段完成）",
            )

        if done_count < total:
            return

        self._prune_project_from_farm_files(pid, "v2v")
        self._update_and_broadcast(
            job["id"],
            status="assembling",
            progress=90,
            stage_label="正在生成纯净猫咪版与左右对照版",
            message="正在合成猫咪成片与原片左右同步对照视频...",
        )
        try:
            ensure_data_dirs()
            dims = tuple(ctx["dims"])
            src_abs = ROOT / ctx["src_rel"]
            final_abs = PREVIEWS_DIR / f"{pid}_final.mp4"
            sbs_abs = PREVIEWS_DIR / f"{pid}_side_by_side.mp4"
            _assemble_concat_mp4(valid_clips, final_abs, dims)
            _assemble_side_by_side(src_abs, final_abs, sbs_abs, dims)
            final_url = _media_url(f"studio/data/previews/{pid}_final.mp4")
            sbs_url = _media_url(f"studio/data/previews/{pid}_side_by_side.mp4")
            states = {
                "script": "done", "refs": "done", "storyboard": "done",
                "render": "done", "qa": "done", "master": "done",
            }
            self.db.update_studio_project(
                pid,
                final_video_url=final_url,
                side_by_side_url=sbs_url,
                stage_index=5,
                stages_state=states,
            )
            self.db.upsert_stage_override(pid, stage_index=5, stages_state=states)
            self._update_and_broadcast(
                job["id"],
                status="completed",
                progress=100,
                stage_label="猫咪换角成片已生成",
                message="纯净猫咪版与左右原片对照版均已生成，可直接播放或下载！",
                done_shots=done_count,
                output_url=final_url,
                side_by_side_url=sbs_url,
            )
        except Exception as exc:  # noqa: BLE001
            self._update_and_broadcast(
                job["id"],
                status="failed",
                progress=100,
                stage_label="对照版合成失败",
                error=str(exc)[:200],
                message=f"V2V 成片合成失败：{str(exc)[:140]}",
            )
