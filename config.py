import json
import os
import shutil
import sys
from pathlib import Path

# Base project directory
BASE_DIR = Path(__file__).resolve().parent
BIN_DIR = BASE_DIR / "bin"
CONFIG_FILE = BASE_DIR / "config.json"

DEFAULT_CONFIG = {
    "download_dir": "downloads",
    "default_quality": "best",
    "max_resolution": "1080",
    "concurrent_fragments": 4,
    "retries": 20,
    "fragment_retries": 50,
    "socket_timeout": 30,
    "min_free_space_gb": float(os.environ.get("MIN_FREE_SPACE_GB", 0.05)),
    "embed_thumbnail": False,
    "embed_subtitles": False,
    "embed_chapters": True,
    "use_archive": False,
    "archive_file": "downloads_archive.txt",
    "history_csv": "queue_history.csv",
    "queue_file": "queue.txt",
    "watcher_interval_seconds": 10,
    "rate_limit_bytes": 0
}


def load_config() -> dict:
    """Loads configuration from config.json with fallback to defaults."""
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
                cfg.update(user_cfg)
        except Exception as e:
            print(f"[Aviso] Falha ao ler config.json ({e}). Usando configurações padrão.")
    return cfg


def resolve_binary(binary_name: str) -> str:
    """
    Finds binary (e.g. yt-dlp.exe or ffmpeg.exe) in project bin/ folder first,
    then falls back to system PATH.
    """
    ext = ".exe" if sys.platform.startswith("win") else ""
    target_name = f"{binary_name}{ext}" if not binary_name.endswith(ext) else binary_name

    # 1. Check project's bin directory
    local_bin = BIN_DIR / target_name
    if local_bin.exists():
        return str(local_bin)

    # 2. Check system PATH
    system_path = shutil.which(binary_name)
    if system_path:
        return system_path

    # Fallback to local path even if not yet found
    return str(local_bin)


def get_ffmpeg_dir():
    """Returns directory containing ffmpeg if available, or None for system PATH."""
    system_path = shutil.which("ffmpeg")
    if system_path:
        return os.path.dirname(system_path)

    ffmpeg_exe = resolve_binary("ffmpeg")
    if os.path.exists(ffmpeg_exe):
        return os.path.dirname(ffmpeg_exe)

    return None


def get_free_disk_space_gb(path: Path) -> float:
    """Returns free disk space in Gigabytes for the specified path."""
    try:
        total, used, free = shutil.disk_usage(path if path.exists() else path.parent)
        return free / (1024 ** 3)
    except Exception:
        return 999.0
