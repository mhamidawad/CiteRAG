"""Fail-closed API bearer authorization for remotely reachable CiteRAG services."""
import hmac
import os
import sqlite3
from citerag.policy import configuration, enforce, PolicyConfigurationError

class AuthenticationConfigurationError(RuntimeError):
    pass

def validate_binding(host: str) -> None:
    """Require a long token before binding beyond local loopback."""
    token = os.environ.get("CITERAG_API_TOKEN", "")
    if token and len(token) < 32:
        raise AuthenticationConfigurationError("CITERAG_API_TOKEN must have >=32 characters")
    if host not in {"127.0.0.1", "::1", "localhost"} and not token:
        raise AuthenticationConfigurationError("Non-loopback listener requires CITERAG_API_TOKEN")
    if (os.getenv("CITERAG_REQUIRE_AUTH") == "1" or os.getenv("CITERAG_PRODUCTION") == "1") and not token:
        raise AuthenticationConfigurationError("Authenticated deployment requires CITERAG_API_TOKEN")
    try:
        configuration()
    except PolicyConfigurationError as exc:
        raise AuthenticationConfigurationError(str(exc)) from exc

class BearerAuth:
    """Authenticate and enforce a single-workspace deployment boundary before handlers."""
    def __init__(self, app, public_paths=()):
        self.app = app
        self.public_paths = frozenset(public_paths)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or scope.get("path") in self.public_paths:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        expected = os.environ.get("CITERAG_API_TOKEN", "")
        if expected and len(expected) < 32:
            await self._reject(send)
            return
        if not expected:
            if os.environ.get("CITERAG_REQUIRE_AUTH") == "1" or os.getenv("CITERAG_PRODUCTION") == "1":
                await self._reject(send)
                return
        else:
            authorization = [v for k, v in scope.get("headers", []) if k.lower() == b"authorization"]
            accepted = (len(authorization) == 1 and
                        hmac.compare_digest(authorization[0], b"Bearer " + expected.encode("utf-8")))
            if not accepted:
                await self._reject(send)
                return
        try:
            status, receive = await enforce(scope, receive)
        except (PolicyConfigurationError, sqlite3.Error, OSError):
            await self._reject(send, 503)
            return
        if status is not None:
            await self._reject(send, status)
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send, status=401):
        errors = {401: b'{"error":"Unauthorized"}', 403: b'{"error":"Workspace access denied"}',
                  413: b'{"error":"Request too large"}', 429: b'{"error":"Admission budget exceeded"}',
                  400: b'{"error":"Invalid request"}', 503: b'{"error":"Authorization policy unavailable"}'}
        body = errors[status]
        headers = [(b"content-type", b"application/json"), (b"cache-control", b"no-store"),
                   (b"content-length", str(len(body)).encode())]
        if status == 401:
            headers.append((b"www-authenticate", b"Bearer"))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
