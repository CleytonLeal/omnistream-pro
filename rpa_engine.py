import csv
import datetime
import os
import sys
import time
from pathlib import Path
from typing import List, Tuple, Dict, Any

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
except ImportError:
    class DummyColor:
        def __getattr__(self, name):
            return ""
    Fore = DummyColor()
    Style = DummyColor()

from config import load_config, BASE_DIR
from downloader import LongVideoDownloader


class RPAQueueProcessor:
    """
    RPA queue engine for batch processing, tracking, and continuous monitoring.
    """

    def __init__(self):
        self.config = load_config()
        self.queue_file = BASE_DIR / self.config.get("queue_file", "queue.txt")
        self.completed_file = BASE_DIR / "queue_completed.txt"
        self.history_csv = BASE_DIR / self.config.get("history_csv", "queue_history.csv")
        self.downloader = LongVideoDownloader()

        self._ensure_files()

    def _ensure_files(self):
        """Ensures queue and history files exist."""
        if not self.queue_file.exists():
            with open(self.queue_file, "w", encoding="utf-8") as f:
                f.write("# Cole aqui os links de vídeos (um por linha).\n")
                f.write("# Exemplo:\n")
                f.write("# https://www.youtube.com/watch?v=exemplo\n")
                f.write("# https://www.youtube.com/watch?v=exemplo2 | audio\n\n")

        if not self.history_csv.exists():
            with open(self.history_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Data/Hora", "URL", "Título", "Canal", "Duração",
                    "Tempo Gasto (s)", "Status", "Erro"
                ])

    def parse_queue(self) -> List[Tuple[str, str, str]]:
        """
        Parses queue.txt.
        Returns a list of tuples: (raw_line, url, mode_or_quality)
        """
        if not self.queue_file.exists():
            return []

        tasks = []
        with open(self.queue_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            parts = [p.strip() for p in stripped.split("|")]
            url = parts[0]
            mode = "best"
            if len(parts) > 1:
                arg = parts[1].lower()
                if "audio" in arg or "mp3" in arg:
                    mode = "audio"
                elif arg in ["720", "720p", "1080", "1080p", "1440", "1440p", "2160", "2160p", "4k"]:
                    mode = arg.replace("p", "").replace("4k", "2160")
                else:
                    mode = parts[1]

            tasks.append((line, url, mode))

        return tasks

    def record_history(self, result: Dict[str, Any]):
        """Records download result into CSV history."""
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.history_csv, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                now_str,
                result.get("url", ""),
                result.get("title", ""),
                result.get("channel", ""),
                result.get("duration", ""),
                result.get("elapsed_sec", ""),
                result.get("status", ""),
                result.get("error", "")
            ])

    def mark_completed(self, raw_line: str, result: Dict[str, Any]):
        """
        Moves completed URL from queue.txt to queue_completed.txt.
        """
        try:
            # Read all lines
            with open(self.queue_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Filter out the completed line
            remaining_lines = []
            removed = False
            for line in lines:
                if not removed and line.strip() == raw_line.strip():
                    removed = True
                    continue
                remaining_lines.append(line)

            # Write back remaining
            with open(self.queue_file, "w", encoding="utf-8") as f:
                f.writelines(remaining_lines)

            # Append to completed
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.completed_file, "a", encoding="utf-8") as f:
                f.write(f"[{now_str}] {result.get('status')} - {raw_line.strip()} | {result.get('title', '')}\n")

        except Exception as e:
            print(f"{Fore.YELLOW}[Aviso] Falha ao atualizar queue.txt: {e}{Style.RESET_ALL}")

    def process_queue_once(self) -> int:
        """
        Processes all pending links in queue.txt once.
        Returns number of tasks processed.
        """
        tasks = self.parse_queue()
        if not tasks:
            return 0

        print(f"\n{Fore.CYAN}📋 Fila de RPA encontrada: {len(tasks)} tarefa(s) pendente(s).{Style.RESET_ALL}")

        processed_count = 0
        for raw_line, url, mode in tasks:
            print(f"\n{Fore.YELLOW}▶ Processando item: {url} (Modo: {mode}){Style.RESET_ALL}")

            is_audio = (mode == "audio")
            res = None if is_audio or mode == "best" else mode

            result = self.downloader.download(
                url=url,
                mode="audio" if is_audio else "best",
                resolution=res
            )

            self.record_history(result)

            if result.get("status") == "COMPLETED":
                self.mark_completed(raw_line, result)
                processed_count += 1
            else:
                print(f"{Fore.RED}✘ O download do link falhou. O link permanecerá na fila para nova tentativa.{Style.RESET_ALL}")

        return processed_count

    def run_watcher(self):
        """
        RPA Watcher / Daemon: monitors queue.txt and executes downloads automatically.
        """
        interval = int(self.config.get("watcher_interval_seconds", 10))
        print(f"\n{Fore.GREEN}====================================================={Style.RESET_ALL}")
        print(f"{Fore.GREEN}🤖 ROBÔ VIGILANTE RPA INICIADO{Style.RESET_ALL}")
        print(f"Monitorando o arquivo: {self.queue_file}")
        print(f"Intervalo de checagem: {interval} segundos")
        print(f"Pressione {Fore.YELLOW}Ctrl + C{Style.RESET_ALL} a qualquer momento para pausar/sair.")
        print(f"{Fore.GREEN}====================================================={Style.RESET_ALL}\n")

        try:
            while True:
                processed = self.process_queue_once()
                if processed > 0:
                    print(f"\n{Fore.GREEN}✔ Lote concluído! Aguardando novos links...{Style.RESET_ALL}")
                
                # Sleep with dot display
                time.sleep(interval)
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Robô Vigilante finalizado pelo usuário.{Style.RESET_ALL}")
