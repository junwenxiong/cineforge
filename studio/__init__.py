"""CineForge Studio (影铸 AI 视频可视化工作流看板平台) backend package."""

from pathlib import Path

VERSION = "1.0.0"
STUDIO_DIR = Path(__file__).resolve().parent
ROOT = STUDIO_DIR.parent
DATA_DIR = STUDIO_DIR / "data"
PUBLIC_DIR = STUDIO_DIR / "public"
UPLOADS_DIR = DATA_DIR / "uploads"
PREVIEWS_DIR = DATA_DIR / "previews"
THUMBS_DIR = DATA_DIR / "thumbs"
DISPATCH_DIR = DATA_DIR / "dispatch"
DB_PATH = DATA_DIR / "studio.db"


def ensure_data_dirs() -> None:
    """Create runtime data directories safely."""
    for d in (DATA_DIR, UPLOADS_DIR, PREVIEWS_DIR, THUMBS_DIR, DISPATCH_DIR):
        d.mkdir(parents=True, exist_ok=True)
