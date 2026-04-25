"""
Extract 5-band feature TIFs for all S2 acquisitions.

Usage
-----
    GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/application_default_credentials.json \
    python ml/extract_all.py
"""
import os
from pathlib import Path

from data_preparation.batch import run_batch

DEM_PATH = str(Path(__file__).parent.parent / "_mosaic_tmp.tif")
OUTPUT_DIR = "D:/extracted"

if __name__ == "__main__":
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        candidates = [
            Path.home() / ".config/gcloud/application_default_credentials.json",
            Path(os.environ.get("APPDATA", "")) / "gcloud/application_default_credentials.json",
        ]
        creds = next((p for p in candidates if p.exists()), None)
        if creds:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(creds)
        else:
            raise EnvironmentError(
                "Set GOOGLE_APPLICATION_CREDENTIALS or run: gcloud auth application-default login"
            )

    run_batch(
        dem_path=DEM_PATH,
        output_dir=OUTPUT_DIR,
        max_workers=6,
    )
