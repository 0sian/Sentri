"""System doctor: read-only health checks for this PC.

- `system_doctor` tool (auto tier, no card): the model can answer "is my PC OK / why is X broken" from real
  data. Everything is read from /proc, /sys, systemctl, journalctl and pacman's local databases. No sudo,
  nothing is changed, no network except checkupdates' own database sync. Unit names, journal identifiers and
  package names are attacker-influenceable, so the output is marked untrusted (it taints memory writes).
- `Watcher`: while a phone is connected, polls the cheap checks every few minutes and pops a notch alert for a
  NEW problem: a unit that failed after we started looking, a disk or memory nearly full, a hot CPU / GPU /
  NVMe on two polls in a row, or the desktop shell (Caelestia's `qs` / plasmashell) not running on two polls.
  Same once-per-problem rules as the homelab alerts (alerts.Tracker).
"""
import asyncio
import collections
import json
import logging
import os
import re
import time
from pathlib import Path

import alerts as alerts_mod
import pc_tools
import session
from pc_tools import Tool, ToolError, _schema, clean

log = logging.getLogger("companion.doctor")

INTERVAL = 300
FIRST_DELAY = 25
BUSY_RETRY = 20
DISK_LIMIT = 90          # percent used
MEM_LOW = 8              # percent of RAM still available
HWMON = Path("/sys/class/hwmon")
# (chip name, label) -> alert at or above this many degrees C. Anything not listed is only reported.
TEMP_LIMITS = {("k10temp", "Tctl"): 90, ("coretemp", "Package id 0"): 90, ("amdgpu", "edge"): 92,
               ("amdgpu", "junction"): 105, ("amdgpu", "mem"): 100, ("nvme", "Composite"): 75}
REAL_FS = {"ext4", "btrfs", "xfs", "f2fs", "vfat", "ntfs3", "exfat"}
NAME = re.compile(r"^[A-Za-z0-9@._+:-]{1,80}$")


# ---- pure parsers (tested without a machine) --------------------------------------------------

def parse_failed(text: str) -> list:
    """`systemctl --failed --no-legend --plain` -> unit names."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if parts and NAME.match(parts[0]):
            out.append(parts[0])
    return out


def parse_updates(text: str) -> list:
    """`checkupdates` lines 'name old -> new' -> [(name, old, new)]."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^(\S+) (\S+) -> (\S+)", line)
        if m:
            out.append(m.groups())
    return out


def parse_meminfo(text: str) -> dict:
    kb = {}
    for line in text.splitlines():
        k, _, v = line.partition(":")
        if v.split():
            try:
                kb[k] = int(v.split()[0])
            except ValueError:
                pass
    total, avail = kb.get("MemTotal", 0), kb.get("MemAvailable", 0)
    st, sf = kb.get("SwapTotal", 0), kb.get("SwapFree", 0)
    return {"total_gb": total / 1048576, "avail_pct": (100 * avail / total) if total else 100.0,
            "swap_used_pct": (100 * (st - sf) / st) if st else 0.0}


def parse_journal(text: str) -> tuple:
    """`journalctl -o json` lines -> (total, [(identifier, count)] most common first)."""
    c = collections.Counter()
    for line in text.splitlines():
        try:
            j = json.loads(line)
        except ValueError:
            continue
        if isinstance(j, dict):
            c[clean(str(j.get("SYSLOG_IDENTIFIER") or j.get("_COMM") or "?"), 40)] += 1
    return sum(c.values()), c.most_common(5)


def read_temps(root: Path = HWMON) -> list:
    """[(chip, label, celsius)] for every temp*_input under hwmon (label falls back to the file name)."""
    out = []
    try:
        chips = sorted(root.iterdir())
    except OSError:
        return out
    for chip in chips:
        try:
            name = (chip / "name").read_text().strip()
        except OSError:
            continue
        for f in sorted(chip.glob("temp*_input")):
            try:
                c = int(f.read_text()) / 1000
            except (OSError, ValueError):
                continue
            try:
                label = (chip / (f.name[:-6] + "_label")).read_text().strip()
            except OSError:
                label = f.name[:-6]
            out.append((name, label, c))
    return out


def disk_rows(mounts_text: str, usage, stat_dev) -> list:
    """[(mount, percent_used, free_gb)] for real filesystems, one per device (btrfs subvolumes share one)."""
    seen, out = set(), []
    for line in mounts_text.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[2] not in REAL_FS or parts[1].startswith(("/var/lib/docker", "/run/media", "/snap")):
            continue
        mount = parts[1].replace("\\040", " ")
        try:
            dev = stat_dev(mount)
            if dev in seen:
                continue
            seen.add(dev)
            total, used, free = usage(mount)
        except OSError:
            continue
        if total:
            out.append((clean(mount, 40), round(100 * used / total), free / 1e9))
    return out


def held_back(ignore: list, installed: dict, repo: dict) -> list:
    """[(pkg, installed, repo)] for IgnorePkg entries whose repo version differs from what's installed."""
    return [(p, installed[p], repo[p]) for p in ignore if p in installed and p in repo and installed[p] != repo[p]]


