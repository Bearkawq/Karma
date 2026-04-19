"""TimeBudget — wall-clock time budget enforcer for golearn sessions."""

import time


class TimeBudget:
    """Wall-clock time budget enforcer using monotonic clock."""

    def __init__(self, minutes: float):
        self.budget_seconds = minutes * 60.0
        self.start_time = None

    def start(self) -> None:
        self.start_time = time.monotonic()

    def elapsed(self) -> float:
        if self.start_time is None:
            return 0.0
        return time.monotonic() - self.start_time

    def remaining(self) -> float:
        return max(0.0, self.budget_seconds - self.elapsed())

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def fraction_used(self) -> float:
        if self.budget_seconds <= 0:
            return 1.0
        return min(1.0, self.elapsed() / self.budget_seconds)
