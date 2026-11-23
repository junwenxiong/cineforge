"""SQLite persistence layer for CineForge Studio (stdlib sqlite3 only)."""

from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from . import DB_PATH, ensure_data_dirs


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


SAMPLE_EVALUATIONS = [
    {
        "reviewer_name": "林小满",
        "role": "产品运营 · 示例体验官",
        "work_title": "猫咪四大名著 · 三国演义「俺也一样」",
        "project_id": "classics",
        "score_aesthetic": 5,
        "score_consistency": 5,
        "score_ease_of_use": 5,
        "score_value": 5,
        "would_share": 1,
        "comment": "原片和猫咪对照播放太上头了！口型和张飞的胡须细节都对得上，我们部门午休看了三遍，做成团建开场视频肯定炸场。",
        "is_sample": 1,
    },
    {
        "reviewer_name": "周明宇",
        "role": "市场策划 · 示例体验官",
        "work_title": "星核黎明 · 33分钟科幻长片",
        "project_id": "starcore",
        "score_aesthetic": 5,
        "score_consistency": 4,
        "score_ease_of_use": 4,
        "score_value": 5,
        "would_share": 1,
        "comment": "以前以为 AI 拍片要写一堆参数，这个 6 步工作流看板像 Notion 一样清楚，单镜算下来才两毛钱，做方案提案的 15 秒预演片特别省钱省时间。",
        "is_sample": 1,
    },
]

ACTIVE_CLOUD_STATUSES = ("queued", "staging", "rendering", "assembling")


