"""freshness: the SLOs F1 and F2 of README section 2.

F1: a clear Sentinel-2 pass appears on the site within 24 h of being listed on Earth Search.
  - Latency: for every snow_obs and rgb entry in the window, its created_at minus the latest Earth Search
    `created` time of its source scenes; over 24 h is a breach.
  - Missing: every Earth Search pass (UTC date and relative orbit) over the region listed more than 24 h ago
    whose date has no snow_obs entry is missing, unless the observation pipeline recorded a decision object
    `s2/decisions/<date>_<orbit>.json` (schema pipelines/catalog/s2_decision.schema.json) for that same date and
    orbit saying the pass is complete and not listed, with under 30% of the domain covered and valid. A decision
    that contradicts its key or the 30% rule is reported, never taken as an explanation. A decision holds only for
    the scenes it names: when Earth Search lists a scene of the pass that is not in its scene_ids, or the pass's
    last scene was listed after decided_at (a late tile or a reprocessing), the pass is missing again until a new
    decision or an entry covers it.
  - A pass date with a snow_obs entry must also have its rgb entry (README D1 lists both).
F2: the daily layers for yesterday (Europe/Madrid) exist, created by 10:00 Europe/Madrid today.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo

from jsonschema import ValidationError

from pipelines.catalog import Storage
from pipelines.catalog.validate import validate_s2_decision

from .objects import index_entries

STAC_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
L2A = "sentinel-2-c1-l2a"
L1C = "sentinel-2-l1c"
F1_LIMIT = dt.timedelta(hours=24)
F1_LATENCY_LAYERS = ("snow_obs", "rgb")
F1_PASS_LAYER = "snow_obs"
F1_RGB_LAYER = "rgb"
# README D1: an S2 date is listed when at least 30% of the domain is covered and valid.
MIN_LISTED_VALID_FRACTION = 0.30
# SWE left the daily layers when v2 replaced v1 (docs/snow-evaluation.md): nothing validates it, so it is not published.
F2_LAYERS = ("snow_gapfill", "snow_depth")
# The daily layers (README section 1) and the first day each must exist from. A layer's producing task sets its
# date to 2025-10-01 (README D1) when its backfill lands (T1.4 gap-fill, T2.5 SWE and depth). Until then a layer
# with entries is checked from its first one, and one with none is not live: check_catalog does not count its
# days and F2 does not count it as a breach.
DAILY_SINCE: dict[str, str | None] = {"snow_gapfill": None, "snow_depth": None}
F2_DEADLINE = dt.time(10, 0)
MADRID = ZoneInfo("Europe/Madrid")
# Earth Search c1 items carry no sat:relative_orbit; it is in the ESA product name (..._R094_T30SVG_...).
_ORBIT = re.compile(r"_R(\d{3})_")

Search = Callable[[dict[str, Any]], list[dict[str, Any]]]
SEARCH_ATTEMPTS = 4
SEARCH_BACKOFF_S = 5.0


def _post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """One STAC search page, retried with backoff on network errors, 429 and 5xx."""
    for attempt in range(SEARCH_ATTEMPTS):
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                page: dict[str, Any] = json.load(response)
                return page
        except urllib.error.HTTPError as error:
            if error.code != 429 and error.code < 500 or attempt == SEARCH_ATTEMPTS - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == SEARCH_ATTEMPTS - 1:
                raise
        time.sleep(SEARCH_BACKOFF_S * 2**attempt)
    raise AssertionError("unreachable")


def earth_search(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Every item of a STAC search on Earth Search, following POST `next` links."""
    url, items = STAC_SEARCH_URL, []
    payload: dict[str, Any] | None = dict(body, limit=100)
    while payload is not None:
        page = _post(url, payload)
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
    published_rgb = {entry["date"] for entry in entries.get(F1_RGB_LAYER, [])}
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
            if date not in published_rgb and now - listed > F1_LIMIT:
                row["state"] = "published_without_rgb"
                breaches.append({"layer": F1_RGB_LAYER, "date": date, "orbit": orbit, "why": "missing: no rgb entry"})
        elif now - listed <= F1_LIMIT:
            row["state"] = "not_due"
        else:
            decision, problem = _decision(storage, date, orbit, row["scenes"], listed)
            if problem is None and decision is not None:
                row["state"] = "not_clear"
                row["domain_coverage"] = decision["domain_coverage"]
                row["domain_valid_fraction"] = decision["domain_valid_fraction"]
            else:
                row["state"] = "missing"
                breaches.append({"layer": F1_PASS_LAYER, "date": date, "orbit": orbit, "why": f"missing: {problem}"})
        rows.append(row)
    return {
        "ok": not breaches,
        "window_start": start.isoformat(),
        "latencies": latencies,
        "passes": rows,
        "breaches": breaches,
    }


def _decision(
    storage: Storage, date: str, orbit: str, scenes: list[str], listed: dt.datetime
) -> tuple[dict[str, Any] | None, str | None]:
    """The decision object of a pass and, when it does not explain the pass as not clear, why not.

    `scenes` are the pass's scenes on Earth Search now and `listed` the latest of their `created` times.
    """
    key = f"s2/decisions/{date}_{orbit}.json"
    blob = storage.read(key)
    if blob is None:
        return None, "no decision recorded"
    try:
        decision: dict[str, Any] = json.loads(blob.data)
        validate_s2_decision(decision)
    except (ValueError, ValidationError) as error:  # unparsable JSON or a schema violation
        return None, f"invalid decision {key}: {str(error).splitlines()[0]}"
    if (decision["date"], decision["orbit"]) != (date, orbit):
        return decision, f"decision {key} is for {decision['date']} {decision['orbit']}"
    uncovered = sorted(set(scenes) - set(decision["scene_ids"]))
    if uncovered:
        return decision, f"stale decision: Earth Search now lists {uncovered}, not in its scene_ids"
    if _time(decision["decided_at"]) < listed:
        decided = _time(decision["decided_at"]).isoformat(timespec="seconds")
        return decision, f"stale decision: decided at {decided}, before the last scene was listed"
    if not decision["complete"]:
        return decision, "decision says the pass is incomplete"
    if decision["listed"]:
        return decision, "decision says listed"
    valid, coverage = decision["domain_valid_fraction"], decision["domain_coverage"]
    if valid > coverage:
        return decision, f"decision contradicts itself: valid fraction {valid} above coverage {coverage}"
    if valid >= MIN_LISTED_VALID_FRACTION:
        return (
            decision,
            f"decision says not listed with {valid} of the domain valid (at least {MIN_LISTED_VALID_FRACTION})",
        )
    return decision, None


def check_f2(entries: dict[str, list[dict[str, Any]]], now: dt.datetime) -> dict[str, Any]:
    local_now = now.astimezone(MADRID)
    yesterday = (local_now.date() - dt.timedelta(days=1)).isoformat()
    deadline = dt.datetime.combine(local_now.date(), F2_DEADLINE, tzinfo=MADRID)
    due = local_now >= deadline
    layers, breaches = {}, []
    for layer in F2_LAYERS:
        entry = next((e for e in entries.get(layer, []) if e["date"] == yesterday), None)
        if not entries.get(layer) and DAILY_SINCE.get(layer) is None:
            state = "not_live"
        elif entry is None:
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
    try:
        f1 = check_f1(storage, entries, bbox, now, lookback_days, search)
    except (OSError, ValueError) as error:  # Earth Search unreachable after retries, or a bad response
        # F1 cannot be judged: it fails, and the run still writes its report.
        f1 = {"ok": False, "error": f"Earth Search: {type(error).__name__} {error}", "breaches": []}
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
