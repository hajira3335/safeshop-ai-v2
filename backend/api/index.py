import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app as _fastapi_app  # noqa: E402

PREFIXES = ("/api/index.py", "/api/index", "/api")


class StripPrefix:
    """Removes Vercel's /api/index prefix so /health and /analyze match."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "/")
            for p in PREFIXES:
                if path == p or path.startswith(p + "/"):
                    path = path[len(p):] or "/"
                    scope = dict(scope)
                    scope["path"] = path
                    if "raw_path" in scope:
                        scope["raw_path"] = path.encode()
                    break
        await self.inner(scope, receive, send)


app = StripPrefix(_fastapi_app)
