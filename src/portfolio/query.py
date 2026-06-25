import json
from . import config

def query(filters: dict, json_text: str | None = None) -> list[dict]:
    if json_text is None:
        path = config.json_path()
        if not path.exists():
            return []
        json_text = path.read_text()
    data = json.loads(json_text)
    def keep(p):
        if "tier" in filters and p.get("tier") != filters["tier"]: return False
        if "status" in filters and p.get("status") != filters["status"]: return False
        if "stale" in filters and bool(p.get("stale")) != bool(filters["stale"]): return False
        if "has_backlog" in filters and (p.get("open_backlog", 0) > 0) != bool(filters["has_backlog"]): return False
        if "tag" in filters and filters["tag"].lower() not in (p.get("purpose") or "").lower(): return False
        return True
    return [p for p in data.get("projects", []) if keep(p)]
