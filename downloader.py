import os
import sys
import time
from pathlib import Path
from typing import Optional, Callable, Dict, Any

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
except ImportError:
    class DummyColor:
        def __getattr__(self, name):
            return ""
    Fore = DummyColor()
    Style = DummyColor()

from config import load_config, resolve_binary, get_ffmpeg_dir, get_free_disk_space_gb, BASE_DIR


def format_bytes(bytes_val: Optional[float]) -> str:
    """Formats bytes into human readable string (MB/GB)."""
    if not bytes_val or bytes_val <= 0:
        return "0.00 MB"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:3.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} PB"


def format_seconds(seconds: Optional[float]) -> str:
    """Converts seconds into HH:MM:SS format."""
    if seconds is None or seconds < 0:
        return "--:--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}h {m:02d}m {s:02d}s"
    return f"{m:02d}m {s:02d}s"


def safe_print(msg: Any):
    """Safely prints text to stdout handling any charset encoding limitations."""
    try:
        print(msg)
    except Exception:
        try:
            encoding = getattr(sys.stdout, "encoding", None) or "ascii"
            clean_msg = str(msg).encode(encoding, errors="replace").decode(encoding)
            print(clean_msg)
        except Exception:
            pass


def get_cookie_file() -> Optional[str]:
    """Resolves and loads cookies from Render Secret Files, local path, or env."""
    # 1. Render Secret Files mount path
    render_secret = Path("/etc/secrets/cookies.txt")
    if render_secret.exists() and render_secret.stat().st_size > 0:
        return str(render_secret)

    # 2. Local cookies.txt file
    cookie_path = BASE_DIR / "cookies.txt"
    env_cookies = os.environ.get("YOUTUBE_COOKIES", "").strip()
    if env_cookies:
        try:
            formatted = env_cookies.replace("\\n", "\n").replace("\\t", "\t")
            cookie_path.write_text(formatted, encoding="utf-8")
        except Exception:
            pass

    if cookie_path.exists() and cookie_path.stat().st_size > 0:
        return str(cookie_path)

    # 3. Docker /app/cookies.txt
    app_cookie = Path("/app/cookies.txt")
    if app_cookie.exists() and app_cookie.stat().st_size > 0:
        return str(app_cookie)

    return None