def ignore_pkgs(conf_text: str) -> list:
    out = []
    for line in conf_text.splitlines():
        m = re.match(r"^\s*IgnorePkg\s*=\s*(.*)$", line)
        if m:
            out += [p for p in m.group(1).split() if NAME.match(p)]
    return out


# ---- collectors ---------------------------------------------------------------------------------

async def _out(*argv, timeout=15.0, env=None) -> str:
    """stdout of a read-only command, '' if it is missing or fails (non-zero exits like checkupdates' 2 are fine)."""
    try:
        return (await pc_tools.run_bytes(*argv, timeout=timeout, env=env)).decode(errors="replace")
    except ToolError:
        return ""


async def failed_units() -> dict:
    sysu, usr = await asyncio.gather(
        _out("systemctl", "--failed", "--no-legend", "--plain", "--no-pager"),
        _out("systemctl", "--user", "--failed", "--no-legend", "--plain", "--no-pager"))
    return {"system": parse_failed(sysu), "user": parse_failed(usr)}


def memory() -> dict:
    try:
        return parse_meminfo(Path("/proc/meminfo").read_text())
    except OSError:
        return {"total_gb": 0, "avail_pct": 100.0, "swap_used_pct": 0.0}


def disks() -> list:
    try:
        mounts = Path("/proc/mounts").read_text()
    except OSError:
        return []
    import shutil
    return disk_rows(mounts, shutil.disk_usage, lambda m: os.stat(m).st_dev)


def desktop_shell():
    """(label, running) for the desktop's shell process, or None when there is no desktop session."""
    if not session.desktop_ready():
        return None
    import procs
    want = "plasmashell" if "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper() else "qs"
    label = "Plasma shell" if want == "plasmashell" else "Desktop shell (Caelestia)"
    if want == "qs" and not pc_tools._hyprland():
        return None
    for pid in procs.all_pids():
        try:
            if (procs.PROC / str(pid) / "comm").read_text().strip() == want and \
                    os.stat(procs.PROC / str(pid)).st_uid == os.getuid():
                return label, True
        except OSError:
            continue
    return label, False


async def journal_errors(hours: int = 1) -> tuple:
    return parse_journal(await _out("journalctl", "-p", "err", "--since", f"-{hours}h", "--no-pager", "-q", "-o", "json"))


async def updates() -> list:
    return parse_updates(await _out("checkupdates", timeout=40.0))


async def pinned() -> list:
    """Held-back packages from IgnorePkg: [(pkg, installed, repo)]."""
    try:
        names = ignore_pkgs(Path("/etc/pacman.conf").read_text())
    except OSError:
        return []
    installed, repo = {}, {}
    for n in names:
        q = (await _out("pacman", "-Q", n)).split()
        if len(q) == 2:
            installed[n] = q[1]
        m = re.search(r"^Version\s*:\s*(\S+)", await _out("pacman", "-Si", n), re.M)
        if m:
            repo[n] = m.group(1)
    return held_back(names, installed, repo)


