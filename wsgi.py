"""
WSGI entrypoint for production servers (Gunicorn, Waitress, uWSGI).
Usage:
  gunicorn --workers=1 --threads=4 --timeout=180 --bind=0.0.0.0:$PORT wsgi:app
"""
import os
from web_app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    app.run(host=host, port=port)
