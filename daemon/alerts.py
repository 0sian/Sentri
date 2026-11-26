"""Shared bookkeeping for notch alerts (homelab_watch, doctor): show each problem once, again after a
while if it is still there, and forget it when it clears so a repeat counts as news."""
import time

REMIND = 2 * 3600


class Tracker:
    def __init__(self, remind: float = REMIND, clock=time.monotonic):
        self.remind, self.clock = remind, clock
        self.notified = {}      # key -> when it was shown

    def due(self, alerts: list) -> list:
        """alerts: [(key, text)] currently wrong. Returns the ones to show now. Forgets cleared keys.
        Call mark() once they have actually been shown."""
        keys = {k for k, _ in alerts}
        for k in list(self.notified):
            if k not in keys:
                del self.notified[k]
        now = self.clock()
        return [(k, t) for k, t in alerts if k not in self.notified or now - self.notified[k] >= self.remind]

    def mark(self, keys):
        now = self.clock()
        for k in keys:
            self.notified[k] = now
