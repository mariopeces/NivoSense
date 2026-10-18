from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone


def candidate_cycles(
    now: datetime, max_age_hours: int = 48, stride_hours: int = 6
) -> Iterator[datetime]:
    utc = now.astimezone(timezone.utc)
    current = utc.replace(
        hour=(utc.hour // stride_hours) * stride_hours,
        minute=0,
        second=0,
        microsecond=0,
    )
    for age in range(0, max_age_hours + 1, stride_hours):
        yield current - timedelta(hours=age)


def select_latest_cycle(
    now: datetime,
    is_complete: Callable[[datetime], bool],
    max_age_hours: int = 48,
    stride_hours: int = 6,
) -> datetime:
    for cycle in candidate_cycles(now, max_age_hours, stride_hours):
        if is_complete(cycle):
            return cycle
    raise RuntimeError("No complete forecast cycle was found")
