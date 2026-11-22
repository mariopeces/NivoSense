"""Score a snow product against a reference and write a markdown report.

    python -m qa.validation.report --product catalogue:snow_depth --fold 2013
    python -m qa.validation.report --product my_run.csv --fold 2012 --reference poqueira
    python -m qa.validation.report --product run.csv --reference-csv erhin_pole.csv --variable snow_depth
    python -m qa.validation.report --product catalogue:swe --fold 2026 --s2-presence

--product is a CSV (date, value, lat, lon; optional quantile columns q10, q50, q90 or a member column) or
`catalogue:swe` / `catalogue:snow_depth`, the v1 layers of the prod bucket sampled at the reference points.
--reference is the Refugio Poqueira camera (default) or, with --reference-csv, a table of the same format.
--fold is a water year (2013 is 2012-10-01 to 2013-09-30) or `all`. Reports go to qa-reports/ (gitignored)
and the headline numbers are printed. Units of product and reference must match.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import baselines, folds, metrics, pangaea, presence, products

REPORT_DIR = Path("qa-reports")
SNOW_THRESHOLD = {"snow_depth": metrics.DEPTH_SNOW_M, "swe": 5.0, "snow_cover_fraction": metrics.FSCA_SNOW}

CAMERA_LIMITS = """\
- It is one 30 x 30 m plot at 2,510 m (37.02825 N, -3.32337 E), 2009-11-15 to 2013-05-31. It gives snow depth and snow
  cover fraction, not SWE, and says nothing about the current seasons or about any other place.
