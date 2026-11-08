"""Fail-closed API bearer authorization for remotely reachable CiteRAG services."""
import hmac
import os

class AuthenticationConfigurationError(RuntimeError):
    pass

def validate_binding(host: str) -> None:
    """Require a long token before binding beyond local loopback."""
    token = os.environ.get("CITERAG_API_TOKEN", "")
    if token and len(token) < 32:
        raise AuthenticationConfigurationError("CITERAG_API_TOKEN must have >=32 characters")
    if host not in {"127.0.0.1", "::1", "localhost"} and not token:
        raise AuthenticationConfigurationError("Non-loopback listener requires CITERAG_API_TOKEN")
    if os.getenv("CITERAG_REQUIRE_AUTH") == "1" and not token:
        raise AuthenticationConfigurationError("CITERAG_REQUIRE_AUTH needs CITERAG_API_TOKEN")

class BearerAuth:
    """ASGI middleware: protect every path except process liveness."""
    def __init__(self, app, public_paths=()):
        self.app = app
        self.public_paths = frozenset(public_paths)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or scope.get("path") in self.public_paths:
            await self.app(scope, receive, send)
            return
        expected = os.environ.get("CITERAG_API_TOKEN", "")
        if expected and len(expected) < 32:
            await self._reject(send)
            return
        if not expected:
            # Loopback-only development can continue without credentials.
            if os.environ.get("CITERAG_REQUIRE_AUTH") == "1":
                await self._reject(send)
                return
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers", [])
        authorization = [v for k, v in headers if k.lower() == b"authorization"]
        accepted = (len(authorization) == 1 and
                    hmac.compare_digest(authorization[0], b"Bearer " + expected.encode("utf-8")))
        if not accepted:
            await self._reject(send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send):
        body = b'{"error":"Unauthorized"}'
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json"),
                                (b"cache-control", b"no-store"),
                                (b"www-authenticate", b"Bearer"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
