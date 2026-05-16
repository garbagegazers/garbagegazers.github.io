#!/usr/bin/env python3
"""
Local development server with live reload for the site.
Watches for file changes and automatically refreshes the browser.
Uses PollingObserver for WSL/Windows filesystem compatibility.
"""

import http.server
import threading
import time
import os
import json
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler

PORT = 8000
WATCH_DIR = Path(__file__).parent
DEBOUNCE_SECONDS = 0.5

INJECT_SCRIPT = b"""
<script>
(function() {
    let lastCheck = Date.now();
    setInterval(() => {
        fetch('/__livereload__?since=' + lastCheck)
            .then(r => r.json())
            .then(data => {
                if (data.changed) {
                    console.log('[LiveReload] Change detected, reloading...');
                    location.reload();
                }
                lastCheck = data.time;
            })
            .catch(() => {});
    }, 500);
})();
</script>
"""

def get_last_updated():
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cd", "--date=format:%B %d, %Y"],
            cwd=str(WATCH_DIR), capture_output=True, text=True
        )
        date = result.stdout.strip()
        if date:
            return date
    except Exception:
        pass
    return datetime.now().strftime("%B %d, %Y")


changed = threading.Event()
last_change_time = {"t": time.time()}
last_event_time = {"t": 0.0}

IGNORE_DIRS = {".git", "__pycache__"}
IGNORE_EXTS = {".pyc", ".pyo"}
IGNORE_FILES = {"serve.py"}


class ChangeHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory:
            return
        self._handle(event.src_path)

    def on_created(self, event):
        if event.is_directory:
            return
        self._handle(event.src_path)

    def _handle(self, src):
        if any(d in src for d in IGNORE_DIRS):
            return
        if any(src.endswith(e) for e in IGNORE_EXTS):
            return
        if os.path.basename(src) in IGNORE_FILES:
            return
        now = time.time()
        # Debounce: ignore events within DEBOUNCE_SECONDS of the last one
        if now - last_event_time["t"] < DEBOUNCE_SECONDS:
            last_event_time["t"] = now
            return
        last_event_time["t"] = now
        last_change_time["t"] = now
        print(f"[LiveReload] Changed: {src}")
        changed.set()


class LiveReloadHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/__livereload__"):
            is_changed = changed.is_set()
            if is_changed:
                changed.clear()
            body = json.dumps({"changed": is_changed, "time": last_change_time["t"]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
            return

        # For HTML files, inject the live reload script
        clean_path = self.path.split("?")[0]
        fs_path = self.translate_path(clean_path)
        if os.path.isdir(fs_path):
            fs_path = os.path.join(fs_path, "index.html")

        if fs_path.endswith(".html") and os.path.isfile(fs_path):
            with open(fs_path, "rb") as f:
                content = f.read()
            # Inject last-updated date
            last_updated = get_last_updated()
            date_script = f'<script>window.addEventListener("DOMContentLoaded",function(){{var d="{last_updated}";var a=document.getElementById("last-updated");var b=document.getElementById("last-updated-fixed");if(a)a.textContent=d;if(b)b.textContent=d;}});</script>'.encode()
            injected = content.replace(b"</body>", date_script + INJECT_SCRIPT + b"</body>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(injected)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(injected)
            return

        # All other files (images, CSS, JS) served normally
        super().do_GET()

    def log_message(self, format, *args):
        if args and isinstance(args[0], str) and "/__livereload__" not in args[0]:
            super().log_message(format, *args)


def start_server():
    os.chdir(WATCH_DIR)
    server = http.server.HTTPServer(("", PORT), LiveReloadHandler)
    print(f"[Server] Serving at http://localhost:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    observer = PollingObserver(timeout=1)
    observer.schedule(ChangeHandler(), str(WATCH_DIR), recursive=True)
    observer.start()
    print(f"[Watcher] Watching {WATCH_DIR} for changes...")

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    print("[Server] Open http://localhost:8000 in your browser.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Server] Shutting down.")
        observer.stop()
    observer.join()

