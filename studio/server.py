"""CineForge Studio HTTP + SSE server (Python 3.14 stdlib only)."""

from __future__ import annotations

import argparse
import hmac
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import queue
import re
import signal
import sys
import threading
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
import uuid

# Support running both as `python3 studio/server.py` and `python3 -m studio.server`
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio import PUBLIC_DIR, VERSION, ensure_data_dirs  # noqa: E402
from studio.cloud_coordinator import CloudCoordinator  # noqa: E402
from studio.db import StudioDB  # noqa: E402
from studio import pipeline_bridge as bridge  # noqa: E402
from studio import workflow_engine as wf_engine  # noqa: E402

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,48}$")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".ico": "image/x-icon",
}


class EventBroker:
    """Thread-safe Server-Sent Events pub/sub broker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: set[queue.Queue[tuple[str, str]]] = set()

    def subscribe(self) -> queue.Queue[tuple[str, str]]:
        q: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=64)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue[tuple[str, str]]) -> None:
        with self._lock:
            self._subs.discard(q)

    def broadcast(self, event: str, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait((event, data))
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait((event, data))
                except queue.Empty:
                    pass

    def wake_all(self) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(("__shutdown__", "{}"))
            except queue.Full:
                pass


class StudioHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[BaseHTTPRequestHandler],
        db: StudioDB,
        *,
        guest_mode: bool = False,
        invite_code: str | None = None,
        farm_port: int = 8765,
        max_guest_jobs: int = 3,
        max_guest_duration: int = 30,
    ):
        super().__init__(server_address, handler_cls)
        self.db = db
        self.broker = EventBroker()
        self.shutdown_event = threading.Event()
        self.bound_port = self.server_address[1]
        self.guest_mode = bool(guest_mode)
        self.invite_code = (invite_code or "").strip() or None
        self.farm_port = int(farm_port)
        self.max_guest_jobs = max(1, int(max_guest_jobs))
        self.max_guest_duration = max(15, int(max_guest_duration))
        self.coordinator = CloudCoordinator(
            db,
            self.broker.broadcast,
            farm_port=self.farm_port,
        )
        self.coordinator.start()

    def server_close(self) -> None:
        self.shutdown_event.set()
        self.coordinator.stop()
        self.broker.wake_all()
        super().server_close()


def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int] | None:
    """Parse HTTP `Range: bytes=start-end` header; returns (start, end) inclusive or None if invalid."""
    m = re.match(r"^bytes=(\d*)-(\d*)$", range_header.strip())
    if not m or file_size <= 0:
        return None
    start_s, end_s = m.groups()
    if not start_s and not end_s:
        return None
    if start_s and end_s:
        start, end = int(start_s), int(end_s)
    elif start_s:
        start, end = int(start_s), file_size - 1
    else:
        suffix = int(end_s)
        if suffix <= 0:
            return None
        start = max(0, file_size - suffix)
        end = file_size - 1
    if start < 0 or start >= file_size or end < start:
        return None
    end = min(end, file_size - 1)
    return start, end


class StudioHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: StudioHTTPServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Never log query secrets or noisy static hits; keep concise sanitized line on stderr if verbose
        if os.environ.get("STUDIO_VERBOSE_LOG") == "1":
            msg = bridge.sanitize_text(format % args)
            sys.stderr.write(f"[studio] {self.address_string()} {msg}\n")

    def _resolve_session(self) -> str:
        cached = getattr(self, "_resolved_session", None)
        if cached:
            return cached
        hdr_sid = (self.headers.get("X-Studio-Session") or "").strip()
        if hdr_sid and SESSION_ID_RE.fullmatch(hdr_sid):
            self._resolved_session = hdr_sid
            self._pending_session_cookie = None
            return hdr_sid
        raw_cookie = self.headers.get("Cookie") or ""
        if raw_cookie:
            cookie = SimpleCookie()
            try:
                cookie.load(raw_cookie)
                morsel = cookie.get("studio_sid")
                if morsel and SESSION_ID_RE.fullmatch(morsel.value):
                    self._resolved_session = morsel.value
                    self._pending_session_cookie = None
                    return morsel.value
            except Exception:  # noqa: BLE001
                pass
        sid = f"g_{uuid.uuid4().hex[:16]}"
        self._resolved_session = sid
        self._pending_session_cookie = sid
        return sid

    def _emit_session_cookie(self) -> None:
        sid = getattr(self, "_pending_session_cookie", None)
        if sid:
            self.send_header("Set-Cookie", f"studio_sid={sid}; Path=/; SameSite=Lax; Max-Age=2592000")
            self._pending_session_cookie = None

    def _require_project_read_access(self, pid: str, sid: str) -> bool:
        if not self.server.guest_mode or not pid.startswith("studio_"):
            return True
        rec = self.server.db.get_studio_project(pid)
        if not rec:
            return True
        if (rec.get("owner_session") or "") != sid:
            self._send_error_json(403, "仅可访问您当前会话创建的作品")
            return False
        return True

    def _require_project_write_access(self, pid: str, sid: str) -> bool:
        if not self.server.guest_mode:
            return True
        if not pid.startswith("studio_"):
            self._send_error_json(403, "访客体验模式仅支持编辑您自己新建的作品（左侧「一键做视频」即可创作）")
            return False
        rec = self.server.db.get_studio_project(pid)
        if not rec:
            return True
        if (rec.get("owner_session") or "") != sid:
            self._send_error_json(403, "无权修改其他访客会话的作品")
            return False
        return True

    def _send_json(self, data: Any, status: int = 200) -> None:
        self._resolve_session()
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._emit_session_cookie()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json({"ok": False, "error": message}, status=status)

    def _require_invite_for_write(self, qs: dict[str, list[str]]) -> bool:
        """
        Enforce optional --invite-code ONLY when explicitly configured, and ONLY on write requests.
        Zero-friction by default (invite_code=None).
        """
        expected = self.server.invite_code
        if not expected:
            return True
        provided = (
            self.headers.get("X-Invite-Code")
            or (qs.get("invite_code") or [""])[0]
        ).strip()
        if provided and hmac.compare_digest(provided, expected):
            return True
        self._send_error_json(401, "需要有效的访客邀请口令 (X-Invite-Code)")
        return False

    def _read_body_bytes(self, max_bytes: int = 105 * 1024 * 1024) -> bytes:
        cl = self.headers.get("Content-Length")
        if cl is None:
            return b""
        try:
            length = int(cl)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length < 0 or length > max_bytes:
            raise ValueError("Request body too large")
        return self.rfile.read(length) if length > 0 else b""

    def _read_json_body(self) -> dict[str, Any]:
        raw = self._read_body_bytes(max_bytes=20 * 1024 * 1024)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求体不是有效的 JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("JSON 顶层必须是对象")
        return parsed

    def _guess_content_type(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext in CONTENT_TYPES:
            return CONTENT_TYPES[ext]
        ct, _ = mimetypes.guess_type(str(path))
        return ct or "application/octet-stream"

    # ---------- Media & Static File Serving ----------

    def _serve_file(
        self,
        file_path: Path,
        *,
        support_range: bool = True,
        cache_header: str = "public, max-age=300",
        emit_session_cookie: bool = False,
    ) -> None:
        try:
            stat = file_path.stat()
        except OSError:
            self._send_error_json(404, "File not found")
            return
        if emit_session_cookie:
            self._resolve_session()
        file_size = stat.st_size
        ctype = self._guess_content_type(file_path)
        range_hdr = self.headers.get("Range") if support_range else None

        start = 0
        end = file_size - 1
        status = 200
        if range_hdr:
            parsed = _parse_range_header(range_hdr, file_size)
            if parsed is None:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            start, end = parsed
            status = 206

        length = max(0, end - start + 1) if file_size > 0 else 0
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", cache_header)
        if emit_session_cookie and status == 200:
            self._emit_session_cookie()
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(length))
        self.end_headers()

        if self.command == "HEAD" or length == 0:
            return

        chunk_size = 64 * 1024
        remaining = length
        try:
            with file_path.open("rb") as fh:
                fh.seek(start)
                while remaining > 0:
                    data = fh.read(min(chunk_size, remaining))
                    if not data:
                        break
                    self.wfile.write(data)
                    remaining -= len(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _handle_media(self, qs: dict[str, list[str]]) -> None:
        raw_path = (qs.get("path") or [None])[0]
        rel_path = unquote(raw_path) if raw_path is not None else None
        status, file_path = bridge.resolve_media_path(rel_path)
        if status != 200 or file_path is None:
            self._send_error_json(status, "Forbidden media path" if status == 403 else "Media not found")
            return
        self._serve_file(file_path, support_range=True, cache_header="public, max-age=600")

    def _handle_static(self, req_path: str) -> None:
        pub_root = PUBLIC_DIR.resolve()
        if not pub_root.is_dir():
            self._send_error_json(404, "Frontend assets not installed in studio/public/")
            return

        rel = unquote(req_path).lstrip("/")
        if not rel or rel.endswith("/"):
            rel = rel + "index.html"

        try:
            target = (pub_root / rel).resolve()
        except OSError:
            self._send_error_json(403, "Invalid static path")
            return

        if not target.is_relative_to(pub_root):
            self._send_error_json(403, "Forbidden static path")
            return

        if target.is_file():
            cache = "no-cache" if target.suffix.lower() in (".html", ".js", ".css") else "public, max-age=300"
            self._serve_file(
                target,
                support_range=False,
                cache_header=cache,
                emit_session_cookie=(target.name == "index.html"),
            )
            return

        # SPA fallback to index.html for extension-less routes
        if "." not in Path(rel).name:
            index_file = pub_root / "index.html"
            if index_file.is_file():
                self._serve_file(index_file, support_range=False, cache_header="no-cache", emit_session_cookie=True)
                return

        self._send_error_json(404, "Static resource not found")

    # ---------- SSE ----------

    def _handle_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        q = self.server.broker.subscribe()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.write(b'event: hello\ndata: {"ok": true}\n\n')
            self.wfile.flush()
            while not self.server.shutdown_event.is_set():
                try:
                    evt, data = q.get(timeout=15.0)
                    if evt == "__shutdown__":
                        break
                    msg = f"event: {evt}\ndata: {data}\n\n".encode("utf-8")
                    self.wfile.write(msg)
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.server.broker.unsubscribe(q)

    # ---------- Route Dispatch ----------

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET, POST, PUT, PATCH, HEAD, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        try:
            if path == "/api/health":
                self._send_json({"ok": True, "version": VERSION, "port": self.server.bound_port})
                return
            if path == "/api/media":
                self._handle_media(qs)
                return
            if path == "/api/events":
                self._handle_sse()
                return
            if path == "/api/showcase":
                self._send_json(bridge.get_showcase())
                return
            if path == "/api/templates":
                self._send_json(bridge.get_templates())
                return
            if path == "/api/workflows/presets":
                self._send_json({"ok": True, "presets": wf_engine.list_workflow_presets()})
                return
            if path == "/api/session":
                sid = self._resolve_session()
                used_jobs = self.server.db.count_session_cloud_jobs(sid)
                used_projects = self.server.db.count_session_projects(sid)
                summary = self.server.coordinator.get_queue_summary(
                    owner_session=sid if self.server.guest_mode else None
                )
                self._send_json(
                    {
                        "ok": True,
                        "session_id": sid,
                        "mode": "guest" if self.server.guest_mode else "host",
                        "guest_mode": self.server.guest_mode,
                        "invite_required": bool(self.server.invite_code),
                        "farm_online": self.server.coordinator.is_farm_online(),
                        "used_cloud_jobs": used_jobs,
                        "max_guest_jobs": self.server.max_guest_jobs,
                        "remaining_cloud_jobs": max(0, self.server.max_guest_jobs - used_jobs),
                        "used_projects": used_projects,
                        "max_guest_projects": 6,
                        "max_guest_duration": self.server.max_guest_duration,
                        "active_queue": summary["active"],
                        "queue_jobs": summary["jobs"][:12],
                    }
                )
                return
            if path == "/api/queue":
                sid = self._resolve_session()
                active_only = (qs.get("active") or ["0"])[0] == "1"
                owner_filter = sid if self.server.guest_mode else None
                summary = self.server.coordinator.get_queue_summary(owner_session=owner_filter)
                jobs = self.server.db.list_cloud_queue(
                    owner_session=owner_filter,
                    active_only=active_only,
                    limit=50,
                )
                self._send_json(
                    {
                        "ok": True,
                        "farm_online": summary["farm_online"],
                        "active_count": summary["active_count"],
                        "jobs": jobs,
                    }
                )
                return
            m_qjob = re.fullmatch(r"/api/queue/([A-Za-z0-9_-]+)", path)
            if m_qjob:
                sid = self._resolve_session()
                qjob = self.server.db.get_cloud_job(m_qjob.group(1))
                if not qjob:
                    self._send_error_json(404, "Queue job not found")
                    return
                if self.server.guest_mode and (qjob.get("owner_session") or "") != sid:
                    self._send_error_json(403, "无权访问其他访客的队列任务")
                    return
                enriched = dict(qjob)
                enriched["queue_pos"] = self.server.db.get_queue_position(qjob["id"])
                enriched["farm_online"] = self.server.coordinator.is_farm_online()
                self._send_json({"ok": True, "job": enriched, **enriched})
                return
            if path == "/api/projects":
                sid = self._resolve_session()
                self._send_json(
                    {
                        "projects": bridge.list_projects(
                            self.server.db,
                            session_id=sid,
                            guest_mode=self.server.guest_mode,
                        )
                    }
                )
                return
            m_proj = re.fullmatch(r"/api/projects/([A-Za-z0-9_][A-Za-z0-9_-]*)", path)
            if m_proj:
                pid = m_proj.group(1)
                sid = self._resolve_session()
                if not self._require_project_read_access(pid, sid):
                    return
                scene = (qs.get("scene") or [None])[0]
                limit_raw = (qs.get("limit") or ["120"])[0]
                try:
                    limit = max(1, min(1000, int(limit_raw)))
                except ValueError:
                    limit = 120
                detail = bridge.get_project_detail(
                    self.server.db,
                    pid,
                    scene=scene,
                    limit=limit,
                    session_id=sid,
                    coordinator=self.server.coordinator,
                )
                if not detail:
                    self._send_error_json(404, f"Project not found: {pid}")
                    return
                self._send_json(detail)
                return
            m_wf = re.fullmatch(r"/api/projects/([A-Za-z0-9_][A-Za-z0-9_-]*)/workflow", path)
            if m_wf:
                pid = m_wf.group(1)
                sid = self._resolve_session()
                if not self._require_project_read_access(pid, sid):
                    return
                detail = bridge.get_project_detail(
                    self.server.db, pid, limit=60, session_id=sid, coordinator=self.server.coordinator
                )
                if not detail:
                    self._send_error_json(404, f"Project not found: {pid}")
                    return
                preset_id = (qs.get("preset") or [None])[0]
                wf = wf_engine.get_project_workflow(detail, preset_id=preset_id)
                self._send_json({"ok": True, "workflow": wf})
                return
            m_wf_exp = re.fullmatch(r"/api/projects/([A-Za-z0-9_][A-Za-z0-9_-]*)/workflow/export", path)
            if m_wf_exp:
                pid = m_wf_exp.group(1)
                sid = self._resolve_session()
                if not self._require_project_read_access(pid, sid):
                    return
                detail = bridge.get_project_detail(
                    self.server.db, pid, limit=60, session_id=sid, coordinator=self.server.coordinator
                )
                if not detail:
                    self._send_error_json(404, f"Project not found: {pid}")
                    return
                fmt = (qs.get("format") or ["comfyui"])[0].lower()
                wf = wf_engine.get_project_workflow(detail)
                payload_obj = wf["comfyui_api"] if fmt == "comfyui" else {k: v for k, v in wf.items() if k not in ("presets", "comfyui_api")}
                raw_bytes = (json.dumps(payload_obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                fname = f"{pid}_comfyui_workflow.json" if fmt == "comfyui" else f"{pid}_cineforge_workflow.json"
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                self.send_header("Content-Length", str(len(raw_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(raw_bytes)
                return
            if path == "/api/jobs":
                sid = self._resolve_session()
                pid = (qs.get("project_id") or [None])[0]
                if self.server.guest_mode and pid and not self._require_project_read_access(pid, sid):
                    return
                jobs = self.server.db.list_jobs(project_id=pid)
                if self.server.guest_mode:
                    jobs = [
                        j
                        for j in jobs
                        if not str(j.get("project_id") or "").startswith("studio_")
                        or (j.get("owner_session") or "") == sid
                    ]
                self._send_json({"jobs": jobs})
                return
            m_job = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)", path)
            if m_job:
                sid = self._resolve_session()
                job = self.server.db.get_job(m_job.group(1))
                if not job:
                    self._send_error_json(404, "Job not found")
                    return
                if (
                    self.server.guest_mode
                    and str(job.get("project_id") or "").startswith("studio_")
                    and (job.get("owner_session") or "") != sid
                ):
                    self._send_error_json(403, "无权访问其他访客的任务")
                    return
                self._send_json({"job": job, **job})
                return
            if path == "/api/farm/status":
                full_farm = bridge.get_farm_status(farm_port=self.server.farm_port)
                if self.server.guest_mode:
                    self._send_json(
                        {
                            "online": full_farm["online"],
                            "farm_online": full_farm["farm_online"],
                            "mode_label": "共享影棚算力在线" if full_farm["online"] else "共享影棚排队就绪",
                            "total_shots_rendered": full_farm["total_shots_rendered"],
                            "median_h3_sec": full_farm["median_h3_sec"],
                            "median_ltx_sec": full_farm["median_ltx_sec"],
                            "metrics": full_farm["metrics"],
                            "cost_comparison": full_farm["cost_comparison"],
                        }
                    )
                    return
                self._send_json(full_farm)
                return
            if path == "/api/farm/colab-notebook":
                if self.server.guest_mode:
                    self._send_error_json(403, "访客体验模式无需下载 Colab 节点脚本，算力已由主站托管")
                    return
                nb_bytes = json.dumps(
                    bridge.build_colab_worker_notebook(), ensure_ascii=False, indent=2
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ipynb+json")
                self.send_header(
                    "Content-Disposition", 'attachment; filename="CineForge_Colab_Worker.ipynb"'
                )
                self.send_header("Content-Length", str(len(nb_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(nb_bytes)
                return
            if path == "/api/share/info":
                info = bridge.get_share_info(
                    guest_mode=self.server.guest_mode,
                    invite_required=bool(self.server.invite_code),
                )
                if self.server.guest_mode:
                    info = {
                        "mode": "guest",
                        "invite_required": bool(self.server.invite_code),
                        "invite_copy_zh": info.get("invite_copy_zh", ""),
                    }
                self._send_json(info)
                return
            if path == "/api/evaluations":
                self._send_json(
                    {
                        "missions": bridge.get_beta_missions(),
                        "reviews": self.server.db.list_evaluations(),
                        "summary": self.server.db.get_evaluation_summary(),
                    }
                )
                return
            if path.startswith("/api/"):
                self._send_error_json(404, f"Unknown API endpoint: {path}")
                return
            self._handle_static(path)
        except Exception as exc:  # noqa: BLE001
            self._send_error_json(500, bridge.sanitize_text(str(exc))[:240])

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if not self._require_invite_for_write(qs):
            return

        try:
            sid = self._resolve_session()
            if path == "/api/projects":
                body = self._read_json_body()
                if self.server.guest_mode:
                    if self.server.db.count_session_projects(sid) >= 6:
                        self._send_error_json(
                            429,
                            "免费体验空间最多保留 6 个创作项目，请打开您已创建的项目继续编辑或等待渲染完成",
                        )
                        return
                    try:
                        dur = int(body.get("duration_sec") or 30)
                    except (TypeError, ValueError):
                        dur = 30
                    body["duration_sec"] = max(10, min(self.server.max_guest_duration, dur))
                body["owner_session"] = sid
                auto_dispatch = bool(body.get("auto_dispatch"))
                project = bridge.create_studio_project(self.server.db, body)
                project["is_mine"] = True
                self.server.broker.broadcast("project_created", {"project": project})
                resp_payload: dict[str, Any] = {"project": project}
                if auto_dispatch:
                    preview_res = bridge.start_render_preview_job(
                        self.server.db,
                        self.server.broker.broadcast,
                        project["id"],
                        owner_session=sid,
                    )
                    resp_payload["preview_job"] = preview_res
                    try:
                        cloud_res = bridge.dispatch_cloud_project(
                            self.server.db,
                            self.server.broker.broadcast,
                            project["id"],
                            coordinator=self.server.coordinator,
                            owner_session=sid,
                            guest_mode=self.server.guest_mode,
                            max_guest_jobs=self.server.max_guest_jobs,
                        )
                        if cloud_res and self.server.guest_mode:
                            cloud_res = dict(cloud_res)
                            cloud_res.pop("colab_snippet", None)
                    except PermissionError as exc:
                        cloud_res = {"ok": False, "quota_exceeded": True, "error": str(exc)}
                    resp_payload["cloud_dispatch"] = cloud_res
                    if isinstance(cloud_res, dict) and cloud_res.get("queue_job"):
                        resp_payload["cloud_job"] = cloud_res["queue_job"]
                self._send_json(resp_payload, status=201)
                return

            m_retake = re.fullmatch(
                r"/api/projects/([A-Za-z0-9_][A-Za-z0-9_-]*)/shots/([A-Za-z0-9_][A-Za-z0-9_-]*)/retake",
                path,
            )
            if m_retake:
                pid, shot_id = m_retake.groups()
                if not self._require_project_write_access(pid, sid):
                    return
                body = self._read_json_body()
                reason = str(body.get("reason") or "导演标记需重拍").strip()
                patch: dict[str, Any] = {
                    "status": "retake",
                    "retake_reason": reason,
                    "notes": f"[重拍原因] {reason}",
                }
                if body.get("prompt"):
                    patch["prompt"] = str(body["prompt"])
                res = bridge.patch_shot(self.server.db, pid, shot_id, patch)
                if not res:
                    self._send_error_json(404, "Project or shot not found")
                    return
                shot, proj_summary = res
                self.server.broker.broadcast(
                    "shot_updated", {"project_id": pid, "shot_id": shot_id, "shot": shot}
                )
                self._send_json({"shot": shot, "project_summary": proj_summary})
                return

            m_stage = re.fullmatch(r"/api/projects/([A-Za-z0-9_][A-Za-z0-9_-]*)/advance-stage", path)
            if m_stage:
                pid = m_stage.group(1)
                if not self._require_project_write_access(pid, sid):
                    return
                body = self._read_json_body()
                stage_key = str(body.get("stage") or "").strip()
                res = bridge.advance_stage(self.server.db, pid, stage_key)
                if not res:
                    self._send_error_json(404, "Project not found")
                    return
                self.server.broker.broadcast("stage_advanced", {"project_id": pid, "stage": stage_key})
                self._send_json(res)
                return

            m_preview = re.fullmatch(r"/api/projects/([A-Za-z0-9_][A-Za-z0-9_-]*)/render-preview", path)
            if m_preview:
                pid = m_preview.group(1)
                if not self._require_project_write_access(pid, sid):
                    return
                res = bridge.start_render_preview_job(
                    self.server.db,
                    self.server.broker.broadcast,
                    pid,
                    owner_session=sid,
                )
                if not res:
                    self._send_error_json(404, "Project not found")
                    return
                self._send_json(res)
                return

            m_dispatch = re.fullmatch(r"/api/projects/([A-Za-z0-9_][A-Za-z0-9_-]*)/dispatch-cloud", path)
            if m_dispatch:
                pid = m_dispatch.group(1)
                if not self._require_project_write_access(pid, sid):
                    return
                try:
                    res = bridge.dispatch_cloud_project(
                        self.server.db,
                        self.server.broker.broadcast,
                        pid,
                        coordinator=self.server.coordinator,
                        owner_session=sid,
                        guest_mode=self.server.guest_mode,
                        max_guest_jobs=self.server.max_guest_jobs,
                    )
                except PermissionError as exc:
                    self._send_error_json(429, str(exc))
                    return
                if not res:
                    self._send_error_json(404, "Project not found")
                    return
                if self.server.guest_mode:
                    res = dict(res)
                    res.pop("colab_snippet", None)
                self._send_json(res)
                return

            m_wf_save = re.fullmatch(r"/api/projects/([A-Za-z0-9_][A-Za-z0-9_-]*)/workflow", path)
            if m_wf_save:
                pid = m_wf_save.group(1)
                if not self._require_project_write_access(pid, sid):
                    return
                detail = bridge.get_project_detail(
                    self.server.db, pid, limit=60, session_id=sid, coordinator=self.server.coordinator
                )
                if not detail:
                    self._send_error_json(404, "Project not found")
                    return
                body = self._read_json_body()
                saved = wf_engine.save_project_workflow(pid, body, detail=detail)
                self.server.broker.broadcast("workflow_updated", {"project_id": pid, "engine": saved.get("engine")})
                self._send_json({"ok": True, "workflow": saved})
                return

            m_wf_imp = re.fullmatch(r"/api/projects/([A-Za-z0-9_][A-Za-z0-9_-]*)/workflow/import", path)
            if m_wf_imp:
                pid = m_wf_imp.group(1)
                if not self._require_project_write_access(pid, sid):
                    return
                detail = bridge.get_project_detail(
                    self.server.db, pid, limit=60, session_id=sid, coordinator=self.server.coordinator
                )
                if not detail:
                    self._send_error_json(404, "Project not found")
                    return
                body = self._read_json_body()
                raw_wf = body.get("workflow") if isinstance(body.get("workflow"), dict) else body
                imported = wf_engine.import_external_workflow(pid, raw_wf, detail=detail)
                self.server.broker.broadcast("workflow_updated", {"project_id": pid, "engine": imported.get("engine")})
                self._send_json({"ok": True, "workflow": imported})
                return

            m_wf_run = re.fullmatch(r"/api/projects/([A-Za-z0-9_][A-Za-z0-9_-]*)/workflow/run", path)
            if m_wf_run:
                pid = m_wf_run.group(1)
                if not self._require_project_write_access(pid, sid):
                    return
                detail = bridge.get_project_detail(
                    self.server.db, pid, limit=60, session_id=sid, coordinator=self.server.coordinator
                )
                if not detail:
                    self._send_error_json(404, "Project not found")
                    return
                body = self._read_json_body()
                if isinstance(body.get("nodes"), list) and body["nodes"]:
                    wf = wf_engine.save_project_workflow(pid, body, detail=detail)
                elif isinstance(body.get("workflow"), dict) and body["workflow"].get("nodes"):
                    wf = wf_engine.save_project_workflow(pid, body["workflow"], detail=detail)
                else:
                    wf = wf_engine.get_project_workflow(detail)
                ov = wf.get("runtime_overrides") or {}
                try:
                    res = bridge.dispatch_cloud_project(
                        self.server.db,
                        self.server.broker.broadcast,
                        pid,
                        coordinator=self.server.coordinator,
                        owner_session=sid,
                        guest_mode=self.server.guest_mode,
                        max_guest_jobs=self.server.max_guest_jobs,
                        engine_override=ov.get("engine"),
                    )
                except PermissionError as exc:
                    self._send_error_json(429, str(exc))
                    return
                if not res:
                    self._send_error_json(404, "Project not found")
                    return
                if self.server.guest_mode:
                    res = dict(res)
                    res.pop("colab_snippet", None)
                self._send_json({"ok": True, "workflow": wf, "cloud_dispatch": res, **res})
                return

            m_cancel = re.fullmatch(r"/api/queue/([A-Za-z0-9_-]+)/cancel", path)
            if m_cancel:
                qid = m_cancel.group(1)
                qjob = self.server.db.get_cloud_job(qid)
                if not qjob:
                    self._send_error_json(404, "Queue job not found")
                    return
                if self.server.guest_mode and (qjob.get("owner_session") or "") != sid:
                    self._send_error_json(403, "无权取消其他访客的队列任务")
                    return
                cancelled = self.server.coordinator.cancel(qid)
                self._send_json({"ok": True, "job": cancelled})
                return

            if path == "/api/uploads":
                ctype = (self.headers.get("Content-Type") or "").lower()
                if "application/json" in ctype:
                    body = self._read_json_body()
                    fname = str(body.get("filename") or "upload.png")
                    b64 = str(body.get("data_base64") or "")
                    raw = bridge.decode_base64_upload(b64)
                else:
                    fname = unquote((qs.get("filename") or [self.headers.get("X-Filename") or "upload.png"])[0])
                    raw = self._read_body_bytes()
                res = bridge.save_upload(fname, raw)
                self._send_json(res)
                return

            if path == "/api/evaluations":
                body = self._read_json_body()

                def _score(primary: str, alt: str) -> int:
                    val = body.get(primary, body.get(alt))
                    if val is None:
                        raise ValueError(f"缺少评分字段 {primary}")
                    ival = int(val)
                    if ival < 1 or ival > 5:
                        raise ValueError(f"评分 {primary} 必须在 1 到 5 之间")
                    return ival

                rec = {
                    "reviewer_name": str(body.get("reviewer_name") or "匿名体验官").strip()[:40] or "匿名体验官",
                    "role": str(body.get("role") or "白领体验官").strip()[:40] or "白领体验官",
                    "work_title": str(body.get("work_title") or "影铸 Studio 综合体验").strip()[:120],
                    "project_id": str(body.get("project_id") or "").strip()[:60],
                    "score_aesthetic": _score("score_aesthetic", "aesthetic"),
                    "score_consistency": _score("score_consistency", "consistency"),
                    "score_ease_of_use": _score("score_ease_of_use", "ease_of_use"),
                    "score_value": _score("score_value", "value"),
                    "would_share": bool(body.get("would_share", True)),
                    "comment": str(body.get("comment") or "").strip()[:1000],
                }
                review = self.server.db.add_evaluation(rec)
                summary = self.server.db.get_evaluation_summary()
                self.server.broker.broadcast("evaluation_added", {"review": review, "summary": summary})
                self._send_json({"review": review, "summary": summary}, status=201)
                return

            self._send_error_json(404, f"Unknown POST endpoint: {path}")
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._send_error_json(500, bridge.sanitize_text(str(exc))[:240])

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if not self._require_invite_for_write(qs):
            return
        try:
            sid = self._resolve_session()
            m_wf = re.fullmatch(r"/api/projects/([A-Za-z0-9_][A-Za-z0-9_-]*)/workflow", path)
            if m_wf:
                pid = m_wf.group(1)
                if not self._require_project_write_access(pid, sid):
                    return
                detail = bridge.get_project_detail(
                    self.server.db, pid, limit=60, session_id=sid, coordinator=self.server.coordinator
                )
                if not detail:
                    self._send_error_json(404, "Project not found")
                    return
                body = self._read_json_body()
                saved = wf_engine.save_project_workflow(pid, body, detail=detail)
                self.server.broker.broadcast("workflow_updated", {"project_id": pid, "engine": saved.get("engine")})
                self._send_json({"ok": True, "workflow": saved})
                return
            self._send_error_json(404, f"Unknown PUT endpoint: {path}")
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._send_error_json(500, bridge.sanitize_text(str(exc))[:240])

    def do_PATCH(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if not self._require_invite_for_write(qs):
            return

        try:
            sess_id = self._resolve_session()
            m_shot = re.fullmatch(
                r"/api/projects/([A-Za-z0-9_][A-Za-z0-9_-]*)/shots/([A-Za-z0-9_][A-Za-z0-9_-]*)",
                path,
            )
            if m_shot:
                pid, sid = m_shot.groups()
                if not self._require_project_write_access(pid, sess_id):
                    return
                body = self._read_json_body()
                res = bridge.patch_shot(self.server.db, pid, sid, body)
                if not res:
                    self._send_error_json(404, "Project or shot not found")
                    return
                shot, proj_summary = res
                self.server.broker.broadcast(
                    "shot_updated", {"project_id": pid, "shot_id": sid, "shot": shot}
                )
                self._send_json({"shot": shot, "project_summary": proj_summary})
                return

            self._send_error_json(404, f"Unknown PATCH endpoint: {path}")
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._send_error_json(500, bridge.sanitize_text(str(exc))[:240])


def run_server(
    host: str = "127.0.0.1",
    port: int = 8866,
    *,
    guest_mode: bool = False,
    invite_code: str | None = None,
    farm_port: int | None = None,
    max_guest_jobs: int | None = None,
    max_guest_duration: int | None = None,
) -> None:
    if port == 8765:
        raise ValueError("Port 8765 is reserved for tools/film/farm_server.py")
    resolved_farm_port = int(farm_port if farm_port is not None else os.environ.get("STUDIO_FARM_PORT", "8765"))
    if resolved_farm_port == port and port != 0:
        raise ValueError("Studio port and farm_port cannot be identical")
    resolved_max_jobs = int(
        max_guest_jobs if max_guest_jobs is not None else os.environ.get("STUDIO_MAX_GUEST_JOBS", "3")
    )
    resolved_max_dur = int(
        max_guest_duration if max_guest_duration is not None else os.environ.get("STUDIO_MAX_GUEST_DURATION", "30")
    )
    ensure_data_dirs()
    db = StudioDB()
    httpd = StudioHTTPServer(
        (host, port),
        StudioHandler,
        db=db,
        guest_mode=guest_mode,
        invite_code=invite_code,
        farm_port=resolved_farm_port,
        max_guest_jobs=resolved_max_jobs,
        max_guest_duration=resolved_max_dur,
    )

    def _stop(signum: int, _frame: Any) -> None:
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    mode_str = "guest" if guest_mode else "host"
    invite_str = "invite-protected" if httpd.invite_code else "open"
    print(
        f"[CineForge Studio] v{VERSION} ({mode_str}, {invite_str}, farm=:{resolved_farm_port}) listening on http://{host}:{httpd.bound_port}",
        flush=True,
    )
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
        db.close()
        print("[CineForge Studio] stopped cleanly.", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="CineForge Studio visual workflow server")
    ap.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8866, help="Bind port (default: 8866, never 8765)")
    ap.add_argument(
        "--guest-mode",
        "--guest",
        dest="guest_mode",
        action="store_true",
        help="Run in external zero-install guest experience mode",
    )
    ap.add_argument(
        "--invite-code",
        default=None,
        help="Optional invite code required for write endpoints only (default: none / zero-friction)",
    )
    ap.add_argument(
        "--farm-port",
        type=int,
        default=None,
        help="Farm server port for shared compute coordination (default: $STUDIO_FARM_PORT or 8765)",
    )
    ap.add_argument(
        "--max-guest-jobs",
        type=int,
        default=None,
        help="Max cloud generation jobs per guest session (default: $STUDIO_MAX_GUEST_JOBS or 3)",
    )
    ap.add_argument(
        "--max-guest-duration",
        type=int,
        default=None,
        help="Max video duration seconds allowed per guest project (default: $STUDIO_MAX_GUEST_DURATION or 30)",
    )
    args = ap.parse_args()
    run_server(
        host=args.host,
        port=args.port,
        guest_mode=args.guest_mode,
        invite_code=args.invite_code,
        farm_port=args.farm_port,
        max_guest_jobs=args.max_guest_jobs,
        max_guest_duration=args.max_guest_duration,
    )


if __name__ == "__main__":
    main()
