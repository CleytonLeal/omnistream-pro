import csv
import datetime
import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from config import load_config, BASE_DIR, get_free_disk_space_gb
from downloader import LongVideoDownloader, format_bytes, format_seconds


class BackgroundTaskManager:
    """
    Central background task manager for running yt-dlp downloads asynchronously.
    Runs a worker thread that consumes tasks from a queue without blocking the UI.
    """

    def __init__(self):
        self.config = load_config()
        self.download_dir = BASE_DIR / self.config.get("download_dir", "downloads")
        self.queue_file = BASE_DIR / self.config.get("queue_file", "queue.txt")
        self.completed_file = BASE_DIR / "queue_completed.txt"
        self.history_csv = BASE_DIR / self.config.get("history_csv", "queue_history.csv")

        self.task_queue = queue.Queue()
        self.active_task: Optional[Dict[str, Any]] = None
        self.queued_tasks: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []

        self.lock = threading.Lock()
        self.worker_thread = None
        self.watcher_thread = None
        self.watcher_enabled = False
        self.is_running = True

        self._load_history()
        self._start_worker()

    def _load_history(self):
        """Loads last 30 entries from history CSV."""
        if not self.history_csv.exists():
            return

        try:
            with open(self.history_csv, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
                if len(rows) > 1:
                    headers = rows[0]
                    for row in rows[1:][-30:]:
                        if len(row) >= 7:
                            self.history.append({
                                "date": row[0],
                                "url": row[1],
                                "title": row[2],
                                "channel": row[3],
                                "duration": row[4],
                                "elapsed": row[5],
                                "status": row[6],
                                "error": row[7] if len(row) > 7 else ""
                            })
                    self.history.reverse()
        except Exception as e:
            print(f"[Aviso] Falha ao ler historico: {e}")

    def _start_worker(self):
        """Spawns the continuous background worker thread."""
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def _worker_loop(self):
        """Main loop that executes downloads sequentially in background."""
        while self.is_running:
            try:
                task = self.task_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            with self.lock:
                self.active_task = task
                self.queued_tasks = [t for t in self.queued_tasks if t["id"] != task["id"]]

            self._execute_task(task)

            with self.lock:
                self.active_task = None
            self.task_queue.task_done()

    def _execute_task(self, task: Dict[str, Any]):
        """Executes a single download task using LongVideoDownloader with live progress callbacks."""
        task_id = task["id"]
        url = task["url"]
        mode = task.get("mode", "best")
        quality = task.get("quality")

        task["status"] = "ANALYZING"
        task["message"] = "Carregando metadados do vídeo..."
        task["start_time"] = time.time()

        def custom_hook(d: Dict[str, Any]):
            status = d.get('status')
            if status == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes', 0)
                percent = (downloaded / total * 100.0) if total > 0 else 0.0

                with self.lock:
                    if self.active_task and self.active_task["id"] == task_id:
                        self.active_task["status"] = "DOWNLOADING"
                        self.active_task["percent"] = round(percent, 1)
                        self.active_task["downloaded_bytes"] = downloaded
                        self.active_task["total_bytes"] = total
                        self.active_task["downloaded_str"] = format_bytes(downloaded)
                        self.active_task["total_str"] = format_bytes(total) if total > 0 else "Calculando..."
                        self.active_task["speed_str"] = format_bytes(d.get('speed', 0)) + "/s"
                        self.active_task["eta_str"] = format_seconds(d.get('eta'))
                        self.active_task["message"] = f"Baixando: {self.active_task['percent']}%"

            elif status == 'finished':
                with self.lock:
                    if self.active_task and self.active_task["id"] == task_id:
                        self.active_task["status"] = "PROCESSING"
                        self.active_task["message"] = "Mesclando fluxos com FFmpeg..."

        # Create downloader with progress callback
        downloader = LongVideoDownloader()
        downloader._progress_hook = custom_hook

        # Pre-fetch info to update UI
        try:
            info = downloader.get_video_info(url)
            if info:
                with self.lock:
                    task["title"] = info.get("title", "Sem título")
                    task["channel"] = info.get("uploader", "Desconhecido")
                    task["duration"] = format_seconds(info.get("duration", 0))
                    task["thumbnail"] = info.get("thumbnail", "")
        except Exception:
            pass

        # Perform download
        result = downloader.download(url, mode=mode, resolution=quality)
        elapsed = time.time() - task["start_time"]
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        history_item = {
            "date": now_str,
            "url": url,
            "title": result.get("title", task.get("title", "Vídeo")),
            "channel": result.get("channel", task.get("channel", "Canal")),
            "duration": result.get("duration", task.get("duration", "")),
            "elapsed": f"{round(elapsed, 1)}s",
            "status": result.get("status", "FAILED"),
            "error": result.get("error", "")
        }

        with self.lock:
            self.history.insert(0, history_item)
            if len(self.history) > 50:
                self.history.pop()

        # Save to CSV
        try:
            with open(self.history_csv, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    now_str, url, history_item["title"], history_item["channel"],
                    history_item["duration"], history_item["elapsed"],
                    history_item["status"], history_item["error"]
                ])
        except Exception:
            pass

    def add_task(self, url: str, mode: str = "best", quality: Optional[str] = None) -> Dict[str, Any]:
        """Adds a new URL to the background download queue."""
        url = url.strip()
        task = {
            "id": str(uuid.uuid4())[:8],
            "url": url,
            "mode": mode,
            "quality": quality,
            "title": "Aguardando na fila...",
            "channel": "",
            "duration": "",
            "thumbnail": "",
            "status": "QUEUED",
            "percent": 0.0,
            "downloaded_str": "0 MB",
            "total_str": "--",
            "speed_str": "0 KB/s",
            "eta_str": "--:--",
            "message": "Na fila de processamento",
            "created_at": datetime.datetime.now().strftime("%H:%M:%S")
        }

        with self.lock:
            self.queued_tasks.append(task)
        self.task_queue.put(task)
        return task

    def add_batch(self, urls_text: str, default_mode: str = "best") -> int:
        """Parses a multiline string and enqueues all URLs."""
        lines = urls_text.strip().splitlines()
        count = 0
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            parts = [p.strip() for p in stripped.split("|")]
            url = parts[0]
            mode = default_mode
            quality = None

            if len(parts) > 1:
                arg = parts[1].lower()
                if "audio" in arg or "mp3" in arg:
                    mode = "audio"
                elif arg in ["720", "720p", "1080", "1080p", "1440", "1440p", "2160", "2160p", "4k"]:
                    quality = arg.replace("p", "").replace("4k", "2160")
                    mode = "best"

            self.add_task(url=url, mode=mode, quality=quality)
            count += 1
        return count

    def set_watcher_enabled(self, enable: bool):
        """Enables or disables the background queue.txt watcher."""
        self.watcher_enabled = enable
        if enable and (self.watcher_thread is None or not self.watcher_thread.is_alive()):
            self.watcher_thread = threading.Thread(target=self._watcher_loop, daemon=True)
            self.watcher_thread.start()

    def _watcher_loop(self):
        """Continuously monitors queue.txt and enqueues new items."""
        while self.watcher_enabled and self.is_running:
            if self.queue_file.exists():
                try:
                    with open(self.queue_file, "r", encoding="utf-8") as f:
                        lines = f.readlines()

                    new_lines = []
                    found_any = False
                    for line in lines:
                        stripped = line.strip()
                        if stripped and not stripped.startswith("#"):
                            parts = [p.strip() for p in stripped.split("|")]
                            url = parts[0]
                            mode = "best"
                            quality = None
                            if len(parts) > 1:
                                arg = parts[1].lower()
                                if "audio" in arg or "mp3" in arg:
                                    mode = "audio"
                                else:
                                    quality = arg.replace("p", "").replace("4k", "2160")

                            self.add_task(url=url, mode=mode, quality=quality)
                            found_any = True
                        else:
                            new_lines.append(line)

                    # Empty the consumed lines from queue.txt
                    if found_any:
                        with open(self.queue_file, "w", encoding="utf-8") as f:
                            f.writelines(new_lines)

                except Exception as e:
                    print(f"[Watcher] Erro ao ler fila: {e}")

            time.sleep(int(self.config.get("watcher_interval_seconds", 10)))

    def open_downloads_folder(self) -> Dict[str, Any]:
        """Opens the downloads directory in Windows File Explorer reliably."""
        p = Path(self.download_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                import subprocess
                subprocess.Popen(["explorer.exe", str(p)])
                try:
                    subprocess.Popen([
                        "powershell", "-WindowStyle", "Hidden", "-Command",
                        f"Start-Process explorer.exe -ArgumentList '\"{str(p)}\"'"
                    ])
                except Exception:
                    pass
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(p)])
            return {"success": True, "path": str(p)}
        except Exception as e:
            print(f"[Erro] Falha ao abrir pasta: {e}")
            return {"error": str(e), "path": str(p)}

    def open_file(self, filename: str) -> Dict[str, Any]:
        """Opens or reveals a specific downloaded file in Windows Explorer."""
        p = (Path(self.download_dir) / filename).resolve()
        if not p.exists():
            return {"error": "Arquivo não encontrado", "path": str(p)}
        try:
            if sys.platform.startswith("win"):
                import subprocess
                subprocess.Popen(["explorer.exe", f"/select,{str(p)}"])
                try:
                    subprocess.Popen([
                        "powershell", "-WindowStyle", "Hidden", "-Command",
                        f"Start-Process explorer.exe -ArgumentList '/select,\"{str(p)}\"'"
                    ])
                except Exception:
                    pass
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(p.parent)])
            return {"success": True, "path": str(p), "filename": filename}
        except Exception as e:
            return {"error": str(e), "path": str(p)}

    def list_downloaded_files(self) -> List[Dict[str, Any]]:
        """Lists all downloaded video/audio files with metadata."""
        files_list = []
        p = Path(self.download_dir).resolve()
        if not p.exists():
            return []
        try:
            idx = 0
            for item in sorted(p.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if item.is_file() and not item.name.endswith(".part"):
                    stat = item.stat()
                    files_list.append({
                        "id": idx,
                        "filename": item.name,
                        "path": str(item.resolve()),
                        "size_bytes": stat.st_size,
                        "size_formatted": format_bytes(stat.st_size),
                        "modified_time": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
                        "ext": item.suffix.lower().replace(".", ""),
                        "download_url": f"/downloads/{item.name}"
                    })
                    idx += 1
        except Exception as e:
            print(f"[Aviso] Falha ao listar arquivos: {e}")
        return files_list

    def get_system_status(self) -> Dict[str, Any]:
        """Returns overall state for API/UI."""
        free_gb = get_free_disk_space_gb(self.download_dir)
        files = self.list_downloaded_files()

        with self.lock:
            active = self.active_task.copy() if self.active_task else None
            queued = [t.copy() for t in self.queued_tasks]
            history = [h.copy() for h in self.history[:25]]

        return {
            "free_disk_gb": round(free_gb, 2),
            "watcher_enabled": self.watcher_enabled,
            "active_task": active,
            "queued_count": len(queued),
            "queued_tasks": queued,
            "history": history,
            "last_result": history[0] if history else None,
            "downloaded_files": files,
            "total_files_count": len(files),
            "download_dir_path": str(Path(self.download_dir).resolve())
        }


# Global singleton instance
manager = BackgroundTaskManager()
