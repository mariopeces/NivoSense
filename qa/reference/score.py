"""Q1 scoring of a snow classification against the frozen reference sample.

    python -m qa.reference.score --predictions predictions.csv     Q1 report (JSON); CSV columns id,class
    python -m qa.reference.score --prevalence                      snow share per stratum and draw (Markdown)

The sample comes from several draws with unequal probabilities: draw 1 has equal quotas per
date, stratum and elevation band, and the later draws sample only ground above the date's
snowline. A point's inclusion probability is the chance that any draw, from any stratum the
pixel lies in, picked it: the sum of points / pixels over those draw cells (multi-frame,
Horvitz and Thompson 1952; Hartley 1962). Scores weight every point by its inverse, so they
estimate the rates over all pixels of the domain on the sampled dates, not over the sample.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from . import strata

TRUTH = ("snow", "no_snow", "cloud")
PREDICTED = ("snow", "no_snow", "cloud", "unknown")
SAMPLE_PATH = Path(__file__).with_name("snow_points.geojson")


def inclusion_probabilities(collection: dict) -> dict[str, float]:
    """Inclusion probability of every point, from metadata.cells."""
    metadata = collection["metadata"]
    rates = {
        (cell["draw"], cell["date"], cell["stratum"], cell["elevation_band"]): cell["points"] / cell["pixels"]
        for cell in metadata["cells"]
        if cell["pixels"]
    }
    snowline = {meta["date"]: meta["snowline_m"] for meta in metadata["dates"]}
    above = {int(number): plan["above_snowline_m"] for number, plan in metadata.get("supplements", {}).items()}
    draws = sorted({cell["draw"] for cell in metadata["cells"]})
    probabilities = {}
    for feature in collection["features"]:
        point = feature["properties"]
        probability = 0.0
        for number in draws:
            if number > 1:
                line = snowline[point["date"]]
                if line is None or point["elevation_m"] < line + above[number]:
                    continue
            for name in point["in_strata"]:
                probability += rates.get((number, point["date"], name, point["elevation_band"]), 0.0)
        if probability <= 0:
            raise ValueError(f"{point['id']} lies in no drawn cell")
        probabilities[point["id"]] = probability
    return probabilities


def weights(collection: dict) -> dict[str, float]:
    return {point_id: 1.0 / probability for point_id, probability in inclusion_probabilities(collection).items()}


def scored_points(collection: dict, stratum: str | None = None, draw: int | None = None) -> list[dict]:
    """Points labelled snow, no snow or cloud; with `stratum`, those lying in it (in_strata)."""
    return [
        f["properties"]
        for f in collection["features"]
        if f["properties"]["scored"]
        and (stratum is None or stratum in f["properties"]["in_strata"])
        and (draw is None or f["properties"]["draw"] == draw)
    ]


def confusion(points: list[dict], predicted: dict[str, str], weight: dict[str, float] | None = None) -> dict:
    """Reference class (rows) by predicted class (columns), summed weights or counts."""
    matrix = {truth: dict.fromkeys(PREDICTED, 0.0) for truth in TRUTH}
    for point in points:
        guess = predicted.get(point["id"])
        if guess not in PREDICTED:
            raise ValueError(f"no valid prediction for {point['id']}: {guess!r}")
        matrix[point["label"]][guess] += weight[point["id"]] if weight else 1.0
    return matrix


def snow_f1(matrix: dict) -> dict:
    """Precision, recall and F1 of the snow class; any other prediction counts as not snow."""
    hit = matrix["snow"]["snow"]
    false_alarm = sum(matrix[truth]["snow"] for truth in TRUTH if truth != "snow")
    missed = sum(matrix["snow"][guess] for guess in PREDICTED if guess != "snow")
    precision = hit / (hit + false_alarm) if hit + false_alarm else None
    recall = hit / (hit + missed) if hit + missed else None
    f1 = 2 * hit / (2 * hit + false_alarm + missed) if hit + false_alarm + missed else None
    return {"precision": precision, "recall": recall, "f1": f1}


def _scores(points: list[dict], predicted: dict[str, str], weight: dict[str, float] | None) -> dict:
    matrix = confusion(points, predicted, weight)
    return {"points": len(points), **snow_f1(matrix), "confusion": matrix}


def report(collection: dict, predicted: dict[str, str]) -> dict:
    """Q1 overall and per stratum: design-weighted (the threshold) and unweighted, plus
    unweighted per draw and the share of unsure points left out."""
    weight = weights(collection)
    draws = sorted({f["properties"]["draw"] for f in collection["features"]})
    groups: list[tuple[str, str | None]] = [("overall", None)] + [(name, name) for name in strata.STRATA]
    result = {}
    for key, stratum in groups:
        everything = [
            f["properties"]
            for f in collection["features"]
            if stratum is None or stratum in f["properties"]["in_strata"]
        ]
        points = scored_points(collection, stratum)
        result[key] = {
            "weighted": _scores(points, predicted, weight),
            "unweighted": _scores(points, predicted, None),
            "per_draw_unweighted": {
                str(number): _scores(scored_points(collection, stratum, number), predicted, None) for number in draws
            },
            "unsure_share": round(1 - len(points) / len(everything), 4) if everything else None,
        }
    return result


def prevalence(collection: dict) -> list[dict]:
    """Snow share of the scored points per stratum: unweighted in each draw and pooled, and
    design-weighted pooled. A sound weighting gives the pooled weighted share close to the
    population share that draw 1 alone estimates with its own cell weights."""
    weight = weights(collection)
    draw_one = _single_draw(collection, 1)
    weight_one = weights(draw_one)
    draws = sorted({f["properties"]["draw"] for f in collection["features"]})
    rows = []
    for name in (*strata.STRATA, None):
        points = scored_points(collection, name)
        first = scored_points(draw_one, name)
        row: dict[str, object] = {"stratum": name or "all", "points": len(points)}
        for number in draws:
            members = [p for p in points if p["draw"] == number]
            row[f"draw {number} unweighted"] = _share(members, None)
        row["pooled unweighted"] = _share(points, None)
        row["draw 1 weighted"] = _share(first, weight_one)
        row["pooled weighted"] = _share(points, weight)
        rows.append(row)
    return rows


def _single_draw(collection: dict, number: int) -> dict:
    metadata = {**collection["metadata"], "cells": [c for c in collection["metadata"]["cells"] if c["draw"] == number]}
    features = [f for f in collection["features"] if f["properties"]["draw"] == number]
    return {**collection, "metadata": metadata, "features": features}


def _share(points: list[dict], weight: dict[str, float] | None) -> float | None:
    total = sum(weight[p["id"]] if weight else 1.0 for p in points)
    snow = sum(weight[p["id"]] if weight else 1.0 for p in points if p["label"] == "snow")
    return round(snow / total, 4) if total else None


def read_predictions(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["id"]: row["class"].strip() for row in csv.DictReader(handle)}


def prevalence_table(rows: list[dict]) -> str:
    names = list(dict.fromkeys(name for row in rows for name in row))
    lines = ["| " + " | ".join(names) + " |", "|" + "---|" * len(names)]
    for row in rows:
        cells = [row.get(name) for name in names]
        lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
    return "\n".join(lines)


def _cell(value: object) -> str:
    if value is None:
        return ""
    return f"{value:.1%}" if isinstance(value, float) else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample", type=Path, default=SAMPLE_PATH)
    parser.add_argument("--predictions", type=Path, help="CSV with columns id,class (snow, no_snow, cloud, unknown)")
    parser.add_argument("--prevalence", action="store_true", help="snow share per stratum, weighted and unweighted")
    args = parser.parse_args(argv)
    collection = json.loads(args.sample.read_text(encoding="utf-8"))
    if args.prevalence:
        print(prevalence_table(prevalence(collection)))
        return 0
    if args.predictions is None:
        parser.error("give --predictions or --prevalence")
    print(json.dumps(report(collection, read_predictions(args.predictions)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