class StudioDB:
    """Thread-safe SQLite store for Studio projects, overlays, jobs, cloud queue, and evaluations."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        ensure_data_dirs()
        env_db = os.environ.get("STUDIO_DB_PATH")
        self.db_path = Path(db_path) if db_path else (Path(env_db) if env_db else DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                try:
                    self._conn.execute("PRAGMA journal_mode=DELETE")
                except sqlite3.Error:
                    pass
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._init_schema()

    def _ensure_column(self, table: str, col: str, col_def: str) -> None:
        cols = {r["name"] for r in self._conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
        if col not in cols:
            self._conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {col} {col_def}')

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                title_en TEXT NOT NULL DEFAULT '',
                idea TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL DEFAULT 'original',
                genre TEXT NOT NULL DEFAULT '',
                style_id TEXT NOT NULL DEFAULT '',
                style_name TEXT NOT NULL DEFAULT '',
                duration_sec INTEGER NOT NULL DEFAULT 30,
                aspect TEXT NOT NULL DEFAULT '16:9',
                character_name TEXT NOT NULL DEFAULT '',
                creator_name TEXT NOT NULL DEFAULT '匿名创作者',
                owner_session TEXT NOT NULL DEFAULT '',
                ref_images_json TEXT NOT NULL DEFAULT '[]',
                source_video_url TEXT,
                v2v_options_json TEXT NOT NULL DEFAULT '{}',
                stage_index INTEGER NOT NULL DEFAULT 2,
                stages_state_json TEXT NOT NULL DEFAULT '{}',
                poster_url TEXT NOT NULL DEFAULT '',
                preview_video_url TEXT,
                final_video_url TEXT,
                side_by_side_url TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_stage_overrides (
                project_id TEXT PRIMARY KEY,
                stage_index INTEGER,
                stages_state_json TEXT NOT NULL DEFAULT '{}',
                preview_video_url TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS shot_overlays (
                project_id TEXT NOT NULL,
                shot_id TEXT NOT NULL,
                status TEXT,
                summary_zh TEXT,
                prompt TEXT,
                dialogue_json TEXT,
                cut_in REAL,
                cut_out REAL,
                notes TEXT,
                retake_reason TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (project_id, shot_id)
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                output_url TEXT,
                output_path TEXT,
                meta_json TEXT NOT NULL DEFAULT '{}',
                owner_session TEXT NOT NULL DEFAULT '',
                queue_pos INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cloud_queue (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                owner_session TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                stage_label TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                total_shots INTEGER NOT NULL DEFAULT 0,
                done_shots INTEGER NOT NULL DEFAULT 0,
                failed_shots INTEGER NOT NULL DEFAULT 0,
                output_url TEXT,
                side_by_side_url TEXT,
                manifest_path TEXT,
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reviewer_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '白领体验官',
                work_title TEXT NOT NULL DEFAULT '',
                project_id TEXT NOT NULL DEFAULT '',
                score_aesthetic INTEGER NOT NULL,
                score_consistency INTEGER NOT NULL,
                score_ease_of_use INTEGER NOT NULL,
                score_value INTEGER NOT NULL,
                would_share INTEGER NOT NULL DEFAULT 1,
                comment TEXT NOT NULL DEFAULT '',
                is_sample INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        # Idempotent migrations for existing studio.db files
        self._ensure_column("projects", "owner_session", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("projects", "side_by_side_url", "TEXT")
        self._ensure_column("jobs", "owner_session", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("jobs", "queue_pos", "INTEGER NOT NULL DEFAULT 0")

        cur = self._conn.execute("SELECT COUNT(*) AS c FROM evaluations")
        if cur.fetchone()["c"] == 0:
            now = utc_now_iso()
            for row in SAMPLE_EVALUATIONS:
                self._conn.execute(
                    """
                    INSERT INTO evaluations (
                        reviewer_name, role, work_title, project_id,
                        score_aesthetic, score_consistency, score_ease_of_use, score_value,
                        would_share, comment, is_sample, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["reviewer_name"],
                        row["role"],
                        row["work_title"],
                        row["project_id"],
                        row["score_aesthetic"],
                        row["score_consistency"],
                        row["score_ease_of_use"],
                        row["score_value"],
                        row["would_share"],
                        row["comment"],
                        row["is_sample"],
                        now,
                    ),
                )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------- Studio projects ----------
    def _row_to_project(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["ref_images"] = json.loads(d.pop("ref_images_json", "[]") or "[]")
        d["v2v_options"] = json.loads(d.pop("v2v_options_json", "{}") or "{}")
        d["stages_state"] = json.loads(d.pop("stages_state_json", "{}") or "{}")
        d.setdefault("owner_session", "")
        d.setdefault("side_by_side_url", None)
        return d

    def list_studio_projects(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
            return [self._row_to_project(r) for r in rows]

    def count_session_projects(self, owner_session: str) -> int:
        if not owner_session:
            return 0
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM projects WHERE owner_session = ?",
                (owner_session,),
            ).fetchone()
            return int(row["c"] or 0) if row else 0

    def get_studio_project(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            return self._row_to_project(row) if row else None

    def create_studio_project(self, rec: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO projects (
                    id, title, title_en, idea, mode, genre, style_id, style_name,
                    duration_sec, aspect, character_name, creator_name, owner_session,
                    ref_images_json, source_video_url, v2v_options_json,
                    stage_index, stages_state_json, poster_url, preview_video_url,
                    final_video_url, side_by_side_url, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec["id"],
                    rec["title"],
                    rec.get("title_en", ""),
                    rec.get("idea", ""),
                    rec.get("mode", "original"),
                    rec.get("genre", ""),
                    rec.get("style_id", ""),
                    rec.get("style_name", ""),
                    int(rec.get("duration_sec", 30)),
                    rec.get("aspect", "16:9"),
                    rec.get("character_name", ""),
                    rec.get("creator_name", "匿名创作者"),
                    rec.get("owner_session", ""),
                    json.dumps(rec.get("ref_images", []), ensure_ascii=False),
                    rec.get("source_video_url"),
                    json.dumps(rec.get("v2v_options", {}), ensure_ascii=False),
                    int(rec.get("stage_index", 2)),
                    json.dumps(rec.get("stages_state", {}), ensure_ascii=False),
                    rec.get("poster_url", ""),
                    rec.get("preview_video_url"),
                    rec.get("final_video_url"),
                    rec.get("side_by_side_url"),
                    now,
                    now,
                ),
            )
            self._conn.commit()
            return self.get_studio_project(rec["id"])  # type: ignore[return-value]

    def update_studio_project(self, project_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "title",
            "title_en",
            "idea",
            "genre",
            "style_id",
            "style_name",
            "duration_sec",
            "aspect",
            "character_name",
            "owner_session",
            "stage_index",
            "poster_url",
            "preview_video_url",
            "final_video_url",
            "side_by_side_url",
        }
        cols: list[str] = []
        vals: list[Any] = []
        for k, v in fields.items():
            if k == "stages_state":
                cols.append("stages_state_json = ?")
                vals.append(json.dumps(v, ensure_ascii=False))
            elif k == "ref_images":
                cols.append("ref_images_json = ?")
                vals.append(json.dumps(v, ensure_ascii=False))
            elif k in allowed:
                cols.append(f"{k} = ?")
                vals.append(v)
        if not cols:
            return self.get_studio_project(project_id)
        cols.append("updated_at = ?")
        vals.append(utc_now_iso())
        vals.append(project_id)
        with self._lock:
            self._conn.execute(f"UPDATE projects SET {', '.join(cols)} WHERE id = ?", vals)
            self._conn.commit()
            return self.get_studio_project(project_id)

    # ---------- Project stage & preview overrides ----------
    def get_stage_override(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM project_stage_overrides WHERE project_id = ?", (project_id,)
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["stages_state"] = json.loads(d.pop("stages_state_json", "{}") or "{}")
            return d

    def upsert_stage_override(
        self,
        project_id: str,
        *,
        stage_index: int | None = None,
        stages_state: dict[str, Any] | None = None,
        preview_video_url: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self._lock:
            existing = self.get_stage_override(project_id) or {}
            merged_index = stage_index if stage_index is not None else existing.get("stage_index")
            merged_state = dict(existing.get("stages_state") or {})
            if stages_state:
                merged_state.update(stages_state)
            merged_preview = (
                preview_video_url if preview_video_url is not None else existing.get("preview_video_url")
            )
            self._conn.execute(
                """
                INSERT INTO project_stage_overrides (
                    project_id, stage_index, stages_state_json, preview_video_url, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    stage_index = excluded.stage_index,
                    stages_state_json = excluded.stages_state_json,
                    preview_video_url = excluded.preview_video_url,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    merged_index,
                    json.dumps(merged_state, ensure_ascii=False),
                    merged_preview,
                    now,
                ),
            )
            self._conn.commit()
            return self.get_stage_override(project_id)  # type: ignore[return-value]

    # ---------- Shot overlays ----------
    def _row_to_overlay(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        raw_dlg = d.pop("dialogue_json", None)
        d["dialogue"] = json.loads(raw_dlg) if raw_dlg is not None else None
        return d

    def get_shot_overlays(self, project_id: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM shot_overlays WHERE project_id = ?", (project_id,)
            ).fetchall()
            return {r["shot_id"]: self._row_to_overlay(r) for r in rows}

    def get_shot_overlay(self, project_id: str, shot_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM shot_overlays WHERE project_id = ? AND shot_id = ?",
                (project_id, shot_id),
            ).fetchone()
            return self._row_to_overlay(row) if row else None

    def upsert_shot_overlay(
        self, project_id: str, shot_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self._lock:
            existing = self.get_shot_overlay(project_id, shot_id) or {}
            status = fields["status"] if "status" in fields else existing.get("status")
            summary_zh = fields["summary_zh"] if "summary_zh" in fields else existing.get("summary_zh")
            prompt = fields["prompt"] if "prompt" in fields else existing.get("prompt")
            dialogue = fields["dialogue"] if "dialogue" in fields else existing.get("dialogue")
            cut_in = fields["cut_in"] if "cut_in" in fields else existing.get("cut_in")
            cut_out = fields["cut_out"] if "cut_out" in fields else existing.get("cut_out")
            notes = fields["notes"] if "notes" in fields else existing.get("notes")
            retake_reason = (
                fields["retake_reason"] if "retake_reason" in fields else existing.get("retake_reason")
            )
            dialogue_json = json.dumps(dialogue, ensure_ascii=False) if dialogue is not None else None
            self._conn.execute(
                """
                INSERT INTO shot_overlays (
                    project_id, shot_id, status, summary_zh, prompt, dialogue_json,
                    cut_in, cut_out, notes, retake_reason, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, shot_id) DO UPDATE SET
                    status = excluded.status,
                    summary_zh = excluded.summary_zh,
                    prompt = excluded.prompt,
                    dialogue_json = excluded.dialogue_json,
                    cut_in = excluded.cut_in,
                    cut_out = excluded.cut_out,
                    notes = excluded.notes,
                    retake_reason = excluded.retake_reason,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    shot_id,
                    status,
                    summary_zh,
                    prompt,
                    dialogue_json,
                    cut_in,
                    cut_out,
                    notes,
                    retake_reason,
                    now,
                ),
            )
            self._conn.commit()
            return self.get_shot_overlay(project_id, shot_id)  # type: ignore[return-value]

    # ---------- Jobs ----------
    def _row_to_job(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["meta"] = json.loads(d.pop("meta_json", "{}") or "{}")
        d.setdefault("owner_session", "")
        d.setdefault("queue_pos", 0)
        return d

    def create_job(
        self,
        job_id: str,
        project_id: str,
        kind: str,
        *,
        status: str = "running",
        progress: int = 0,
        message: str = "",
        output_url: str | None = None,
        output_path: str | None = None,
        meta: dict[str, Any] | None = None,
        owner_session: str = "",
        queue_pos: int = 0,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jobs (
                    id, project_id, kind, status, progress, message,
                    output_url, output_path, meta_json, owner_session, queue_pos,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    project_id,
                    kind,
                    status,
                    int(progress),
                    message,
                    output_url,
                    output_path,
                    json.dumps(meta or {}, ensure_ascii=False),
                    owner_session,
                    int(queue_pos),
                    now,
                    now,
                ),
            )
            self._conn.commit()
            return self.get_job(job_id)  # type: ignore[return-value]

    def update_job(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"status", "progress", "message", "output_url", "output_path", "queue_pos"}
        cols: list[str] = []
        vals: list[Any] = []
        for k, v in fields.items():
            if k == "meta":
                cols.append("meta_json = ?")
                vals.append(json.dumps(v, ensure_ascii=False))
            elif k in allowed:
                cols.append(f"{k} = ?")
                vals.append(v)
        if not cols:
            return self.get_job(job_id)
        cols.append("updated_at = ?")
        vals.append(utc_now_iso())
        vals.append(job_id)
        with self._lock:
            self._conn.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE id = ?", vals)
            self._conn.commit()
            return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return self._row_to_job(row) if row else None

    def get_active_preview_job(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM jobs
                WHERE project_id = ? AND kind = 'render_preview' AND status IN ('queued', 'running')
                ORDER BY created_at DESC LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            return self._row_to_job(row) if row else None

    def list_jobs(self, project_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            if project_id:
                rows = self._conn.execute(
                    "SELECT * FROM jobs WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                    (project_id, int(limit)),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (int(limit),)
                ).fetchall()
            return [self._row_to_job(r) for r in rows]

    # ---------- Shared Cloud Queue ----------
    def _row_to_cloud_job(self, row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def enqueue_cloud_job(self, rec: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO cloud_queue (
                    id, project_id, owner_session, mode, status, progress,
                    stage_label, message, total_shots, done_shots, failed_shots,
                    output_url, side_by_side_url, manifest_path, error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec["id"],
                    rec["project_id"],
                    rec.get("owner_session", ""),
                    rec.get("mode", "original"),
                    rec.get("status", "queued"),
                    int(rec.get("progress", 0)),
                    rec.get("stage_label", "已加入云端影棚队列"),
                    rec.get("message", "正在排队等待云端显卡开拍..."),
                    int(rec.get("total_shots", 0)),
                    int(rec.get("done_shots", 0)),
                    int(rec.get("failed_shots", 0)),
                    rec.get("output_url"),
                    rec.get("side_by_side_url"),
                    rec.get("manifest_path"),
                    rec.get("error", ""),
                    now,
                    now,
                ),
            )
            self._conn.commit()
            return self.get_cloud_job(rec["id"])  # type: ignore[return-value]

    def get_cloud_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM cloud_queue WHERE id = ?", (job_id,)).fetchone()
            return self._row_to_cloud_job(row) if row else None

    def get_latest_cloud_job_for_project(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM cloud_queue WHERE project_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            return self._row_to_cloud_job(row) if row else None

    def get_active_cloud_job_for_project(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM cloud_queue
                WHERE project_id = ? AND status IN ('queued', 'staging', 'rendering', 'assembling')
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            return self._row_to_cloud_job(row) if row else None

    def list_cloud_queue(
        self,
        *,
        owner_session: str | None = None,
        active_only: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if owner_session is not None:
            clauses.append("owner_session = ?")
            params.append(owner_session)
        if active_only:
            clauses.append("status IN ('queued', 'staging', 'rendering', 'assembling')")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "ORDER BY created_at ASC, rowid ASC" if active_only else "ORDER BY created_at DESC, rowid DESC"
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM cloud_queue {where} {order} LIMIT ?",
                params,
            ).fetchall()
            return [self._row_to_cloud_job(r) for r in rows]

    def update_cloud_job(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "status",
            "progress",
            "stage_label",
            "message",
            "total_shots",
            "done_shots",
            "failed_shots",
            "output_url",
            "side_by_side_url",
            "manifest_path",
            "error",
        }
        cols: list[str] = []
        vals: list[Any] = []
        for k, v in fields.items():
            if k in allowed:
                cols.append(f"{k} = ?")
                vals.append(v)
        if not cols:
            return self.get_cloud_job(job_id)
        cols.append("updated_at = ?")
        vals.append(utc_now_iso())
        vals.append(job_id)
        with self._lock:
            self._conn.execute(f"UPDATE cloud_queue SET {', '.join(cols)} WHERE id = ?", vals)
            self._conn.commit()
            return self.get_cloud_job(job_id)

    def cancel_cloud_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            existing = self.get_cloud_job(job_id)
            if not existing:
                return None
            if existing["status"] not in ACTIVE_CLOUD_STATUSES:
                return existing
            return self.update_cloud_job(
                job_id,
                status="canceled",
                stage_label="已取消排队",
                message="已取消该云端拍摄任务",
            )

    def count_session_cloud_jobs(self, owner_session: str) -> int:
        if not owner_session:
            return 0
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM cloud_queue WHERE owner_session = ? AND status != 'canceled'",
                (owner_session,),
            ).fetchone()
            return int(row["c"] or 0) if row else 0

    def get_queue_position(self, job_id: str) -> int:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id FROM cloud_queue
                WHERE status IN ('queued', 'staging', 'rendering', 'assembling')
                ORDER BY created_at ASC, rowid ASC
                """
            ).fetchall()
            for idx, r in enumerate(rows, start=1):
                if r["id"] == job_id:
                    return idx
            return 0

    # ---------- Evaluations ----------
    def _row_to_eval(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["would_share"] = bool(d["would_share"])
        d["is_sample"] = bool(d["is_sample"])
        d["aesthetic"] = d["score_aesthetic"]
        d["consistency"] = d["score_consistency"]
        d["ease_of_use"] = d["score_ease_of_use"]
        d["value"] = d["score_value"]
        avg = round(
            (
                d["score_aesthetic"]
                + d["score_consistency"]
                + d["score_ease_of_use"]
                + d["score_value"]
            )
            / 4.0,
            2,
        )
        d["avg_score"] = avg
        d["overall"] = avg
        return d

    def list_evaluations(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM evaluations ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
            return [self._row_to_eval(r) for r in rows]

    def add_evaluation(self, rec: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO evaluations (
                    reviewer_name, role, work_title, project_id,
                    score_aesthetic, score_consistency, score_ease_of_use, score_value,
                    would_share, comment, is_sample, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    rec["reviewer_name"],
                    rec["role"],
                    rec["work_title"],
                    rec["project_id"],
                    int(rec["score_aesthetic"]),
                    int(rec["score_consistency"]),
                    int(rec["score_ease_of_use"]),
                    int(rec["score_value"]),
                    1 if rec.get("would_share", True) else 0,
                    rec.get("comment", ""),
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM evaluations WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return self._row_to_eval(row)

    def get_evaluation_summary(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS count,
                    COALESCE(AVG(score_aesthetic), 0) AS avg_aesthetic,
                    COALESCE(AVG(score_consistency), 0) AS avg_consistency,
                    COALESCE(AVG(score_ease_of_use), 0) AS avg_ease_of_use,
                    COALESCE(AVG(score_value), 0) AS avg_value,
                    COALESCE(AVG(would_share), 0) AS share_ratio
                FROM evaluations
                """
            ).fetchone()
            cnt = int(row["count"] or 0)
            a = round(float(row["avg_aesthetic"] or 0), 2)
            c = round(float(row["avg_consistency"] or 0), 2)
            e = round(float(row["avg_ease_of_use"] or 0), 2)
            v = round(float(row["avg_value"] or 0), 2)
            overall = round((a + c + e + v) / 4.0, 2) if cnt else 0.0
            rec_rate = round(float(row["share_ratio"] or 0) * 100.0, 1) if cnt else 0.0
            return {
                "count": cnt,
                "avg_aesthetic": a,
                "avg_consistency": c,
                "avg_ease_of_use": e,
                "avg_value": v,
                "avg_overall": overall,
                "recommend_rate": rec_rate,
            }
