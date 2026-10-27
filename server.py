
import json
import os
import threading
import unicodedata
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

PORT = int(os.environ.get("PORT", "10000"))
HOST = "0.0.0.0"
DATA_FILE = Path(os.environ.get("SIGNATURES_FILE", "signatures.json"))
MAX_BODY_SIZE = 8192
MAX_SIGNATURES = 10000


ALLOWED_ORIGINS = {
    "https://makeupartistrespect.github.io",
    "https://lennycroft89-hue.github.io",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
}


LOCK = threading.Lock()


def clean_text(value, limit):
    if not isinstance(value, str):
        return ""

    value = unicodedata.normalize("NFKC", value)
    value = "".join(
        char for char in value
        if char.isprintable() or char in "\n\t"
    )
    return value.strip()[:limit]


def load_signatures():
    with LOCK:
        try:
            if not DATA_FILE.exists():
                return []

            with DATA_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)

            if isinstance(data, list):
                return data[:MAX_SIGNATURES]

        except (OSError, json.JSONDecodeError) as error:
            print(f"Could not load signatures: {error}", flush=True)

        return []


def save_signature(signature):
    with LOCK:
        signatures = []

        try:
            if DATA_FILE.exists():
                with DATA_FILE.open("r", encoding="utf-8") as file:
                    data = json.load(file)

                if isinstance(data, list):
                    signatures = data[:MAX_SIGNATURES]

        except (OSError, json.JSONDecodeError) as error:
            print(f"Could not read signature file: {error}", flush=True)

        if len(signatures) >= MAX_SIGNATURES:
            return False

        signatures.insert(0, signature)

        try:
            DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            temporary_file = DATA_FILE.with_name(DATA_FILE.name + ".tmp")

            with temporary_file.open("w", encoding="utf-8") as file:
                json.dump(signatures, file, ensure_ascii=False, indent=2)

            temporary_file.replace(DATA_FILE)
            return True

        except OSError as error:
            print(f"Could not save signature: {error}", flush=True)
            return False


class PetitionHandler(BaseHTTPRequestHandler):
    server_version = "PetitionServer/1.0"

    def log_message(self, format_string, *args):
        print(
            f"{self.client_address[0]} - {format_string % args}",
            flush=True
        )

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")

        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header(
                "Access-Control-Allow-Methods",
                "GET, POST, OPTIONS"
            )
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type"
            )

        self.end_headers()

        if self.command != "HEAD":
            self.wfile.write(body)

    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "")

        self.send_response(204)

        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header(
                "Access-Control-Allow-Methods",
                "GET, POST, OPTIONS"
            )
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "86400")

        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/healthz":
            self.send_json(200, {"status": "ok"})
            return

        if path == "/":
            self.send_json(200, {
                "service": "Makeup Artists Deserve Respect Petition API",
                "status": "online",
                "endpoints": ["/healthz", "/api/signatures"]
            })
            return

        if path == "/api/signatures":
            signatures = load_signatures()
            self.send_json(200, {
                "count": len(signatures),
                "signatures": signatures
            })
            return

        self.send_json(404, {"error": "Not found"})

    def do_HEAD(self):
        path = urlparse(self.path).path

        if path == "/healthz":
            self.send_json(200, {"status": "ok"})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path

        if path != "/api/signatures":
            self.send_json(404, {"error": "Not found"})
            return

        origin = self.headers.get("Origin", "")
        if origin and origin not in ALLOWED_ORIGINS:
            self.send_json(403, {"error": "Origin not allowed"})
            return

        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type.lower():
            self.send_json(415, {"error": "Expected application/json"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Invalid content length"})
            return

        if length <= 0 or length > MAX_BODY_SIZE:
            self.send_json(413, {"error": "Request size is invalid"})
            return

        try:
            raw_body = self.rfile.read(length)
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"error": "Invalid JSON"})
            return

        if not isinstance(payload, dict):
            self.send_json(400, {"error": "Expected a JSON object"})
            return

        name = clean_text(payload.get("name"), 60)
        message = clean_text(payload.get("message", ""), 500)

        if len(name) < 2:
            self.send_json(400, {
                "error": "Name must contain at least 2 characters"
            })
            return

        if not message:
            self.send_json(400, {
                "error": "Please include a message with your signature"
            })
            return

        signature = {
            "name": name,
            "message": message,
            "date": datetime.now(timezone.utc).isoformat()
        }

        if not save_signature(signature):
            self.send_json(503, {
                "error": "Could not save signature. Please try again later."
            })
            return

        print(f"New petition signature received from {name!r}", flush=True)
        self.send_json(201, {
            "success": True,
            "signature": signature
        })


if __name__ == "__main__":
    print(f"Starting petition server on {HOST}:{PORT}", flush=True)

    server = ThreadingHTTPServer((HOST, PORT), PetitionHandler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down petition server", flush=True)
    finally:
        server.server_close()
