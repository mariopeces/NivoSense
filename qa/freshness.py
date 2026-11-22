"""freshness: the SLOs F1 and F2 of README section 2.

F1: a clear Sentinel-2 pass appears on the site within 24 h of being listed on Earth Search.
  - Latency: for every snow_obs and rgb entry in the window, its created_at minus the latest Earth Search
    `created` time of its source scenes; over 24 h is a breach.
  - Missing: every Earth Search pass (UTC date and relative orbit) over the region listed more than 24 h ago
    whose date has no snow_obs entry is missing, unless the observation pipeline recorded a decision object
    `s2/decisions/<date>_<orbit>.json` (schema pipelines/catalog/s2_decision.schema.json) saying the pass is
    complete and not listed (under 30% of the domain covered and valid).
F2: the daily layers for yesterday (Europe/Madrid) exist, created by 10:00 Europe/Madrid today.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.request
from collections import defaultdict
from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo

from pipelines.catalog import Storage
from pipelines.catalog.validate import validate_s2_decision

from .objects import index_entries

STAC_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
L2A = "sentinel-2-c1-l2a"
L1C = "sentinel-2-l1c"
F1_LIMIT = dt.timedelta(hours=24)
F1_LATENCY_LAYERS = ("snow_obs", "rgb")
F1_PASS_LAYER = "snow_obs"
F2_LAYERS = ("snow_gapfill", "swe", "snow_depth")
F2_DEADLINE = dt.time(10, 0)
MADRID = ZoneInfo("Europe/Madrid")
# Earth Search c1 items carry no sat:relative_orbit; it is in the ESA product name (..._R094_T30SVG_...).
_ORBIT = re.compile(r"_R(\d{3})_")

Search = Callable[[dict[str, Any]], list[dict[str, Any]]]


def earth_search(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Every item of a STAC search on Earth Search, following POST `next` links."""
    url, items = STAC_SEARCH_URL, []
    payload: dict[str, Any] | None = dict(body, limit=100)
    while payload is not None:
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            page = json.load(response)
        items.extend(page["features"])
        link = next((link for link in page.get("links", []) if link["rel"] == "next"), None)
        url, payload = (link["href"], link["body"]) if link and link.get("method") == "POST" else (url, None)
    return items


def _time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def orbit_of(item: dict[str, Any]) -> str:
    match = _ORBIT.search(item["properties"].get("s2:product_uri", ""))
    if match is None:
        raise ValueError(f"No relative orbit in the product name of {item['id']}")
    return f"R{match.group(1)}"


