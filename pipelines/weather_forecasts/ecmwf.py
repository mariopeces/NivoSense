import json
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

OPEN_DATA_URL = "https://data.ecmwf.int/forecasts"
USER_AGENT = "NivoSense forecast pipeline"
PARAMETERS = {"precipitation_total": "tp", "snowfall": "sf"}
REQUEST_INTERVAL_SECONDS = 1.0
RETRY_STATUSES = {429, 500, 502, 503, 504}


class EcmwfClient:
    def __init__(self, timeout: int = 120, attempts: int = 5):
        self.timeout = timeout
        self.attempts = attempts
        self._indexes: dict[tuple[datetime, int], dict[str, tuple[int, int]]] = {}

    def _base(self, cycle: datetime, step: int) -> str:
        return (
            f"{OPEN_DATA_URL}/{cycle:%Y%m%d}/{cycle:%H}z/ifs/0p25/oper/"
            f"{cycle:%Y%m%d%H}0000-{step}h-oper-fc"
        )

    def _read(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        request = Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        for attempt in range(1, self.attempts + 1):
            time.sleep(REQUEST_INTERVAL_SECONDS)
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except HTTPError as error:
                if error.code not in RETRY_STATUSES or attempt == self.attempts:
                    raise
                time.sleep(10 * attempt)
        raise RuntimeError("unreachable")

    def index(self, cycle: datetime, step: int) -> dict[str, tuple[int, int]]:
        key = (cycle, step)
        if key not in self._indexes:
            payload = self._read(f"{self._base(cycle, step)}.index").decode("utf-8")
            entries = {}
            for line in payload.splitlines():
                record = json.loads(line)
                if record.get("levtype") == "sfc":
                    entries[record["param"]] = (record["_offset"], record["_length"])
            self._indexes[key] = entries
        return self._indexes[key]

    def is_complete(self, cycle: datetime, final_step: int) -> bool:
        try:
            entries = self.index(cycle, final_step)
        except OSError:
            return False
        return all(parameter in entries for parameter in PARAMETERS.values())

    def download(
        self, cycle: datetime, step: int, parameter: str, destination: Path
    ) -> Path:
        offset, length = self.index(cycle, step)[parameter]
        payload = self._read(
            f"{self._base(cycle, step)}.grib2",
            {"Range": f"bytes={offset}-{offset + length - 1}"},
        )
        if payload[:4] != b"GRIB" or len(payload) != length:
            raise RuntimeError(f"Unexpected {parameter} response for forecast hour {step}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return destination
