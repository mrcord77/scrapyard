"""
pagination_params — Shared query params for page/cursor pagination.

### PART-META-JSON
{
  "name": "pagination_params",
  "layer": "api",
  "purpose": "Shared pagination query parameters: a PaginationParams dataclass with defensive clamping (limit 1..max, offset >= 0) and a FastAPI dependency reading ?limit/?offset that feeds scrapyard.database.pagination.paginate().",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Client-supplied limit/offset query parameters.",
  "outputs": "A clamped PaginationParams instance.",
  "files_created": [],
  "security_notes": "Clamping caps limit at 200 and floors it at 1, and floors offset at 0, so a hostile ?limit=999999 cannot force unbounded result sets regardless of what the route does with it. Pure stdlib — usable as a FastAPI dependency but with no hard fastapi import.",
  "ai_usage": "def route(p: PaginationParams = Depends(pagination_params)): page = paginate(db, stmt, limit=p.limit, offset=p.offset).",
  "example": "params = pagination_params(limit=500)  # clamped to 200",
  "import_path": "scrapyard.api.pagination_params"
}
### END-PART-META
"""
from __future__ import annotations
from dataclasses import dataclass
STATUS = "core"

@dataclass
class PaginationParams:
    limit: int = 50
    offset: int = 0
    def clamped(self, max_limit: int = 200) -> "PaginationParams":
        return PaginationParams(max(1, min(self.limit, max_limit)), max(0, self.offset))

def pagination_params(limit: int = 50, offset: int = 0) -> PaginationParams:
    """FastAPI dependency: read ?limit & ?offset and clamp to safe bounds.
    Feeds scrapyard.database.pagination.paginate()."""
    return PaginationParams(limit=limit, offset=offset).clamped()


def _selftest() -> None:
    # defaults
    p = pagination_params()
    assert p.limit == 50 and p.offset == 0

    # clamping: hostile values are bounded
    assert pagination_params(limit=999_999).limit == 200
    assert pagination_params(limit=0).limit == 1
    assert pagination_params(limit=-5).limit == 1
    assert pagination_params(offset=-10).offset == 0
    assert pagination_params(limit=25, offset=100) == PaginationParams(25, 100)

    # clamped() with a custom cap; original instance untouched
    raw = PaginationParams(limit=1000, offset=-1)
    clamped = raw.clamped(max_limit=10)
    assert clamped == PaginationParams(10, 0) and raw.limit == 1000

    # works as a FastAPI dependency end-to-end
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/list")
    def list_route(p: PaginationParams = Depends(pagination_params)):
        return {"limit": p.limit, "offset": p.offset}

    with TestClient(app) as client:
        assert client.get("/list").json() == {"limit": 50, "offset": 0}
        assert client.get("/list?limit=5000&offset=-3").json() == {"limit": 200, "offset": 0}
        assert client.get("/list?limit=7&offset=14").json() == {"limit": 7, "offset": 14}

    print("pagination_params selftest: PASS")


if __name__ == "__main__":
    _selftest()
