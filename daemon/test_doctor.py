#!/usr/bin/env python3
"""System doctor: parsers, the system_doctor tool (fake collectors) and the proactive watcher."""
import asyncio
import sys
import tempfile
from pathlib import Path

import doctor
import pc_tools

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


async def main():
    # ---- parsers ----
    check("failed units: plain rows", doctor.parse_failed("foo.service loaded failed failed Foo\nbar.timer loaded failed failed Bar") == ["foo.service", "bar.timer"])
    check("failed units: names are validated", doctor.parse_failed("a;b loaded failed failed X\nok.service loaded failed failed Y") == ["ok.service"])
    check("updates parse", doctor.parse_updates("7zip 26.04-1.1 -> 26.06-1.1\ngarbage\nada 4.0.0-1 -> 4.1.1-1") == [("7zip", "26.04-1.1", "26.06-1.1"), ("ada", "4.0.0-1", "4.1.1-1")])
    m = doctor.parse_meminfo("MemTotal: 16000000 kB\nMemAvailable: 4000000 kB\nSwapTotal: 8000000 kB\nSwapFree: 6000000 kB\n")
    check("meminfo", round(m["avail_pct"]) == 25 and round(m["swap_used_pct"]) == 25 and round(m["total_gb"]) == 15, m)
    check("meminfo with no swap or junk", doctor.parse_meminfo("MemTotal: 1000 kB\nMemAvailable: 500 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\nweird")["swap_used_pct"] == 0)
    total, top = doctor.parse_journal('{"SYSLOG_IDENTIFIER":"kernel"}\nnot json\n{"_COMM":"steam"}\n{"SYSLOG_IDENTIFIER":"kernel"}\n[1]\n')
    check("journal counts by identifier", total == 3 and top[0] == ("kernel", 2), (total, top))
    check("ignore_pkgs parses and validates", doctor.ignore_pkgs("#IgnorePkg = no\nIgnorePkg   = libcava noctalia-qs $bad\nIgnorePkg = extra") == ["libcava", "noctalia-qs", "extra"])
    check("held back = installed differs from repo", doctor.held_back(["a", "b", "c"], {"a": "1", "b": "2"}, {"a": "1", "b": "3", "c": "9"}) == [("b", "2", "3")])

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i, (name, temps) in enumerate((("k10temp", {"temp1": ("Tctl", 42500)}), ("nvme", {"temp1": ("Composite", 34000), "temp2": (None, 48000)}))):
            d = root / f"hwmon{i}"; d.mkdir(); (d / "name").write_text(name + "\n")
            for t, (label, v) in temps.items():
                (d / f"{t}_input").write_text(str(v))
                if label: (d / f"{t}_label").write_text(label)
        (root / "hwmon9").mkdir()      # no name file: skipped
        rows = doctor.read_temps(root)
        check("hwmon temps read with labels and fallbacks", rows == [("k10temp", "Tctl", 42.5), ("nvme", "Composite", 34.0), ("nvme", "temp2", 48.0)], rows)
    check("missing hwmon dir is fine", doctor.read_temps(Path("/nonexistent")) == [])

    mounts = "/dev/a / ext4 rw 0 0\n/dev/a /home btrfs rw 0 0\n/dev/b /boot vfat rw 0 0\ntmpfs /tmp tmpfs rw 0 0\n/dev/c /run/media/x ext4 rw 0 0\n/dev/d /var/lib/docker/overlay2/x ext4 rw 0 0\n"
    devs = {"/": 1, "/home": 1, "/boot": 2}
    rows = doctor.disk_rows(mounts, lambda m: (1000, 900, 100) if m == "/" else (100, 3, 97), lambda m: devs[m])
    check("disks: real filesystems only, one per device", [(m, p) for m, p, _ in rows] == [("/", 90), ("/boot", 3)], rows)

    # ---- the tool, with fake collectors ----
    async def fake_failed(): return {"system": ["foo.service"], "user": []}
    async def fake_journal(h=1): return 5, [("kernel", 3), ("steam", 2)]
    async def fake_updates(): return [("a", "1", "2")] * 3
    async def fake_pinned(): return [("libcava", "0.10.7-2", "1.0.0-1")]
    doctor.failed_units, doctor.journal_errors, doctor.updates, doctor.pinned = fake_failed, fake_journal, fake_updates, fake_pinned
    doctor.disks = lambda: [("/", 91, 20.0)]
    doctor.memory = lambda: {"total_gb": 16, "avail_pct": 38, "swap_used_pct": 11}
    doctor.read_temps = lambda root=None: [("k10temp", "Tctl", 50.0), ("amdgpu", "edge", 57.0), ("acpitz", "temp1", 16.0)]
    doctor.desktop_shell = lambda: ("Desktop shell (Caelestia)", False)
    t = doctor.SystemDoctor()
    check("tool is read-only (no confirmation) and marked untrusted", t.risk is None and t.untrusted_output is True and not t.needs_confirm({"section": "overview"}))
    check("validate: default and bad section", t.validate({}) == {"section": "overview"} and _raises(lambda: t.validate({"section": "rm -rf"})))
    out = await t.run(t.validate({}))
    for needle in ("Failed units: system: foo.service", "/ 91% used", "Memory: 38%", "k10temp Tctl 50C", "NOT RUNNING", "kernel x3", "Updates pending: 3", "Held back by IgnorePkg: libcava (installed 0.10.7-2, repo has 1.0.0-1)"):
        check(f"overview mentions {needle!r}", needle in out, out)
    check("a section returns just that section", (await t.run(t.validate({"section": "units"}))).count("\n") == 1, await t.run(t.validate({"section": "units"})))
    doctor.failed_units = lambda: _async({"system": [], "user": []})
    check("no failed units says none", "none" in await t.run(t.validate({"section": "units"})))
    reg = pc_tools.registry()
    check("registered, and last (tool order is part of the cached prompt)", "system_doctor" in reg and list(reg)[-1] == "system_doctor", list(reg)[-3:])

    # ---- watcher ----
    class Src:
        def __init__(self):
            self.failed = {"system": ["old.service"], "user": []}
            self.disks = [("/", 40, 100.0)]
            self.mem = {"avail_pct": 40.0}
            self.temps = [("k10temp", "Tctl", 50.0)]
            self.shell = ("Desktop shell (Caelestia)", True)

        def sources(self):
            return {"failed_units": lambda: _async(self.failed), "disks": lambda: self.disks, "memory": lambda: self.mem,
                    "temps": lambda: self.temps, "shell": lambda: self.shell}

    def mk(busy=False):
        s, shown, now, st = Src(), [], [0.0], {"busy": busy}
        w = doctor.Watcher(lambda rows, ttl: shown.append([r["t"] for r in rows]), lambda: st["busy"], 300, lambda: now[0], s.sources())
        return w, s, shown, now, st

    w, s, shown, now, st = mk()
    await w.tick()
    check("a unit that was already failed at the start isn't news", shown == [], shown)
    s.failed = {"system": ["old.service"], "user": ["new.service"]}
    await w.tick()
    check("a newly failed unit alerts", shown == [["Unit new.service failed"]], shown)
    await w.tick()
    check("not repeated", len(shown) == 1)
    s.failed = {"system": [], "user": []}
    await w.tick()
    s.failed = {"system": ["old.service"], "user": []}
    await w.tick()
    check("a baseline unit that recovered and fails again is news", len(shown) == 2 and "old.service" in shown[1][0], shown)
    s.failed = {"system": [], "user": []}; await w.tick()

    shown.clear()
    s.disks = [("/", 93, 10.0)]
    await w.tick()
    check("disk >= 90% alerts", shown == [["Disk / is 93% full"]], shown)
    s.disks = [("/", 40, 10.0)]; await w.tick()

    shown.clear()
    s.mem = {"avail_pct": 4.0}
    await w.tick()
    check("one low-memory poll is ignored", shown == [])
    await w.tick()
    check("low memory twice alerts", len(shown) == 1 and "Memory low" in shown[0][0], shown)
    s.mem = {"avail_pct": 40.0}; await w.tick()

    shown.clear()
    s.temps = [("k10temp", "Tctl", 95.0), ("acpitz", "temp1", 99.0)]
    await w.tick()
    check("one hot poll is ignored; unlisted sensors never alert", shown == [], shown)
    await w.tick()
    check("hot twice alerts", len(shown) == 1 and "k10temp Tctl is 95" in shown[0][0] and "acpitz" not in shown[0][0], shown)
    s.temps = [("k10temp", "Tctl", 50.0)]; await w.tick()

    shown.clear()
    s.shell = ("Desktop shell (Caelestia)", False)
    await w.tick()
    check("shell down once is ignored", shown == [])
    await w.tick()
    check("shell down twice alerts", shown == [["Desktop shell (Caelestia) isn't running"]], shown)
    s.shell = None; await w.tick()
    s.shell = ("Desktop shell (Caelestia)", True); await w.tick()

    shown.clear()
    s.disks = [("/", 95, 1.0)]
    now[0] += doctor.alerts_mod.REMIND + 1
    await w.tick(); await w.tick()
    check("still-broken things are reminded after a while", len(shown) >= 1, shown)

    w2, s2, shown2, _, st2 = mk(busy=True)
    await w2.tick()
    s2.disks = [("/", 99, 1.0)]
    wait = await w2.tick()
    check("busy chat turn: retry soon, nothing shown", shown2 == [] and wait == doctor.BUSY_RETRY, (shown2, wait))
    st2["busy"] = False
    await w2.tick()
    check("shown once the turn is over", len(shown2) == 1)

    w3, s3, shown3, _, _ = mk()
    src = s3.sources(); src["disks"] = lambda: 1 / 0
    w3.src = src
    await w3.tick()
    check("a failing collector doesn't break the poll", True)

    if failures:
        print(f"{len(failures)} FAILED: {failures}"); sys.exit(1)
    print("all tests passed")


def _raises(f):
    try:
        f()
    except pc_tools.ToolError:
        return True
    return False


async def _async(v):
    return v

asyncio.run(main())
