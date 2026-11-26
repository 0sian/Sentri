"""Things that tap Osian on the shoulder through the notch: timers / reminders and "tell me when that
finishes" process watches. Both are harmless (they only show a message and play a sound), so the tools
run without an approval card. Timers survive a daemon restart (a small JSON file), because a deploy
restarts the daemon and a lost reminder is worse than none.

The overlay draws the countdown itself from absolute end times (it only ticks while a timer exists, so an
idle notch costs nothing); the daemon sends the current list on every change and when a phone connects.
"""
import asyncio
import json
import logging
import os
import secrets
import shutil
import time
from pathlib import Path

import pc_tools
from pc_tools import Tool, ToolError, _int, _schema, clean

log = logging.getLogger("companion.notices")

TIMER_FILE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "companion" / "timers.json"
MAX_TIMERS = 10
MAX_WATCHES = 5
MAX_SECONDS = 24 * 3600
LATE_LIMIT = 3600          # a timer that came due while the daemon was down is announced up to an hour late, then dropped
WATCH_POLL = 2.0
SOUND = Path("/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga")
DONE_SOUND = Path("/usr/share/sounds/freedesktop/stereo/complete.oga")


async def play(path: Path):
    """Play a short sound if the machine can (best effort, never raises)."""
    try:
        player = shutil.which("paplay") or shutil.which("pw-play")
        if player and path.exists():
            await asyncio.create_subprocess_exec(player, str(path), env=pc_tools.desktop_env(),
                                                 stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                                                 stderr=asyncio.subprocess.DEVNULL)
    except Exception:
        log.debug("couldn't play a sound")


def fmt(secs: float) -> str:
    secs = max(0, int(round(secs)))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class Timers:
    def __init__(self, fire, sync, path: Path = TIMER_FILE, clock=time.time):
        """fire(label, late_secs) announces a due timer; sync(items) pushes [{id,label,end}] to the notch."""
        self.fire_cb, self.sync_cb, self.path, self.clock = fire, sync, path, clock
        self.items = {}      # id -> {"label", "end"}
        self._tasks = {}

    # ---- persistence ----
    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.items))
            tmp.chmod(0o600)
            tmp.replace(self.path)
        except OSError as ex:
            log.warning("can't save timers: %s", ex)

    def load(self):
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for tid, t in raw.items():
            if isinstance(t, dict) and isinstance(t.get("end"), (int, float)) and isinstance(t.get("label"), str):
                self.items[str(tid)[:12]] = {"label": clean(t["label"], 40), "end": float(t["end"])}

    # ---- operations ----
    def listing(self) -> list:
        return sorted(({"id": i, "label": t["label"], "end": t["end"]} for i, t in self.items.items()), key=lambda x: x["end"])

    def add(self, seconds: int, label: str) -> str:
        if len(self.items) >= MAX_TIMERS:
            raise ToolError(f"there are already {MAX_TIMERS} timers; cancel one first")
        tid = secrets.token_hex(3)
        self.items[tid] = {"label": clean(label, 40) or "Timer", "end": self.clock() + seconds}
        self._save()
        self._schedule(tid)
        self._push()
        return tid

    def cancel(self, which: str) -> int:
        ids = list(self.items) if which == "all" else [which] if which in self.items else []
        for i in ids:
            self.items.pop(i, None)
            t = self._tasks.pop(i, None)
            if t:
                t.cancel()
        if ids:
            self._save()
            self._push()
        return len(ids)

    def _push(self):
        try:
            self.sync_cb(self.listing())
        except Exception:
            log.debug("timer sync failed", exc_info=True)

    def _schedule(self, tid: str):
        self._tasks[tid] = asyncio.ensure_future(self._wait(tid))

    async def _wait(self, tid: str):
        try:
            t = self.items.get(tid)
            if t is None:
                return
            await asyncio.sleep(max(0.0, t["end"] - self.clock()))
            t = self.items.pop(tid, None)
            self._tasks.pop(tid, None)
            if t is None:
                return
            self._save()
            self._push()
            try:
                await self.fire_cb(t["label"], max(0.0, self.clock() - t["end"]))
            except Exception:
                log.debug("timer announce failed", exc_info=True)
        except asyncio.CancelledError:
            raise

    def start(self):
        """Load saved timers and arm them (after a restart). Ones that came due while we were down are announced
        now (if less than an hour late) or dropped."""
        self.load()
        for tid, t in list(self.items.items()):
            if self.clock() - t["end"] > LATE_LIMIT:
                del self.items[tid]
            else:
                self._schedule(tid)
        self._save()

    def stop(self):
        for t in self._tasks.values():
            t.cancel()
        self._tasks.clear()


