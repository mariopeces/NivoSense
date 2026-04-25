"""Normalize raw flow exports from SAIH Guadalquivir / Hidrosur into the canonical
NivoSense flow JSON consumed by the backend `/rivers/{id}/flow` endpoint.

Input formats supported (auto-detected from columns):
  * SAIH Guadalquivir Excel: columns "Fecha"-style + a caudal column with the variable
    code in its header (e.g. "A05_211_X").
  * Hidrosur CSV/Excel: columns "Fecha" + "Caudal (m3/s)" (or similar).
  * Generic CSV with date + numeric value columns.

Output JSON schema:

    {
      "station_id": "5086",
      "station_name": "Río Dilar — Dilar",
      "variable": "caudal",
      "unit": "m3/s",
      "source": "SAIH Guadalquivir",
      "license": "© Confederación Hidrográfica del Guadalquivir",
      "first_date": "2024-10-01",
      "last_date": "2026-04-25",
      "points": [
        { "date": "2024-10-01", "label": "01 Oct", "value": 0.42 },
        ...
      ]
    }

Usage:
    python ml/normalize_flow.py INPUT_FILE OUTPUT_JSON \\
        --station-id 5086 \\
        --station-name "Río Dilar — Dilar" \\
        --source "SAIH Guadalquivir"

Multiple inputs can be passed (positional) and they will be concatenated and
sorted/deduplicated by date — useful when SAIH limits queries to 170 days and
you have to download the year in chunks.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "pandas is required: pip install pandas openpyxl\n"
    )
    raise


DATE_CANDIDATES = ["fecha", "date", "fecha y hora", "datetime", "dia", "día"]


def detect_date_column(columns: list[str]) -> str | None:
    lowered = {c.lower().strip(): c for c in columns}
    for candidate in DATE_CANDIDATES:
        if candidate in lowered:
            return lowered[candidate]
    for original in columns:
        if any(key in original.lower() for key in DATE_CANDIDATES):
            return original
    return None


def detect_value_column(columns: list[str], date_col: str) -> str | None:
    for original in columns:
        if original == date_col:
            continue
        lower = original.lower()
        if (
            "caudal" in lower
            or "m3/s" in lower
            or "m³/s" in lower
            or original.endswith("_X")
        ):
            return original
    # Fallback: first numeric column that's not the date.
    for original in columns:
        if original != date_col:
            return original
    return None


def parse_value(raw) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, float) and pd.isna(raw):
        return None
    if isinstance(raw, str):
        cleaned = raw.replace(",", ".").strip()
        if not cleaned or cleaned.lower() in {"-", "nan", "null"}:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def parse_date(raw) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(raw.strip(), fmt).date()
            except ValueError:
                continue
        # Fallback: pandas
        try:
            return pd.to_datetime(raw, dayfirst=True).date()
        except (ValueError, TypeError):
            return None
    return None


def load_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".csv":
        return pd.read_csv(path, sep=None, engine="python")
    raise ValueError(f"Unsupported file format: {suffix}")


def normalize_one(path: Path) -> list[tuple[date, float | None]]:
    df = load_table(path)
    columns = [str(c).strip() for c in df.columns]
    df.columns = columns

    date_col = detect_date_column(columns)
    if date_col is None:
        raise ValueError(f"{path}: could not detect date column among {columns}")

    value_col = detect_value_column(columns, date_col)
    if value_col is None:
        raise ValueError(f"{path}: could not detect value column among {columns}")

    rows: list[tuple[date, float | None]] = []
    for _, row in df.iterrows():
        d = parse_date(row[date_col])
        v = parse_value(row[value_col])
        if d is None:
            continue
        rows.append((d, v))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="One or more CSV/Excel files")
    parser.add_argument("output", help="Path to output JSON")
    parser.add_argument("--station-id", required=True)
    parser.add_argument("--station-name", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--variable", default="caudal")
    parser.add_argument("--unit", default="m3/s")
    parser.add_argument("--license", default="")
    args = parser.parse_args()

    aggregated: dict[date, float | None] = {}
    for raw in args.inputs:
        path = Path(raw)
        if not path.exists():
            sys.stderr.write(f"Skipping missing input {path}\n")
            continue
        for d, v in normalize_one(path):
            aggregated[d] = v

    ordered_dates = sorted(aggregated.keys())
    points = [
        {
            "date": d.isoformat(),
            "label": d.strftime("%d %b"),
            "value": aggregated[d],
        }
        for d in ordered_dates
    ]

    payload = {
        "station_id": args.station_id,
        "station_name": args.station_name,
        "variable": args.variable,
        "unit": args.unit,
        "source": args.source,
        "license": args.license,
        "first_date": points[0]["date"] if points else None,
        "last_date": points[-1]["date"] if points else None,
        "points": points,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(points)} points to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
