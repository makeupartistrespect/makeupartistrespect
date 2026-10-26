from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
import json
import threading
import unicodedata

BASE = Path(__file__).resolve().parent
DATA = BASE / "signatures.json"
LOCK = threading.Lock()
MAX_BODY = 4096


def load_signatures():
    try:
        data = json.loads(DATA.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def save_signatures(signatures):
    temp = DATA.with_suffix(".tmp")
    temp.write_text(
        json.dumps(signatures, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    temp.replace(DATA)


class PetitionHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE), **kwargs)

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/signatures":
            with LOCK:
                signatures = load_signatures()

            public = [
                {"name": s["name"], "message": s.get("message", "")}
                for s in reversed(signatures[-100:])
            ]
            self.send_json(200, {
                "total": len(signatures),
                "signatures": public
            })
            return

        if path == "/":
            self.path = "/index.html"

        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/signatures":
            self.send_json(404, {"error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0

        if not 0 < length <= MAX_BODY:
            self.send_json(413, {"error": "Invalid request size."})
            return

        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"error": "Invalid JSON."})
            return

        if not isinstance(data, dict):
            self.send_json(400, {"error": "Invalid request."})
            return

        name = unicodedata.normalize(
            "NFKC", str(data.get("name", ""))
        ).strip()
        message = unicodedata.normalize(
            "NFKC", str(data.get("message", ""))
        ).strip()

        name = " ".join(name.split())
        message = " ".join(message.split())

        if not name or len(name) > 70 or len(message) > 240:
            self.send_json(400, {
                "error": "Enter a name (maximum 70 characters) and a message under 240 characters."
            })
            return

        with LOCK:
            signatures = load_signatures()

            if any(
                s.get("name", "").casefold() == name.casefold()
                for s in signatures
            ):
                self.send_json(409, {
                    "error": "That name has already signed the petition."
                })
                return

            signatures.append({
                "name": name,
                "message": message
            })

            try:
                save_signatures(signatures)
            except OSError:
                self.send_json(500, {
                    "error": "Could not save the signature."
                })
                return

            total = len(signatures)

        self.send_json(201, {"ok": True, "total": total})

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), PetitionHandler)
    print("Petition server running at http://localhost:8000")
    print(f"Signatures are saved in: {DATA}")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()