def check_f1(
    storage: Storage,
    entries: dict[str, list[dict[str, Any]]],
    bbox: tuple[float, float, float, float],
    now: dt.datetime,
    lookback_days: int,
    search: Search,
) -> dict[str, Any]:
    start = (now - dt.timedelta(days=lookback_days)).date()
    breaches: list[dict[str, Any]] = []

    recent = [
        entry
        for layer in F1_LATENCY_LAYERS
        for entry in entries.get(layer, [])
        if dt.date.fromisoformat(entry["date"]) >= start
    ]
    source_ids = sorted({source for entry in recent for source in entry["source_ids"]})
    listed_at: dict[str, dt.datetime] = {}
    for chunk in (source_ids[i : i + 100] for i in range(0, len(source_ids), 100)):
        for item in search({"collections": [L2A, L1C], "ids": chunk}):
            listed_at[item["id"]] = _time(item["properties"]["created"])
    latencies = []
    for entry in recent:
        times = [listed_at.get(source) for source in entry["source_ids"]]
        if any(t is None for t in times):
            unknown = [s for s, t in zip(entry["source_ids"], times) if t is None]
            breaches.append(
                {"layer": entry["layer"], "date": entry["date"], "why": f"source not on Earth Search: {unknown}"}
            )
            continue
        latency = _time(entry["created_at"]) - max(t for t in times if t is not None)
        hours = round(latency.total_seconds() / 3600, 2)
        latencies.append({"layer": entry["layer"], "date": entry["date"], "latency_h": hours})
        if latency > F1_LIMIT:
            breaches.append(
                {"layer": entry["layer"], "date": entry["date"], "why": f"published {hours} h after listing"}
            )

    items = search(
        {
            "collections": [L2A],
            "bbox": list(bbox),
            "datetime": f"{start.isoformat()}T00:00:00Z/{now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        }
    )
    passes: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        passes[(item["properties"]["datetime"][:10], orbit_of(item))].append(item)
    published = {entry["date"] for entry in entries.get(F1_PASS_LAYER, [])}
    rows = []
    for (date, orbit), group in sorted(passes.items()):
        listed = max(_time(item["properties"]["created"]) for item in group)
        row: dict[str, Any] = {
            "date": date,
            "orbit": orbit,
            "scenes": sorted(item["id"] for item in group),
            "listed_at": listed.isoformat(timespec="seconds"),
        }
        if date in published:
            row["state"] = "published"
        elif now - listed <= F1_LIMIT:
            row["state"] = "not_due"
        else:
            decision = _decision(storage, date, orbit)
            if decision is not None and decision["complete"] and not decision["listed"]:
                row["state"] = "not_clear"
                row["domain_coverage"] = decision["domain_coverage"]
                row["domain_valid_fraction"] = decision["domain_valid_fraction"]
            else:
                row["state"] = "missing"
                why = "no decision recorded" if decision is None else "decision says listed or incomplete"
                breaches.append({"layer": F1_PASS_LAYER, "date": date, "orbit": orbit, "why": f"missing: {why}"})
        rows.append(row)
    return {
        "ok": not breaches,
        "window_start": start.isoformat(),
        "latencies": latencies,
        "passes": rows,
        "breaches": breaches,
    }


def _decision(storage: Storage, date: str, orbit: str) -> dict[str, Any] | None:
    blob = storage.read(f"s2/decisions/{date}_{orbit}.json")
    if blob is None:
        return None
    decision: dict[str, Any] = json.loads(blob.data)
    validate_s2_decision(decision)
    return decision


def check_f2(entries: dict[str, list[dict[str, Any]]], now: dt.datetime) -> dict[str, Any]:
    local_now = now.astimezone(MADRID)
    yesterday = (local_now.date() - dt.timedelta(days=1)).isoformat()
    deadline = dt.datetime.combine(local_now.date(), F2_DEADLINE, tzinfo=MADRID)
    due = local_now >= deadline
    layers, breaches = {}, []
    for layer in F2_LAYERS:
        entry = next((e for e in entries.get(layer, []) if e["date"] == yesterday), None)
        if entry is None:
            state = "missing" if due else "not_due"
        else:
            created = _time(entry["created_at"])
            state = "late" if created > deadline else "on_time"
            layers[layer] = {"state": state, "created_at": created.astimezone(MADRID).isoformat(timespec="seconds")}
        layers.setdefault(layer, {"state": state})
        if state in ("missing", "late"):
            breaches.append({"layer": layer, "date": yesterday, "why": state})
    return {
        "ok": not breaches,
        "date": yesterday,
        "deadline": deadline.isoformat(timespec="minutes"),
        "layers": layers,
        "breaches": breaches,
    }


def freshness(
    storage: Storage,
    bbox: tuple[float, float, float, float],
    now: dt.datetime | None = None,
    lookback_days: int = 10,
    search: Search = earth_search,
) -> dict[str, Any]:
    """The F1 and F2 report for the catalogue at `now` (UTC, default the current time)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    entries = index_entries(storage)
    f1 = check_f1(storage, entries, bbox, now, lookback_days, search)
    f2 = check_f2(entries, now)
    return {
        "check": "freshness",
        "catalogue": repr(storage),
        "now": now.isoformat(timespec="seconds"),
        "bbox": list(bbox),
        "f1": f1,
        "f2": f2,
        "ok": f1["ok"] and f2["ok"],
    }
