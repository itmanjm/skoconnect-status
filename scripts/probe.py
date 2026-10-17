#!/usr/bin/env python3
"""SkoConnect status page probe.

Probes each surface, then updates data/status.json and the daily aggregate
in data/history.json. Designed to run from GitHub Actions every 15 minutes
and locally for seeding.

Up/down rule: curl-style semantics — any HTTP response means the surface is
reachable (up); network-level failure (DNS, timeout, refused, TLS) = down.
For the API we additionally require HTTP 200 and status:"ok" in the body.
"""
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

JAMAICA_TZ = "America/Jamaica"

COMPONENTS = [
    {
        "id": "marketing",
        "name": "Marketing site",
        "description": "skoconnect.com public website",
        "url": "https://skoconnect.com/",
        "kind": "http",  # any HTTP response = up
    },
    {
        "id": "admin",
        "name": "Admin portal",
        "description": "School administrator web app (admin.skoconnect.com)",
        "url": "https://admin.skoconnect.com/",
        "kind": "http",
    },
    {
        "id": "api",
        "name": "App & API",
        "description": "Mobile app backend / Cloud Functions (health endpoint incl. Firestore round-trip)",
        "url": "https://us-central1-school-connect-enterprise.cloudfunctions.net/health",
        "kind": "health",  # HTTP 200 + status:"ok" required
    },
    {
        "id": "ingestion",
        "name": "Document ingestion pipeline",
        "description": "Cloud Run ingestion service (responding = up; root returns 405 by design)",
        "url": "https://document-ingestion-pltacimgka-uc.a.run.app/",
        "kind": "http",
    },
]

TIMEOUT_SEC = 30
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HISTORY_DAYS = 90


def probe(comp: dict) -> dict:
    """Return {up: bool, http_code: int|0, detail: str}.

    Two attempts: Cloud Run scale-to-zero services can cold-start past the
    timeout on the first hit; the immediate retry hits a warm instance and
    measures real availability rather than startup latency.
    """
    req = urllib.request.Request(comp["url"], method="GET",
                                  headers={"User-Agent": "skoconnect-status-probe/1.0"})
    last = None
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                code = resp.status
                body = resp.read(4096).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            # Got an HTTP response -> surface reachable (e.g. ingestion 405)
            code = e.code
            body = ""
        except Exception as e:  # noqa: BLE001 - network-level failure of any kind
            last = f"{type(e).__name__}: {e}"
            continue
        if comp["kind"] == "health":
            ok = code == 200 and '"status":"ok"' in body.replace(" ", "")
            return {"up": ok, "http_code": code,
                    "detail": "healthy" if ok else f"unexpected response (HTTP {code})"}
        return {"up": True, "http_code": code, "detail": f"HTTP {code}"}
    return {"up": False, "http_code": 0, "detail": f"unreachable after 2 attempts ({last})"}


def now_jamaica_iso() -> str:
    return datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=-5))).isoformat(timespec="seconds")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    status_path = DATA_DIR / "status.json"
    history_path = DATA_DIR / "history.json"

    prev_status = {}
    if status_path.exists():
        try:
            prev_status = {c["id"]: c for c in json.loads(status_path.read_text()).get("components", [])}
        except (json.JSONDecodeError, KeyError):
            prev_status = {}

    components_out = []
    for comp in COMPONENTS:
        result = probe(comp)
        prev = prev_status.get(comp["id"], {})
        entry = {
            "id": comp["id"],
            "name": comp["name"],
            "description": comp["description"],
            "url": comp["url"],
            "up": result["up"],
            "http_code": result["http_code"],
            "detail": result["detail"],
            "checked_at": now_jamaica_iso(),
            "down_since": (prev.get("down_since") if not result["up"] and prev.get("up") is False
                           else None if result["up"] else prev.get("down_since") or now_jamaica_iso()),
        }
        components_out.append(entry)

    all_up = all(c["up"] for c in components_out)
    status_out = {
        "overall": "operational" if all_up else "outage",
        "updated_at": now_jamaica_iso(),
        "timezone": JAMAICA_TZ,
        "components": components_out,
    }
    status_path.write_text(json.dumps(status_out, indent=2) + "\n")

    # Daily aggregate per component: {date, up, total} — one row per component per day.
    today = status_out["updated_at"][:10]
    history = {"days": []}
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text())
        except json.JSONDecodeError:
            history = {"days": []}
    days = history.get("days", [])
    for entry in components_out:
        row = next((d for d in days if d["date"] == today and d["component"] == entry["id"]), None)
        if row is None:
            days.append({"date": today, "component": entry["id"],
                         "up": 1 if entry["up"] else 0, "total": 1})
        else:
            row["total"] += 1
            if entry["up"]:
                row["up"] += 1
    # Trim to HISTORY_DAYS per component by date
    cutoff = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
    days = [d for d in days if d["date"] >= cutoff]
    days.sort(key=lambda d: (d["date"], d["component"]))
    history_path.write_text(json.dumps({"days": days}, indent=2) + "\n")

    print(json.dumps({"overall": status_out["overall"],
                      "components": {c["id"]: f"{'UP' if c['up'] else 'DOWN'} ({c['detail']})"
                                     for c in components_out}}, indent=2))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"## Probe result: {status_out['overall']}\n\n")
            for c in components_out:
                f.write(f"- {'✅' if c['up'] else '❌'} **{c['name']}** — {c['detail']}\n")
    # NOTE: exits 0 even on outage — the data commit IS the deliverable; a
    # nonzero exit here would abort the workflow before data is committed and
    # freeze the public page on stale all-green data (observed Oct 10-17).


if __name__ == "__main__":
    main()
