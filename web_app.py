import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from config import BASE_DIR
from background_worker import manager

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/downloads/<path:filename>")
def serve_download(filename):
    """Serves downloaded video or audio directly for streaming or local download."""
    folder = str(Path(manager.download_dir).resolve())
    return send_from_directory(folder, filename, as_attachment=False)


@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify(manager.get_system_status())


@app.route("/api/files", methods=["GET"])
def api_files():
    return jsonify({"files": manager.list_downloaded_files(), "path": str(Path(manager.download_dir).resolve())})


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.json or {}
    url = data.get("url", "").strip()
    mode = data.get("mode", "best")
    quality = data.get("quality")

    if not url:
        return jsonify({"error": "URL inválida ou vazia"}), 400

    task = manager.add_task(url=url, mode=mode, quality=quality)
    return jsonify({"success": True, "task": task})


@app.route("/api/batch", methods=["POST"])
def api_batch():
    data = request.json or {}
    urls_text = data.get("urls", "").strip()
    mode = data.get("mode", "best")

    if not urls_text:
        return jsonify({"error": "Nenhum link fornecido"}), 400

    count = manager.add_batch(urls_text=urls_text, default_mode=mode)
    return jsonify({"success": True, "count": count})


@app.route("/api/download-media/<int:file_id>", methods=["GET"])
def api_download_media(file_id):
    """Directly triggers native file download to user's device storage (phone or PC)."""
    files = manager.list_downloaded_files()
    target = next((f for f in files if f.get("id") == file_id), None)
    if not target:
        return jsonify({"error": "Arquivo não encontrado"}), 404
    folder = str(Path(manager.download_dir).resolve())
    return send_from_directory(
        folder,
        target["filename"],
        as_attachment=True,
        download_name=target["filename"]
    )


@app.route("/api/detect-lang", methods=["GET"])
def api_detect_lang():
    """Detects preferred language from client's Accept-Language header."""
    best = request.accept_languages.best_match(["pt", "en", "es", "fr", "de"]) or "pt"
    return jsonify({"lang": best})


@app.route("/api/cookie-status", methods=["GET"])
def api_cookie_status():
    """Checks whether YouTube authentication cookies are present."""
    cookie_path = BASE_DIR / "cookies.txt"
    has_cookies = (cookie_path.exists() and cookie_path.stat().st_size > 0) or bool(os.environ.get("YOUTUBE_COOKIES"))
    return jsonify({"has_cookies": has_cookies})


@app.route("/api/upload-cookies", methods=["POST"])
def api_upload_cookies():
    """Receives cookies file or raw text to unlock YouTube on cloud hosting."""
    cookie_content = ""
    if "file" in request.files:
        f = request.files["file"]
        cookie_content = f.read().decode("utf-8", errors="ignore")
    elif request.json and "cookies" in request.json:
        cookie_content = request.json.get("cookies", "")
    elif request.form and "cookies" in request.form:
        cookie_content = request.form.get("cookies", "")

    if not cookie_content.strip():
        return jsonify({"error": "Nenhum conteúdo de cookie fornecido"}), 400

    cookie_path = BASE_DIR / "cookies.txt"
    try:
        cookie_path.write_text(cookie_content.strip(), encoding="utf-8")
        return jsonify({"success": True, "message": "Cookies do YouTube configurados com sucesso! O YouTube agora está desbloqueado."})
    except Exception as e:
        return jsonify({"error": f"Erro ao salvar arquivo: {e}"}), 500


@app.route("/api/watcher", methods=["POST"])
def api_watcher():
    data = request.json or {}
    enable = bool(data.get("enable", False))
    manager.set_watcher_enabled(enable)
    return jsonify({"success": True, "watcher_enabled": manager.watcher_enabled})


@app.route("/api/open-folder", methods=["POST"])
def api_open_folder():
    res = manager.open_downloads_folder()
    if res.get("error"):
        return jsonify(res), 500
    return jsonify(res)


@app.route("/api/open-file", methods=["POST"])
def api_open_file():
    data = request.json or {}
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"error": "Nome do arquivo não especificado"}), 400
    res = manager.open_file(filename)
    if res.get("error"):
        return jsonify(res), 404
    return jsonify(res)


def open_browser():
    """Wait 1.2s for server to start, then open user default browser."""
    time.sleep(1.2)
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    is_cloud = bool(os.environ.get("PORT") or os.environ.get("RENDER") or os.environ.get("RAILWAY_ENVIRONMENT"))
    default_host = "0.0.0.0" if is_cloud else "127.0.0.1"
    host = os.environ.get("HOST", default_host)

    print(f"\n[OmniStream PRO] Servidor rodando em http://{host}:{port}")
    if not is_cloud:
        print("[OmniStream PRO] Abrindo navegador automaticamente...")
        threading.Thread(target=open_browser, daemon=True).start()

    app.run(host=host, port=port, debug=False)
