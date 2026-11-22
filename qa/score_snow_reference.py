"""Scores observed snow cover against the frozen reference sample (README section 2, Q1).

    python -m qa.score_snow_reference --snow-obs work/snow_obs --out report.json \
        [--reference qa/reference/snow_points.geojson]

Reads <snow-obs>/<date>/snow_obs.tif (band 1 classes, as written by pipelines.snow_obs.run) at each
scored reference point. Every scored point counts: a point labelled snow that the product calls
cloud or unknown is a missed snow point, and a point labelled cloud that the product calls snow
is a false snow point. Snow F1 = 2 TP / (2 TP + FP + FN). Unsure points are left out, as the
sample says. Strata are the draw strata (`stratum`), as the sample is stratified on them; the
same scores over every stratum a point falls in (`in_strata`) are reported beside them. Point
counts are not weighted by draw: the second draw oversamples snow-prone ground.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from pipelines.snow_obs import classify as c

REFERENCE = Path(__file__).resolve().parent / "reference" / "snow_points.geojson"
PREDICTED = {c.NO_SNOW: "no_snow", c.SNOW: "snow", c.CLOUD: "cloud", c.UNKNOWN: "unknown", c.NODATA: "nodata"}
LABELS = ("snow", "no_snow", "cloud")
# README section 2, Q1.
MIN_F1_OVERALL = 0.85
MIN_F1_STRATUM = 0.70


def sample(snow_obs: Path, points: list[dict[str, Any]]) -> list[str]:
    """The product class at each point, read from the file of the point's date."""
    import rasterio

    by_date: dict[str, list[int]] = defaultdict(list)
    for index, point in enumerate(points):
        by_date[point["date"]].append(index)
    predicted = [""] * len(points)
    for day, indices in sorted(by_date.items()):
        path = snow_obs / day / "snow_obs.tif"
        if not path.exists():
            raise FileNotFoundError(f"no snow_obs product for {day} at {path}")
        with rasterio.open(path) as src:
            classes = src.read(1)
            for index in indices:
                row, col = src.index(points[index]["x"], points[index]["y"])
                inside = 0 <= row < src.height and 0 <= col < src.width
                predicted[index] = PREDICTED[int(classes[row, col])] if inside else "nodata"
    return predicted


def scores(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """Confusion matrix (reference label x product class) and snow precision, recall and F1."""
    matrix = {label: {name: 0 for name in PREDICTED.values()} for label in LABELS}
    for label, predicted in pairs:
        matrix[label][predicted] += 1
    tp = matrix["snow"]["snow"]
    fp = matrix["no_snow"]["snow"] + matrix["cloud"]["snow"]
    fn = sum(matrix["snow"].values()) - tp
    observed = [(label, p) for label, p in pairs if label != "cloud" and p in ("snow", "no_snow")]
    clear = [p for label, p in pairs if label != "cloud"]
    return {
        "points": len(pairs),
        "matrix": matrix,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "f1": round(2 * tp / (2 * tp + fp + fn), 4) if tp + fp + fn else None,
        "f1_where_observed": _f1(observed),
        "clear_points_observed": round(len(observed) / len(clear), 4) if clear else None,
    }


def _f1(pairs: list[tuple[str, str]]) -> float | None:
    tp = sum(1 for label, p in pairs if label == "snow" and p == "snow")
    fp = sum(1 for label, p in pairs if label != "snow" and p == "snow")
    fn = sum(1 for label, p in pairs if label == "snow" and p != "snow")
    return round(2 * tp / (2 * tp + fp + fn), 4) if tp + fp + fn else None


def report(points: list[dict[str, Any]], predicted: list[str]) -> dict[str, Any]:
    pairs = [(p["label"], q) for p, q in zip(points, predicted)]
    groups: dict[str, dict[str, list[tuple[str, str]]]] = {
        "by_stratum": defaultdict(list),
        "by_in_strata": defaultdict(list),
        "by_date": defaultdict(list),
        "by_stratum_and_date": defaultdict(list),
    }
    for point, pair in zip(points, pairs):
        groups["by_stratum"][point["stratum"]].append(pair)
        for stratum in point["in_strata"]:
            groups["by_in_strata"][stratum].append(pair)
        groups["by_date"][point["date"]].append(pair)
        groups["by_stratum_and_date"][f"{point['stratum']} {point['date']}"].append(pair)
    overall = scores(pairs)
    by_stratum = {name: scores(group) for name, group in sorted(groups["by_stratum"].items())}
    failures = []
    if overall["f1"] is None or overall["f1"] < MIN_F1_OVERALL:
        failures.append(f"overall snow F1 {overall['f1']} < {MIN_F1_OVERALL}")
    for name, result in by_stratum.items():
        if result["f1"] is None or result["f1"] < MIN_F1_STRATUM:
            failures.append(f"{name} snow F1 {result['f1']} < {MIN_F1_STRATUM}")
    return {
        "check": "q1_snow_reference",
        "thresholds": {"overall_f1": MIN_F1_OVERALL, "stratum_f1": MIN_F1_STRATUM},
        "overall": overall,
        "by_stratum": by_stratum,
        **{
            key: {name: scores(group) for name, group in sorted(groups[key].items())}
            for key in ("by_in_strata", "by_date", "by_stratum_and_date")
        },
        "failures": failures,
        "ok": not failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snow-obs", type=Path, required=True, help="output folder of pipelines.snow_obs.run")
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    collection = json.loads(args.reference.read_text(encoding="utf-8"))
    points = [feature["properties"] for feature in collection["features"] if feature["properties"]["scored"]]
    result = report(points, sample(args.snow_obs, points))
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    overall = result["overall"]
    print(f"overall F1 {overall['f1']} (P {overall['precision']}, R {overall['recall']}, n {overall['points']})")
    for name, stratum in result["by_stratum"].items():
        print(f"  {name}: F1 {stratum['f1']} (P {stratum['precision']}, R {stratum['recall']}, n {stratum['points']})")
    for failure in result["failures"]:
        print(f"FAIL {failure}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
