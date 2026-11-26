"""Proactive homelab alerts for the notch. While a phone is connected, poll the same fixed read-only
Glances endpoints homelab_stats uses every few minutes and, when something new goes wrong, pop a short
alert out of the notch (and make the eyes look startled). PC only; nothing here reaches the model.

What counts: CPU >= 90% on two polls in a row (spikes don't), memory >= 90%, any disk >= 90%, a
container that was running and no longer is (one that was already stopped when we started looking is
treated as intentional), and the homelab being unreachable on two polls in a row. Each problem is shown
once, again after REMIND seconds if it is still there, and forgotten when it clears.
"""
import asyncio
import logging
import re
import time

import pc_tools

log = logging.getLogger("companion.homelab")

INTERVAL = 300          # seconds between polls
FIRST_DELAY = 20        # let the connection settle; the first poll is only a baseline for containers
REMIND = 2 * 3600
BUSY_RETRY = 20         # a chat turn is running: try the notification again shortly
LIMIT = 90
UP = re.compile(r"(?i)\b(up|running|healthy)\b")


def evaluate(cpu, mem, fs_text, ct_text, seen_up: set):
    """-> (alerts [(key, text)], cpu_hot). cpu/mem are Glances dicts or None, fs_text/ct_text the
    cleaned summaries (or None). seen_up is updated with containers seen running."""
    alerts = []
    cpu_hot = False
    if isinstance(cpu, dict) and pc_tools._num(cpu.get("total")) >= LIMIT:
        cpu_hot = True
    if isinstance(mem, dict) and pc_tools._num(mem.get("percent")) >= LIMIT:
        alerts.append(("mem", f"Memory {pc_tools._num(mem.get('percent')):.0f}% used"))
    for line in (fs_text or "").split("\n"):
        m = re.match(r"(.*?)(?: \([^)]*\))?: (\d+)% of", line)
        if m and int(m.group(2)) >= LIMIT:
            alerts.append((f"fs:{m.group(1)}", f"Disk {m.group(1)} is {m.group(2)}% full"))
    for line in (ct_text or "").split("\n"):
        if line.startswith("(+") or ": " not in line:
            continue
        name, status = line.split(": ", 1)
        if UP.search(status):
            seen_up.add(name)
        elif name in seen_up:
            alerts.append((f"ct:{name}", f"Container {name} is down"))
    return alerts, cpu_hot


class Watcher:
    def __init__(self, fetch, notify, busy=lambda: False, interval=INTERVAL, clock=time.monotonic):
        """fetch(section) -> Glances JSON (async, may raise); notify(rows, ttl) shows the alert;
        busy() is True while a chat turn is running."""
        self.fetch, self.notify, self.busy, self.interval, self.clock = fetch, notify, busy, interval, clock
        self.seen_up = set()
        self.notified = {}      # key -> when it was shown
        self.cpu_hits = 0
        self.fails = 0

    async def _get(self, sec):
        try:
            return await self.fetch(sec)
        except Exception:
            return None

    async def tick(self) -> float:
        """One poll. Returns how long to wait before the next one."""
        cpu, mem, fs, ct = await asyncio.gather(*(self._get(s) for s in ("cpu", "mem", "fs", "containers")))
        if cpu is None and mem is None and fs is None:
            self.fails += 1
            alerts, cpu_hot = ([("down", "Can't reach the homelab")] if self.fails >= 2 else []), False
        else:
            self.fails = 0
            fs_text = pc_tools._glances_summary("fs", fs) if fs is not None else None
            ct_text = pc_tools._glances_summary("containers", ct) if ct is not None else None
            alerts, cpu_hot = evaluate(cpu, mem, fs_text, ct_text, self.seen_up)
        self.cpu_hits = self.cpu_hits + 1 if cpu_hot else 0
        if self.cpu_hits >= 2:
            alerts.append(("cpu", f"CPU {pc_tools._num(cpu.get('total')):.0f}% busy"))
        now = self.clock()
        keys = {k for k, _ in alerts}
        for k in list(self.notified):
            if k not in keys:
                del self.notified[k]          # cleared: a repeat will be news again
        due = [(k, t) for k, t in alerts if k not in self.notified or now - self.notified[k] >= REMIND]
        if due:
            if self.busy():
                return BUSY_RETRY
            self.notify([{"t": t[:pc_tools.PEEK_WIDTH], "l": 2} for _, t in due[:pc_tools.PEEK_ROWS]], 12)
            for k, _ in due:
                self.notified[k] = now
        return self.interval

    async def run(self):
        await asyncio.sleep(FIRST_DELAY)
        while True:
            try:
                wait = await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.debug("homelab poll failed", exc_info=True)
                wait = self.interval
            await asyncio.sleep(wait)