class TimerTool(Tool):
    needs_desktop = False
    name = "timer"
    description = ("Set, list or cancel timers / reminders. When one ends the PC's notch shows the label and plays a sound. "
                   "Use seconds (e.g. 10 minutes = 600). To cancel, pass the timer's id from a list, or id \"all\".")
    schema = _schema({"action": {"type": "string", "enum": ["set", "list", "cancel"]},
                      "seconds": {"type": "integer"}, "label": {"type": "string"}, "id": {"type": "string"}}, ["action"])
    fallback_summary = "Use a timer"

    def __init__(self, timers: Timers):
        self.timers = timers

    def validate(self, args):
        act = args.get("action")
        if act == "set":
            return {"action": "set", "seconds": _int(args.get("seconds"), 1, MAX_SECONDS, "seconds"),
                    "label": clean(str(args.get("label") or ""), 40)}
        if act == "list":
            return {"action": "list"}
        if act == "cancel":
            tid = str(args.get("id") or "")
            if not tid or len(tid) > 12:
                raise ToolError("which timer? pass its id, or \"all\"")
            return {"action": "cancel", "id": tid}
        raise ToolError("action must be set, list or cancel")

    def summary(self, a):
        if a["action"] == "set":
            return f"Set a timer for {fmt(a['seconds'])}" + (f": {a['label']}" if a["label"] else "")
        return "List timers" if a["action"] == "list" else "Cancel timer"

    async def run(self, a):
        if a["action"] == "set":
            tid = self.timers.add(a["seconds"], a["label"])
            return f"Timer {tid} set for {fmt(a['seconds'])}" + (f" ({a['label']})" if a["label"] else "") + ". The notch will show it and chime."
        if a["action"] == "list":
            items = self.timers.listing()
            now = self.timers.clock()
            return "\n".join(f"{i['id']}: {i['label']}, {fmt(i['end'] - now)} left" for i in items) or "No timers running"
        n = self.timers.cancel(a["id"])
        return f"Cancelled {n} timer(s)" if n else "No timer with that id"


class Watches:
    """'Tell me when that finishes': poll a PID until it is gone (or reused by another process)."""

    def __init__(self, announce, poll: float = WATCH_POLL, info=None):
        self.announce, self.poll = announce, poll
        self.info = info or __import__("procs").info
        self.tasks = {}

    def add(self, pid: int, label: str = "") -> str:
        if len(self.tasks) >= MAX_WATCHES:
            raise ToolError(f"already watching {MAX_WATCHES} processes")
        if pid in self.tasks:
            raise ToolError("already watching that process")
        me = self.info(pid)       # ToolError if it isn't running
        name = clean(label, 40) or me["name"]
        self.tasks[pid] = asyncio.ensure_future(self._watch(pid, me["start"], name))
        return name

    async def _watch(self, pid: int, start: int, name: str):
        try:
            while True:
                await asyncio.sleep(self.poll)
                try:
                    now = self.info(pid)
                except ToolError:
                    break
                if now["start"] != start:        # the PID was reused: the original is gone
                    break
            try:
                await self.announce(name)
            except Exception:
                log.debug("watch announce failed", exc_info=True)
        finally:
            self.tasks.pop(pid, None)

    def stop(self):
        for t in list(self.tasks.values()):
            t.cancel()


class WatchProcessTool(Tool):
    needs_desktop = False
    name = "watch_process"
    description = ("Tell Osian when a running process finishes (a build, download, install, game update): the notch shows "
                   "it and chimes. Find the PID with list_processes first. It only watches; it can't tell if it succeeded.")
    schema = _schema({"pid": {"type": "integer"}, "label": {"type": "string"}}, ["pid"])
    fallback_summary = "Watch a process"

    def __init__(self, watches: Watches):
        self.watches = watches

    def validate(self, args):
        return {"pid": _int(args.get("pid"), 2, 4_194_304, "pid"), "label": clean(str(args.get("label") or ""), 40)}

    def summary(self, a):
        return f"Tell you when PID {a['pid']} finishes"

    async def run(self, a):
        name = self.watches.add(a["pid"], a["label"])
        return f"Watching {name} (PID {a['pid']}). The notch will tell Osian when it ends."