class LongVideoDownloader:
    """
    Downloader engine optimized for long videos (1h to 10h+).
    Features:
      - Fragment retry & multi-fragment concurrent downloading
      - Resume on broken connection
      - Pre-download disk space guard
      - Audio + Video auto-merging with bundled FFmpeg
      - Progress and ETA telemetry
    """

    def __init__(self, custom_config: Optional[Dict[str, Any]] = None):
        self.config = load_config()
        if custom_config:
            self.config.update(custom_config)

        self.download_dir = BASE_DIR / self.config.get("download_dir", "downloads")
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self.ffmpeg_dir = get_ffmpeg_dir()
        self.archive_path = BASE_DIR / self.config.get("archive_file", "downloads_archive.txt")

    def _progress_hook(self, d: Dict[str, Any]):
        """Custom console progress reporter for downloads."""
        status = d.get('status')
        if status == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            percent_str = f"{(downloaded / total * 100):.1f}%" if total > 0 else "N/A"
            speed = format_bytes(d.get('speed', 0)) + "/s"
            eta = format_seconds(d.get('eta'))
            downloaded_str = format_bytes(downloaded)
            total_str = format_bytes(total) if total > 0 else "Calculando..."

            # Real-time single line update
            sys.stdout.write(
                f"\r{Fore.CYAN}[Baixando]{Style.RESET_ALL} "
                f"{percent_str} | {downloaded_str} de {total_str} | "
                f"{Fore.GREEN}{speed}{Style.RESET_ALL} | "
                f"ETA: {Fore.YELLOW}{eta}{Style.RESET_ALL}     "
            )
            sys.stdout.flush()

        elif status == 'finished':
            try:
                sys.stdout.write("\n")
                sys.stdout.flush()
            except Exception:
                pass
            safe_print(f"{Fore.GREEN}[OK] Download do fluxo concluido. Processando/Mesclando com FFmpeg...{Style.RESET_ALL}")

    def get_video_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Extracts metadata without downloading."""
        if not yt_dlp:
            raise RuntimeError("Modulo yt-dlp nao esta disponivel no ambiente.")

        cookie_file = get_cookie_file()

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'skip_download': True,
            'nocheckcertificate': True,
            'geo_bypass': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios'],
                    'player_skip': ['webpage', 'configs'],
                }
            }
        }
        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                return info
            except Exception as e:
                safe_print(f"{Fore.YELLOW}Aviso ao obter metadados: {e}{Style.RESET_ALL}")
                return None

    def build_ydl_options(self, mode: str = "best", custom_resolution: Optional[str] = None) -> Dict[str, Any]:
        """
        Builds optimized yt-dlp parameters tailored for downloading long videos.
        """
        max_res = custom_resolution or self.config.get("max_resolution", "1080")
        output_template = str(self.download_dir / "%(uploader)s - %(title)s [%(id)s].%(ext)s")

        cookie_file = get_cookie_file()

        ydl_opts = {
            'outtmpl': output_template,
            'progress_hooks': [self._progress_hook],
            'nocheckcertificate': True,
            'geo_bypass': True,
            'overwrites': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios'],
                    'player_skip': ['webpage', 'configs'],
                }
            },

            # Resilience settings for long video streams:
            'continuedl': True,              # Resume partially downloaded files
            'retries': self.config.get("retries", 20),
            'fragment_retries': self.config.get("fragment_retries", 50),
            'skip_unavailable_fragments': False,
            'keep_fragments': False,
            'concurrent_fragment_downloads': self.config.get("concurrent_fragments", 4),
            'socket_timeout': self.config.get("socket_timeout", 30),
            'buffersize': 1024 * 64,
            'http_chunk_size': 10485760,     # 10MB chunk size
            'part': True,                     # Download to .part file first
            'noprogress': True,               # Use our clean custom progress hook
            'quiet': True,
            'no_warnings': True,
        }

        if self.config.get("use_archive", False):
            ydl_opts['download_archive'] = str(self.archive_path)

        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file

        if self.ffmpeg_dir:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_dir

        # Optional rate limit
        rate_limit = self.config.get("rate_limit_bytes", 0)
        if rate_limit and rate_limit > 0:
            ydl_opts['ratelimit'] = rate_limit

        # Subtitles, Chapters & Thumbnails
        if self.config.get("embed_chapters", True):
            ydl_opts['addchapters'] = True

        if self.config.get("embed_thumbnail", True):
            ydl_opts['writethumbnail'] = True

        if self.config.get("embed_subtitles", False):
            ydl_opts['writesubtitles'] = True
            ydl_opts['allsubtitles'] = False
            ydl_opts['subtitleslangs'] = ['pt', 'pt-BR', 'en']

        # Format selection based on mode
        if mode == "audio":
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }]
        else:
            # Video mode: prioritize highest quality up to specified resolution with fallback
            if max_res == "best":
                ydl_opts['format'] = 'bestvideo+bestaudio/bestvideo*+bestaudio/best'
            else:
                ydl_opts['format'] = f'bestvideo[height<={max_res}]+bestaudio/best[height<={max_res}]/bestvideo*+bestaudio/best'

            ydl_opts['merge_output_format'] = 'mp4'

        return ydl_opts

    def download(self, url: str, mode: str = "best", resolution: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes safe and resilient download of a given URL.
        Returns a summary dict with title, duration, output_path, status, error.
        """
        start_time = time.time()
        safe_print(f"\n{Fore.BLUE}====================================================={Style.RESET_ALL}")
        safe_print(f"{Fore.CYAN}Iniciando analise do video:{Style.RESET_ALL} {url}")

        # Check free disk space (low threshold for cloud container environments)
        min_free_gb = float(self.config.get("min_free_space_gb", 0.05))
        free_gb = get_free_disk_space_gb(self.download_dir)
        safe_print(f"{Fore.WHITE}Espaco livre em disco: {free_gb:.2f} GB (Minimo requerido: {min_free_gb:.2f} GB){Style.RESET_ALL}")

        if 0 < free_gb < min_free_gb:
            err_msg = f"Espaco insuficiente em disco ({free_gb:.2f} GB disponivel, necessario pelo menos {min_free_gb:.2f} GB)"
            safe_print(f"{Fore.RED}ERRO: {err_msg}{Style.RESET_ALL}")
            return {"status": "FAILED", "url": url, "error": err_msg}

        # Step 1: Pre-fetch video details (optional, don't abort if it fails)
        info = self.get_video_info(url)
        title = info.get("title", "Video") if info else "Video da Web"
        duration = info.get("duration", 0) if info else 0
        channel = info.get("uploader", "Internet") if info else "Internet"

        safe_print(f"{Fore.GREEN}Titulo:{Style.RESET_ALL} {title}")
        safe_print(f"{Fore.GREEN}Canal:{Style.RESET_ALL} {channel}")
        if duration:
            safe_print(f"{Fore.GREEN}Duracao estimada:{Style.RESET_ALL} {format_seconds(duration)}")
        safe_print(f"{Fore.BLUE}-----------------------------------------------------{Style.RESET_ALL}")

        # Step 2: Build parameters and download
        ydl_opts = self.build_ydl_options(mode=mode, custom_resolution=resolution)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result_code = ydl.download([url])
                elapsed = time.time() - start_time

                if result_code == 0:
                    safe_print(f"{Fore.GREEN}[OK] SUCESSO! Download finalizado em {format_seconds(elapsed)}.{Style.RESET_ALL}")
                    return {
                        "status": "COMPLETED",
                        "url": url,
                        "title": title,
                        "channel": channel,
                        "duration": format_seconds(duration),
                        "duration_sec": duration,
                        "elapsed_sec": round(elapsed, 2),
                        "error": ""
                    }
                else:
                    return {
                        "status": "FAILED",
                        "url": url,
                        "title": title,
                        "error": f"yt-dlp retornou codigo {result_code}"
                    }

        except Exception as e:
            err_msg = str(e)
            safe_print(f"\n{Fore.RED}Falha durante o download: {err_msg}{Style.RESET_ALL}")
            return {
                "status": "FAILED",
                "url": url,
                "title": title,
                "error": err_msg
            }
