#!/usr/bin/env python3
"""Proactive homelab alerts: what counts as a problem, shown once, cleared and re-armed, never noisy."""
import asyncio
import sys

import homelab_watch as hw

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class Lab:
    """A fake Glances: set the fields, or set down=True."""
    def __init__(self):
        self.cpu, self.mem, self.down = 10.0, 30.0, False
        self.disks = [("/", 40), ("/data", 50)]
        self.cts = {"web": "running", "db": "running"}

    async def fetch(self, sec):
        if self.down:
            raise OSError("down")
        if sec == "cpu":
            return {"total": self.cpu, "cpucore": 4}
        if sec == "mem":
            return {"percent": self.mem, "used": 1e9, "total": 4e9}
        if sec == "fs":
            return [{"device_name": d, "mnt_point": d, "fs_type": "ext4", "percent": p, "size": 1e12, "free": 1e11}
                    for d, p in self.disks]
        if sec == "containers":
            return [{"name": n, "status": s} for n, s in self.cts.items()]


def make(lab, busy=False):
    shown, now = [], [0.0]
    st = {"busy": busy}
    w = hw.Watcher(lab.fetch, lambda rows, ttl: shown.append([r["t"] for r in rows]), lambda: st["busy"], 300, lambda: now[0])
    return w, shown, now, st


async def main():
    lab = Lab()
    w, shown, now, st = make(lab)
    await w.tick()
    check("healthy homelab: silent", shown == [], shown)

    lab.cpu = 97
    await w.tick()
    check("one CPU spike is ignored", shown == [], shown)
    await w.tick()
    check("CPU hot on two polls in a row alerts", shown == [["CPU 97% busy"]], shown)
    await w.tick()
    check("same alert isn't repeated", len(shown) == 1)
    lab.cpu = 10
    await w.tick()
    lab.cpu = 97
    await w.tick(); await w.tick()
    check("cleared then back: news again", len(shown) == 2, shown)
    lab.cpu = 10
    await w.tick()

    shown.clear()
    lab.mem = 93; lab.disks = [("/", 40), ("/data", 94)]
    await w.tick()
    check("memory and disk alert together in one peek", len(shown) == 1 and len(shown[0]) == 2
          and any(t.startswith("Memory 93%") for t in shown[0]) and any("/data" in t and "94%" in t for t in shown[0]), shown)
    now[0] += hw.REMIND + 1
    await w.tick()
    check("still-broken things are reminded after a while", len(shown) == 2, shown)
    lab.mem, lab.disks = 30, [("/", 40)]
    await w.tick()

    shown.clear()
    lab.cts["web"] = "exited"
    await w.tick()
    check("a container that was running and stopped alerts", shown == [["Container web is down"]], shown)

    # containers already stopped when first seen are treated as intentional
    lab2 = Lab(); lab2.cts = {"old": "exited", "web": "running"}
    w2, shown2, _, _ = make(lab2)
    await w2.tick()
    check("container stopped from the start: no alert", shown2 == [], shown2)

    # busy chat turn: don't interrupt, retry soon, and don't mark it shown
    lab3 = Lab(); lab3.mem = 95
    w3, shown3, _, st3 = make(lab3, busy=True)
    wait = await w3.tick()
    check("busy: no alert yet, short retry", shown3 == [] and wait == hw.BUSY_RETRY, (shown3, wait))
    st3["busy"] = False
    await w3.tick()
    check("alert shown once the turn is over", len(shown3) == 1)

    # unreachable: two polls in a row
    lab4 = Lab(); lab4.down = True
    w4, shown4, _, _ = make(lab4)
    await w4.tick()
    check("one failed poll: silent", shown4 == [])
    await w4.tick()
    check("two failed polls: can't reach the homelab", shown4 == [["Can't reach the homelab"]], shown4)
    lab4.down = False
    await w4.tick()
    lab4.down = True
    await w4.tick(); await w4.tick()
    check("recovery re-arms the unreachable alert", len(shown4) == 2, shown4)

    # long names are clipped for the notch
    lab5 = Lab(); lab5.disks = [("/mnt/" + "x" * 80, 99)]
    w5, shown5, _, _ = make(lab5)
    await w5.tick()
    check("alert text is clipped", shown5 and all(len(t) <= 46 for t in shown5[0]), shown5)

    if failures:
        print(f"{len(failures)} FAILED: {failures}"); sys.exit(1)
    print("all tests passed")

asyncio.run(main())
