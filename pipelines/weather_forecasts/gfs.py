from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

NOMADS_FILTER_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"


def accumulation_steps(horizon_hours: int) -> tuple[int, ...]:
    if horizon_hours <= 0 or horizon_hours > 384:
        raise ValueError("GFS horizon must be between 1 and 384 hours")
    if horizon_hours <= 120 and horizon_hours % 3:
        raise ValueError("Horizon must align with the 3-hour accumulation windows")
    if 120 < horizon_hours <= 240 and (horizon_hours - 120) % 3:
        raise ValueError("Horizon must align with the 3-hour accumulation windows")
    if horizon_hours > 240 and (horizon_hours - 240) % 12:
        raise ValueError("Horizon must align with the 12-hour accumulation windows")

    steps = list(range(3, min(horizon_hours, 120) + 1, 3))
    if horizon_hours > 120:
        steps.extend(range(123, min(horizon_hours, 240) + 1, 3))
    if horizon_hours > 240:
        steps.extend(range(252, horizon_hours + 1, 12))
    return tuple(steps)


class GfsClient:
    def __init__(self, bbox: tuple[float, float, float, float], timeout: int = 120):
        self.left, self.bottom, self.right, self.top = bbox
        self.timeout = timeout

    def _url(self, cycle: datetime, step: int, variables: tuple[str, ...]) -> str:
        params = {
            "file": f"gfs.t{cycle:%H}z.pgrb2.0p25.f{step:03d}",
            "subregion": "",
            "leftlon": self.left,
            "rightlon": self.right,
            "toplat": self.top,
            "bottomlat": self.bottom,
            "dir": f"/gfs.{cycle:%Y%m%d}/{cycle:%H}/atmos",
        }
        for variable in variables:
            params[f"var_{variable}"] = "on"
        if "TMP" in variables:
            params["lev_2_m_above_ground"] = "on"
        if any(variable in variables for variable in ("APCP", "CRAIN", "CSNOW")):
            params["lev_surface"] = "on"
        return f"{NOMADS_FILTER_URL}?{urlencode(params)}"

    def is_complete(self, cycle: datetime, final_step: int) -> bool:
        request = Request(
            self._url(cycle, final_step, ("APCP",)),
            headers={"User-Agent": "NivoSense forecast pipeline"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read(4) == b"GRIB"
        except OSError:
            return False

    def download(
        self,
        cycle: datetime,
        step: int,
        variables: tuple[str, ...],
        destination: Path,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".part")
        request = Request(
            self._url(cycle, step, variables),
            headers={"User-Agent": "NivoSense forecast pipeline"},
        )
        with urlopen(request, timeout=self.timeout) as response, partial.open("wb") as output:
            first = response.read(4)
            if first != b"GRIB":
                raise RuntimeError(f"Unexpected response for forecast hour {step}")
            output.write(first)
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        partial.replace(destination)
        return destination
