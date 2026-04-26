from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
import json
import shutil
import subprocess

from main import (
    REGION,
    SNOW_NDSI_THRESHOLD,
    get_basins,
    get_observations,
    snow_coverage_for_observation,
)


def season_year(day: date) -> int:
    return day.year + 1 if day.month >= 10 else day.year


def season_start(year: int) -> date:
    return date(year - 1, 10, 1)


def hydro_day(day: date) -> int:
    return (day - season_start(season_year(day))).days


def filter_majority_observations(
    observations: list[dict],
    reference_date: date,
    include_partial_observations: bool,
):
    if include_partial_observations:
        return observations
    return [
        observation
        for observation in observations
        if (observation["date"] - reference_date).days % 5 == 0
    ]


def point_for_observation(observation: dict, geometry: dict, threshold: float):
    stats = snow_coverage_for_observation(observation["url"], geometry, threshold)
    day = observation["date"]
    return {
        "date": day.isoformat(),
        "label": day.strftime("%d %b"),
        "hydro_day": hydro_day(day),
        "season_year": season_year(day),
        "observed": stats["snow_pct"],
        "total_pixels": stats["total_pixels"],
        "valid_pixels": stats["valid_pixels"],
        "masked_pixels": stats["masked_pixels"],
        "data_coverage_pct": stats["data_coverage_pct"],
        "snow_pixels": stats["snow_pixels"],
        "source": observation["path"],
    }


def average_points(points: list[dict], target_year: int, bin_days: int):
    buckets: dict[int, list[float]] = {}
    coverages: dict[int, list[float]] = {}
    for point in points:
        if point["observed"] is None:
            continue
        bucket = point["hydro_day"] // bin_days
        buckets.setdefault(bucket, []).append(point["observed"])
        if point["data_coverage_pct"] is not None:
            coverages.setdefault(bucket, []).append(point["data_coverage_pct"])

    averaged = []
    start = season_start(target_year)
    for bucket in sorted(buckets):
        values = buckets[bucket]
        coverage_values = coverages.get(bucket, [])
        day_offset = bucket * bin_days + bin_days // 2
        label_day = date.fromordinal(start.toordinal() + day_offset)
        averaged.append(
            {
                "label": label_day.strftime("%d %b"),
                "hydro_day": day_offset,
                "average": round(sum(values) / len(values), 2),
                "sample_count": len(values),
                "data_coverage_pct": round(
                    sum(coverage_values) / len(coverage_values), 2
                )
                if coverage_values
                else None,
            }
        )
    return averaged


def build_payload(
    feature: dict,
    year: int,
    threshold: float,
    bin_days: int,
    workers: int,
    max_observations: int | None,
    reference_date: date,
    include_partial_observations: bool,
):
    props = feature["properties"]
    start = season_start(year)
    end = date(year, 9, 30)
    year_observations = [
        obs for obs in get_observations()
        if start <= obs["date"] <= end
    ]
    observations = filter_majority_observations(
        year_observations,
        reference_date,
        include_partial_observations,
    )
    if max_observations:
        observations = observations[:max_observations]
    total = len(observations)
    done = 0
    all_points = []
    print(f"  Processing {total} observations with {workers} workers...")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(point_for_observation, obs, feature["geometry"], threshold): obs
            for obs in observations
        }
        for future in as_completed(futures):
            all_points.append(future.result())
            done += 1
            print(f"  [{done}/{total}] {futures[future]['date']}", flush=True)
    target_points = all_points
    start = season_start(year)
    end = date(year, 9, 30)

    return {
        "basin_id": str(props["cod_uni"]),
        "basin_name": props.get("nom_rio_1"),
        "region": REGION,
        "hydrological_year": f"{year - 1}-{year}",
        "year": year,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "threshold": threshold,
        "observation_filter": "all"
        if include_partial_observations
        else "majority-footprint-5-day-track",
        "reference_date": reference_date.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "points": target_points,
        "average_points": average_points(target_points, year, bin_days),
    }


def upload_file(path: Path, bucket: str, year: int):
    gcloud = shutil.which("gcloud.cmd") or shutil.which("gcloud")
    if not gcloud:
        raise SystemExit("gcloud CLI not found")
    target = (
        f"gs://{bucket}/static/{REGION}/basins/"
        f"{path.parent.name}/series_{year}.json"
    )
    subprocess.run(
        [gcloud, "storage", "cp", str(path), target],
        check=True,
    )


def main():
    parser = ArgumentParser()
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--basin-id")
    parser.add_argument("--bin-days", type=int, default=7)
    parser.add_argument("--threshold", type=float, default=SNOW_NDSI_THRESHOLD)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--max-observations", type=int)
    parser.add_argument("--reference-date", default="2024-01-08")
    parser.add_argument("--include-partial-observations", action="store_true")
    parser.add_argument(
        "--output-dir",
        default="data/generated/static",
    )
    parser.add_argument("--upload-bucket")
    args = parser.parse_args()
    reference_date = date.fromisoformat(args.reference_date)

    features = get_basins().get("features", [])
    if args.basin_id:
        features = [
            feature
            for feature in features
            if str(feature["properties"].get("cod_uni")) == args.basin_id
        ]
    if not features:
        raise SystemExit("No basins matched")

    root = Path(args.output_dir) / REGION / "basins"
    for i, feature in enumerate(features, 1):
        basin_id = str(feature["properties"]["cod_uni"])
        basin_name = feature["properties"].get("nom_rio_1", basin_id)
        print(f"\n[{i}/{len(features)}] Basin {basin_id} — {basin_name}")
        out_dir = root / basin_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"series_{args.year}.json"
        payload = build_payload(
            feature,
            args.year,
            args.threshold,
            args.bin_days,
            args.workers,
            args.max_observations,
            reference_date,
            args.include_partial_observations,
        )
        out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(
            f"{basin_id}: {len(payload['points'])} scenes, "
            f"{len(payload['average_points'])} average bins -> {out_file}"
        )
        if args.upload_bucket:
            upload_file(out_file, args.upload_bucket, args.year)


if __name__ == "__main__":
    main()
