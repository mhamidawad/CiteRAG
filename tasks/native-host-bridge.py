#!/usr/bin/env python3
"""Private stdlib host bridge: one fixed, bounded native runner and no database work."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from citerag import native
from citerag.native_result import runtime_fingerprint

HOST = "127.0.0.1"
PORT = 60760
MAX_BODY = 4096
MAX_REPORT = 262144


class BridgeConfigurationError(ValueError):
    pass


class BridgeService:
    def __init__(self):
        if os.environ.get("CITERAG_NATIVE_BRIDGE_URL"):
            raise BridgeConfigurationError("Host environment must not enable the bridge client")
        self.token = os.environ.get("CITERAG_NATIVE_BRIDGE_TOKEN", "")
        if len(self.token) < 32 or native.configuration_status() != "ready":
            raise BridgeConfigurationError("Dedicated host configuration required")
        self.backend = os.environ["CITERAG_BACKEND_ID"]
        self.env_file = Path(os.environ["CITERAG_NATIVE_ENV_FILE"])
        if self.env_file.stat().st_uid != os.getuid():
            raise BridgeConfigurationError("Native environment must belong to runtime user")
        values = dict(line.split("=", 1) for line in self.env_file.read_text().splitlines()
                      if "=" in line and not line.startswith("#"))
        if not values.get("CITERAG_API_TOKEN") or self.token == values["CITERAG_API_TOKEN"]:
            raise BridgeConfigurationError("Independent bridge credential required")
        self.binary = Path(os.environ["CITERAG_NATIVE_BINARY_DIR"])
        self.mcp_url = os.environ.get("CITERAG_NATIVE_MCP_URL", "")
        url = urlparse(self.mcp_url)
        if (url.scheme != "http" or url.hostname != HOST or url.path != "/mcp"
                or not url.port or url.username or url.password or url.query or url.fragment):
            raise BridgeConfigurationError("Explicit local CiteRAG MCP required")
        self.owner = threading.BoundedSemaphore(1)

    def identity(self):
        return {"backend_id": self.backend, "runtime_fingerprint": runtime_fingerprint(),
                "bridge_fingerprint": native.bridge_code_fingerprint()}

    def status(self):
        return {"status": native.verification_status(), **self.identity()}

    def answer(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"question", "expected_backend_id"}:
            return 400, {"error": "Invalid request"}
        question = payload.get("question")
        if (payload["expected_backend_id"] != self.backend or not isinstance(question, str)
                or not 1 <= len(question.strip()) <= 400):
            return 400, {"error": "Invalid request"}
        if not self.owner.acquire(blocking=False):
            return 409, {"error": "Native request already running"}
        try:
            command = [sys.executable, str(ROOT / "tasks/verify-native.py"),
                       "--question", question.strip(), "--env-file", str(self.env_file),
                       "--binary-dir", str(self.binary), "--mcp-url", self.mcp_url,
                       "--expected-backend-id", self.backend]
            result = subprocess.run(command, capture_output=True, text=True, timeout=260)
            if len(result.stdout.encode()) > MAX_REPORT:
                return 502, {"error": "Native result invalid"}
            report = json.loads(result.stdout)
            if (result.returncode or not isinstance(report, dict)
                    or report.get("status") != "PASS"
                    or report.get("backend_identity_attested") is not True
                    or report.get("backend_id") != self.backend
                    or report.get("runtime_fingerprint") != runtime_fingerprint()):
                return 502, {"error": "Native verification failed"}
            return 200, {**report, "bridge_fingerprint": native.bridge_code_fingerprint()}
        except (OSError, ValueError, subprocess.SubprocessError):
            return 502, {"error": "Native runner failed"}
        finally:
            self.owner.release()


def handler_for(service):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CiteRAGNativeBridge"
        sys_version = ""

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass

        def reply(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            values = self.headers.get_all("Authorization", [])
            accepted = (len(values) == 1 and
                        hmac.compare_digest(values[0].encode(),
                                            ("Bearer " + service.token).encode()))
            if not accepted:
                self.reply(401, {"error": "Unauthorized"})
            return accepted

        def do_GET(self):
            if not self.authorized():
                return
            if self.path != "/status":
                self.reply(404, {"error": "Unknown route"})
                return
            try:
                self.reply(200, service.status())
            except Exception:
                self.reply(503, {"error": "Native status unavailable"})

        def do_POST(self):
            if not self.authorized():
                return
            if self.path != "/answer":
                self.reply(404, {"error": "Unknown route"})
                return
            lengths = self.headers.get_all("Content-Length", [])
            if (self.headers.get("Transfer-Encoding") or len(lengths) != 1
                    or not lengths[0].isdecimal() or not 1 <= int(lengths[0]) <= MAX_BODY
                    or self.headers.get_content_type() != "application/json"):
                self.reply(400, {"error": "Invalid request"})
                return
            try:
                payload = json.loads(self.rfile.read(int(lengths[0])))
            except (ValueError, OSError):
                self.reply(400, {"error": "Invalid request"})
                return
            status, report = service.answer(payload)
            self.reply(status, report)
    return Handler


def main():
    try:
        service = BridgeService()
        server = ThreadingHTTPServer((HOST, PORT), handler_for(service))
        server.daemon_threads = True
        server.serve_forever(poll_interval=0.5)
    except (BridgeConfigurationError, OSError, ValueError):
        print("Native bridge configuration or listener unavailable", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