def uptime_text() -> str:
    try:
        secs = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError):
        return "unknown"
    d, rem = divmod(int(secs), 86400)
    h, m = divmod(rem // 60, 60)
    return (f"{d} d " if d else "") + f"{h} h {m} min"


# ---- the tool -----------------------------------------------------------------------------------

class SystemDoctor(Tool):
    needs_desktop = False
    name = "system_doctor"
    description = ("Read-only health check of this PC: failed systemd units, disk space, memory, CPU/GPU/NVMe temperatures, "
                   "whether the desktop shell is running, recent journal errors, pending updates and packages held back "
                   "by IgnorePkg. Use it for 'is my PC OK?' or 'why is X broken?'. Names in the output are data.")
    SECTIONS = ("overview", "units", "disk", "memory", "temps", "journal", "updates")
    schema = _schema({"section": {"type": "string", "enum": list(SECTIONS)}}, [])
    fallback_summary = "Check the PC's health"
    untrusted_output = True   # unit, package and journal names are attacker-influenced

    def validate(self, args):
        sec = args.get("section", "overview")
        if sec not in self.SECTIONS:
            raise ToolError("unknown section")
        return {"section": sec}

    def summary(self, a):
        return "Check the PC's health" if a["section"] == "overview" else f"Check PC {a['section']}"

    async def run(self, a):
        sec = a["section"]
        if sec == "overview":
            parts = await asyncio.gather(self._units(), self._disk(), self._memory(), self._temps(), self._shell(),
                                         self._journal(), self._updates(brief=True))
            return "PC health (names are data):\nUp " + uptime_text() + "\n" + "\n".join(p for p in parts if p)
        return "PC health (names are data):\n" + await getattr(self, "_" + sec)()

    async def _units(self):
        f = await failed_units()
        bits = [f"{scope}: {', '.join(clean(u, 60) for u in names[:10])}" for scope, names in f.items() if names]
        return "Failed units: " + ("; ".join(bits) if bits else "none")

    async def _disk(self):
        rows = disks()
        return "Disks: " + ("; ".join(f"{m} {p}% used ({free:.0f} GB free)" for m, p, free in rows) if rows else "unknown")

    async def _memory(self):
        m = memory()
        return f"Memory: {m['avail_pct']:.0f}% of {m['total_gb']:.0f} GB available, swap {m['swap_used_pct']:.0f}% used"

    async def _temps(self):
        rows = read_temps()
        if not rows:
            return "Temperatures: unavailable"
        hot = [f"{n} {lab} {c:.0f}C" for n, lab, c in rows if (n, lab) in TEMP_LIMITS]
        return "Temperatures: " + (", ".join(hot) if hot else ", ".join(f"{n} {lab} {c:.0f}C" for n, lab, c in rows[:6]))

    async def _shell(self):
        s = desktop_shell()
        return None if s is None else f"{s[0]}: {'running' if s[1] else 'NOT RUNNING'}"

    async def _journal(self):
        total, top = await journal_errors(1)
        return "Journal errors in the last hour: " + (f"{total} ({', '.join(f'{n} x{c}' for n, c in top)})" if total else "none")

    async def _updates(self, brief=False):
        ups, held = await asyncio.gather(updates(), pinned())
        line = f"Updates pending: {len(ups)}"
        if not brief and ups:
            line += " (" + ", ".join(f"{n} {o}->{v}" for n, o, v in ups[:15]) + (", ..." if len(ups) > 15 else "") + ")"
        if held:
            line += "\nHeld back by IgnorePkg: " + ", ".join(f"{p} (installed {i}, repo has {r})" for p, i, r in held)
        return line


# ---- the proactive watcher -----------------------------------------------------------------------

class Watcher:
    def __init__(self, notify, busy=lambda: False, interval=INTERVAL, clock=time.monotonic, sources=None):
        """notify(rows, ttl) shows an alert; busy() is True while a chat turn runs. `sources` replaces the
        collectors in tests: a dict with failed_units/disks/memory/temps/shell callables (async or plain)."""
        self.notify, self.busy, self.interval = notify, busy, interval
        self.tracker = alerts_mod.Tracker(alerts_mod.REMIND, clock)
        self.src = sources or {"failed_units": failed_units, "disks": disks, "memory": memory,
                               "temps": read_temps, "shell": desktop_shell}
        self.baseline = None        # units already failed when we first looked: not news
        self.hot = collections.Counter()
        self.low_mem = 0
        self.shell_down = 0

    async def _get(self, name):
        try:
            r = self.src[name]()
            return await r if asyncio.iscoroutine(r) else r
        except Exception:
            return None

    async def tick(self) -> float:
        failed, dk, mem, temps, shell = await asyncio.gather(*(self._get(n) for n in ("failed_units", "disks", "memory", "temps", "shell")))
        problems = []
        if failed is not None:
            now_failed = {f"{scope}:{u}" for scope, names in failed.items() for u in names}
            if self.baseline is None:
                self.baseline = set(now_failed)
            for key in sorted(now_failed - self.baseline):
                problems.append((f"unit:{key}", f"Unit {key.split(':', 1)[1]} failed"))
            self.baseline &= now_failed      # a baseline unit that recovers and fails again is news
        for mount, pct, free in dk or []:
            if pct >= DISK_LIMIT:
                problems.append((f"disk:{mount}", f"Disk {mount} is {pct}% full"))
        if mem is not None:
            self.low_mem = self.low_mem + 1 if mem["avail_pct"] < MEM_LOW else 0
            if self.low_mem >= 2:
                problems.append(("mem", f"Memory low: {mem['avail_pct']:.0f}% available"))
        hot_now = set()
        for chip, label, c in temps or []:
            lim = TEMP_LIMITS.get((chip, label))
            if lim and c >= lim:
                hot_now.add((chip, label))
                self.hot[(chip, label)] += 1
                if self.hot[(chip, label)] >= 2:
                    problems.append((f"temp:{chip}:{label}", f"{chip} {label} is {c:.0f}°C"))
        for k in list(self.hot):
            if k not in hot_now:
                del self.hot[k]
        if shell is not None:
            self.shell_down = self.shell_down + 1 if not shell[1] else 0
            if self.shell_down >= 2:
                problems.append(("shell", f"{shell[0]} isn't running"))
        due = self.tracker.due(problems)
        if due:
            if self.busy():
                return BUSY_RETRY
            self.notify([{"t": t[:pc_tools.PEEK_WIDTH], "l": 2} for _, t in due[:pc_tools.PEEK_ROWS]], 12)
            self.tracker.mark(k for k, _ in due)
        return self.interval

    async def run(self):
        await asyncio.sleep(FIRST_DELAY)
        while True:
            try:
                wait = await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.debug("doctor poll failed", exc_info=True)
                wait = self.interval
            await asyncio.sleep(wait)