- A 100 m model cell is compared with a 900 m2 plot: part of any error is representativeness, not model error.
- Source: PANGAEA 871706, Pimentel, Herrero and Polo (2017), CC-BY-3.0, doi:10.1594/PANGAEA.871706."""

GENERIC_LIMITS = """\
- The reference is a user-supplied table. What it can validate is set by what it measures and where: a point
  measurement checks that point, and a depth is not an SWE."""

GUADALFEO_NOTE = """\
Guadalfeo stations (PANGAEA 895236, CC-BY-4.0) give daily precipitation and temperature to 2018-08-31. They
can check the forcing of a model run, not snow, and they are not used in this report."""


def md_table(frame: pd.DataFrame, digits: int = 3) -> str:
    if frame.empty:
        return "(no rows)"

    def cell(value: object) -> str:
        if isinstance(value, (float, np.floating)):
            return "n/a" if not np.isfinite(value) else f"{value:.{digits}f}"
        return str(value)

    lines = ["| " + " | ".join(map(str, frame.columns)) + " |", "|" + "---|" * len(frame.columns)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join(lines)


def load_reference(args: argparse.Namespace) -> tuple[pd.DataFrame, str, str]:
    """The reference rows (date, value, lat, lon) of the variable, its name and the limits text."""
    if args.reference_csv:
        frame = products.read_table(Path(args.reference_csv))
        if "variable" in frame.columns:
            frame = frame[frame["variable"] == args.variable]
        return frame[["date", "value", "lat", "lon"]].dropna(subset=["value"]), str(args.reference_csv), GENERIC_LIMITS
    tidy = pangaea.load_poqueira()
    keep = tidy[(tidy["variable"] == args.variable) & (tidy["qc"] == "ok")]
    if keep.empty:
        raise SystemExit(f"The camera has no variable {args.variable!r}; use snow_depth or snow_cover_fraction")
    return keep[["date", "value", "lat", "lon"]], "Refugio Poqueira camera (PANGAEA 871706)", CAMERA_LIMITS


def load_product(
    args: argparse.Namespace, reference: pd.DataFrame, days: list[date]
) -> tuple[pd.DataFrame, dict[str, int]]:
    spec = str(args.product)
    if spec.startswith(products.CATALOGUE_PREFIX):
        layer = spec.removeprefix(products.CATALOGUE_PREFIX)
        if layer not in baselines.LAYER_VARIABLE:
            raise SystemExit(f"Unknown catalogue layer {layer!r}; use one of {sorted(baselines.LAYER_VARIABLE)}")
        return baselines.sample_catalogue(baselines.HttpStorage(), layer, products.locations(reference), days)
    frame = products.read_table(Path(spec))
    if "variable" in frame.columns:
        frame = frame[frame["variable"] == args.variable]
    return products.reduce_members(frame), {}


def season_table(pairs: pd.DataFrame, threshold: float) -> pd.DataFrame:
    rows = []
    for wy in folds.seasons_of(pairs["date"]):
        part = folds.in_season(pairs, wy)
        ref = metrics.melt_out_date(part["date"], part["ref"], threshold)
        sim = metrics.melt_out_date(part["date"], part["sim"], threshold)
        rows.append(
            {
                "water_year": wy,
                "ref_melt_out": ref.date if ref else "none",
                "ref_interval_days": (ref.date - ref.last_snow).days if ref else np.nan,
                "model_melt_out": sim.date if sim else "none",
                "error_days": metrics.melt_out_error_days(sim, ref),
            }
        )
    return pd.DataFrame(rows)


def plot_series(pairs: pd.DataFrame, path: Path, title: str) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.plot(pairs["date"], pairs["ref"], ".", label="reference", color="black", markersize=3)
    ax.plot(pairs["date"], pairs["sim"], "-", label="product", color="tab:blue", linewidth=1)
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return True


def build(args: argparse.Namespace) -> tuple[str, dict[str, object]]:
    reference, reference_name, limits = load_reference(args)
    fold_label = "all seasons"
    if args.fold != "all":
        wy = int(args.fold)
        reference = folds.in_season(reference, wy)
        fold_label = f"water year {wy} ({folds.water_year_bounds(wy)[0]} to {folds.water_year_bounds(wy)[1]})"
    days = sorted({d.date() for d in reference["date"]})
    headline: dict[str, object] = {"fold": fold_label, "reference_days": len(days)}
    out = [
        f"# Validation report: {args.product}",
        "",
        f"- Fold: {fold_label}",
        f"- Reference: {reference_name}, variable `{args.variable}`, {len(days)} days in the fold",
        "",
        "## What this reference can and cannot validate",
        "",
        limits,
        "",
        GUADALFEO_NOTE,
        "",
    ]
    stats: dict[str, int] = {}
    if len(days) == 0:
        out += ["## Result", "", "No reference days in this fold; nothing is scored."]
    else:
        product, stats = load_product(args, reference, days)
        pairs = products.match(product, reference) if len(product) else pd.DataFrame()
        headline["paired_days"] = len(pairs)
        out += ["## Overlap", "", f"- Product rows: {len(product)}; paired with the reference: {len(pairs)}"]
        for key, label in (
            ("no_entry_days", "reference days with no catalogue entry (not run, or no visible snow; skipped)"),
            ("outside_raster_points", "points outside the raster"),
        ):
            if stats.get(key):
                out.append(f"- {stats[key]} {label}")
        if pairs.empty:
            out += [
                "",
                "## Result",
                "",
                "The product and the reference share no dates here, so nothing is scored. This is the",
                "expected outcome for the v1 catalogue against the 2009 to 2013 camera: v1 starts in 2024-10.",
            ]
        else:
            out += _scores(pairs, args, headline)
            plot = REPORT_DIR / f"{args.name}.png"
            if plot_series(pairs, plot, f"{args.product} vs reference, {fold_label}"):
                out += ["", f"![series]({plot.name})"]
            else:
                out += ["", "No plot: matplotlib is not in the locked dependencies."]
    if args.s2_presence:
        out += _s2_section(args, headline)
    return "\n".join(out) + "\n", headline


def _scores(pairs: pd.DataFrame, args: argparse.Namespace, headline: dict[str, object]) -> list[str]:
    threshold = SNOW_THRESHOLD.get(args.variable, metrics.DEPTH_SNOW_M)
    both = metrics.depth_metrics(pairs["sim"], pairs["ref"])
    snow_days = pairs[(pairs["ref"] > threshold) | (pairs["sim"] > threshold)]
    snowy = metrics.depth_metrics(snow_days["sim"], snow_days["ref"])
    table = pd.DataFrame([{"subset": "all paired days", **both}, {"subset": "days with snow in either", **snowy}])
    presence_scores = metrics.confusion(pairs["sim"] > threshold, pairs["ref"] > threshold)
    out = [
        "",
        "## Time series scores (model minus reference)",
        "",
        md_table(table),
        "",
        f"## Snow presence at the reference point (value above {threshold:g})",
        "",
        md_table(pd.DataFrame([presence_scores])),
        "",
        "## Melt-out date per season",
        "",
        f"Rule: the first sample after the last one above {threshold:g}, "
        f"only if at least {metrics.MIN_BARE_TAIL_DAYS} bare days follow.",
        "",
        md_table(season_table(pairs, threshold)),
    ]
    headline.update(
        {f"{k}": round(v, 4) for k, v in both.items() if k != "n"} | {"n": int(both["n"]), "f1": presence_scores["f1"]}
    )
    members = products.member_columns(pairs)
    quantiles = products.quantile_columns(pairs)
    ensemble = None
    if members:
        ensemble = metrics.ensemble_summary(pairs[members].to_numpy().T, pairs["ref"])
    elif quantiles:
        ensemble = metrics.quantile_summary(list(quantiles), pairs[list(quantiles.values())].to_numpy(), pairs["ref"])
    if ensemble:
        out += [
            "",
            "## Ensemble quality",
            "",
            md_table(pd.DataFrame([ensemble])),
            "",
            "Targets: coverage80 between 0.70 and 0.90, spread_skill between 0.8 and 1.2.",
        ]
        headline.update(ensemble)
    return out


def _s2_section(args: argparse.Namespace, headline: dict[str, object]) -> list[str]:
    spec = str(args.product)
    if spec != "catalogue:swe":
        return ["", "## Snow presence against Sentinel-2", "", "Only available for `--product catalogue:swe`."]
    storage = baselines.HttpStorage()
    days = presence.obs_dates(storage)
    if args.fold != "all":
        start, end = folds.water_year_bounds(int(args.fold))
        days = [d for d in days if start <= d <= end]
    out = ["", "## Snow presence against Sentinel-2 (catalogue snow_obs, ski resort excluded)", ""]
    if not days:
        return out + ["No Sentinel-2 snow mask dates in this fold."]
    result = presence.score_swe_presence(storage, days)
    per_date = result.per_date
    skipped = result.skipped
    out.append(
        f"{len(skipped)} of {len(days)} Sentinel-2 dates have no v1 entry (not run, or no visible snow); skipped."
    )
    if per_date.empty:
        return out
    out += [
        "v1 inserts the Sentinel-2 mask into its state on dates flagged `observation_inserted`; on those dates this",
        "is a consistency check and not an independent validation.",
        "",
        md_table(per_date),
        "",
        "Pooled, 100 m cells decided by Sentinel-2:",
        "",
        md_table(pd.DataFrame([result.pooled])),
        "",
        "Pooled over the dates where v1 did not insert the mask (the only independent ones):",
        "",
        md_table(pd.DataFrame([result.pooled_not_inserted])),
        "",
        "By 200 m elevation band (bands with at least 30 cells):",
        "",
        md_table(result.by_band),
    ]
    pooled = result.pooled_not_inserted or result.pooled
    if pooled:
        headline.update(
            {
                "s2_dates": len(per_date),
                "s2_scored_dates_not_inserted": int((~per_date["observation_inserted"]).sum()),
                "s2_f1": pooled["f1"],
                "s2_mcc": pooled["mcc"],
                "s2_accuracy": pooled["accuracy"],
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--product", required=True)
    parser.add_argument("--fold", default="all", help="water year, or all")
    parser.add_argument("--reference", choices=("poqueira",), default="poqueira")
    parser.add_argument("--reference-csv")
    parser.add_argument("--variable", default="snow_depth")
    parser.add_argument("--s2-presence", action="store_true")
    parser.add_argument("--name", help="report file name, default from product and fold")
    args = parser.parse_args(argv)
    if args.fold != "all" and not args.fold.isdigit():
        parser.error("--fold is a water year such as 2013, or all")
    product_name = (
        str(args.product).replace(":", "-")
        if str(args.product).startswith("catalogue:")
        else Path(str(args.product)).stem
    )
    args.name = args.name or f"{product_name}-{args.variable}-{args.fold}"
    REPORT_DIR.mkdir(exist_ok=True)
    text, headline = build(args)
    path = REPORT_DIR / f"{args.name}.md"
    path.write_text(text, encoding="utf-8")
    for key, value in headline.items():
        print(f"{key}: {value:.4f}" if isinstance(value, float) else f"{key}: {value}")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
