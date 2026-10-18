from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone


def candidate_cycles(now: datetime, max_age_hours: int = 48) -> Iterator[datetime]:
    current = now.astimezone(timezone.utc).replace(
        hour=(now.astimezone(timezone.utc).hour // 6) * 6,
        minute=0,
        second=0,
        microsecond=0,
    )
    for age in range(0, max_age_hours + 1, 6):
        yield current - timedelta(hours=age)


def select_latest_cycle(
    now: datetime,
    is_complete: Callable[[datetime], bool],
    max_age_hours: int = 48,
) -> datetime:
    for cycle in candidate_cycles(now, max_age_hours):
        if is_complete(cycle):
            return cycle
    raise RuntimeError("No complete forecast cycle was found")
