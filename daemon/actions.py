"""Quick actions: a fixed list the phone's Quick actions screen can run with one tap (lock, sleep,
log out, screen off, restart, shut down, a couple of Caelestia toggles, and Osian's own routines).
No AI and no shell strings: every action is hard-coded argv built here, chosen by exact id.

Actions that end the session or the connection (sleep, log out, restart, shut down) answer first
and act a moment later, so the phone gets its reply. Ones with a `confirm` text are only run when the
phone says it showed that text and Osian tapped OK (`confirmed: true`).
"""
import asyncio
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import pc_tools
import session
from pc_tools import ToolError, clean

log = logging.getLogger("companion.actions")

LOGOUT_SCRIPT = Path.home() / ".local" / "bin" / "caelestia-logout.sh"   # the SDDM-bug workaround (a local workaround script)
AFTER_DELAY = 0.4      # let the reply reach the phone before the session or network goes away
LOCK_SETTLE = 0.8      # sleep: let the lock screen come up before suspending


# systemd-inhibit --list rows: WHO (may contain spaces) UID USER PID COMM WHAT WHY MODE
INHIBITOR = re.compile(r"^(?P<who>.+?)\s+\d+\s+\S+\s+\d+\s+\S+\s+(?P<what>\S+)\s+(?P<why>.+?)\s+(?P<mode>block|delay)\s*$")


@dataclass
class Action:
    id: str
    label: str
    group: str
    confirm: str = None
    danger: bool = False

    def listing(self) -> dict:
        d = {"id": self.id, "label": self.label, "group": self.group}
        if self.confirm:
            d["confirm"] = self.confirm
        if self.danger:
            d["danger"] = True
        return d


@dataclass
class Result:
    msg: str
    after: object = None     # async callable run after the reply has been sent


class System:
    """Everything that touches the machine, in one place so tests can swap it."""

    def kind(self):
        """'hyprland', 'kde' or None (login screen / unknown)."""
        if pc_tools._hyprland():
            return "hyprland"
        import kwin
        return "kde" if kwin.available() else None

    def has(self, cmd: str) -> bool:
        return shutil.which(cmd) is not None

    async def run(self, *argv: str) -> str:
        return await pc_tools.run(*argv, env=pc_tools.desktop_env())

    async def run_plain(self, *argv: str) -> str:      # system tools that need no desktop (systemctl, busctl)
        return await pc_tools.run(*argv)

    async def detach(self, *argv: str):
        """Start a process that must outlive the daemon's own cleanup (a logout kills us too)."""
        await asyncio.create_subprocess_exec(
            *argv, env=pc_tools.desktop_env(), stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True)

    async def can(self, what: str) -> str:
        """login1 CanSuspend/CanReboot/CanPowerOff: yes / no / na / challenge / inhibited."""
        out = await pc_tools.run("busctl", "--system", "call", "org.freedesktop.login1", "/org/freedesktop/login1",
                                 "org.freedesktop.login1.Manager", what)
        return out.split('"')[1] if '"' in out else "na"

    async def blockers(self) -> list:
        """['who: why'] for block inhibitors that stop a suspend."""
        try:
            out = await pc_tools.run("systemd-inhibit", "--list", "--no-pager", "--no-legend")
        except ToolError:
            return []
        rows = []
        for line in out.splitlines():
            m = INHIBITOR.match(line)
            if m and m["mode"] == "block" and "sleep" in m["what"]:
                rows.append(clean(f"{m['who']}: {m['why']}", 80))
        return rows


class Actions:
    def __init__(self, routines=None, run_routine=None, audit=None, wol_ready=lambda: False, system=None):
        """routines: {name: pc_tools.Routine}; run_routine: the RunRoutine tool; audit: AuditLog or None;
        wol_ready(): whether the PC can be woken over the network (shown on the shut down card)."""
        self.sys = system or System()
        self.routines = routines or {}
        self.run_routine = run_routine
        self.audit = audit
        self.wol_ready = wol_ready
        self.busy = asyncio.Lock()

    # ---- what the phone sees ----
    def items(self) -> list:
        out = [Action("lock", "Lock", "Session"), Action("sleep", "Sleep", "Session"),
               Action("screen_off", "Screen off", "Session"),
               Action("logout", "Log out", "Session", "Log out? Open apps will be closed.", True)]
        if self.sys.has("caelestia") and self.sys.kind() == "hyprland":
            out += [Action("game_mode", "Game mode", "Desktop"), Action("dnd", "Do not disturb", "Desktop")]
        wake = ("" if self.wol_ready() else " Wake-on-LAN isn't set up, so you'd need the power button to turn it back on.")
        out += [Action("restart", "Restart", "Power", "Restart the PC? Open apps will be closed.", True),
                Action("shutdown", "Shut down", "Power", "Shut the PC down?" + wake, True)]
        for name, r in sorted(self.routines.items()):
            out.append(Action(f"routine:{name}", name.replace("_", " ").capitalize(), "Routines",
                              clean(r.card(), 300) if r.risk else None, False))
        return out

    def listing(self) -> list:
        return [a.listing() for a in self.items()]

    # ---- running one ----
    async def run(self, aid, confirmed=False) -> Result:
        """Run one action by exact id. Raises ToolError with a message fit for the phone."""
        action = next((a for a in self.items() if a.id == aid), None)
        if action is None:
            raise ToolError("unknown action")
        if action.confirm and confirmed is not True:
            raise ToolError("needs confirmation")
        if self.busy.locked():
            raise ToolError("busy with another action")
        async with self.busy:
            try:
                res = await self._do(action)
            except ToolError as ex:
                self._audit(action, "error", str(ex))
                raise
            self._audit(action, "ok")
            return res

    def _audit(self, action: Action, result: str, detail: str = None):
        if self.audit:
            self.audit.record("quick_action", action.label, "phone button", result, detail=detail)

    def _need_desktop(self) -> str:
        kind = self.sys.kind()
        if kind is None:
            raise ToolError(session.NO_DESKTOP)
        return kind

    async def _lock(self, kind):
        if kind == "hyprland" and self.sys.has("caelestia"):
            await self.sys.run("caelestia", "shell", "lock", "lock")
        else:
            await self.sys.run("loginctl", "lock-sessions")

    async def _do(self, a: Action) -> Result:
        sys_, aid = self.sys, a.id
        if aid == "lock":
            await self._lock(self._need_desktop())
            return Result("Locked")
        if aid == "screen_off":
            kind = self._need_desktop()
            if kind == "hyprland":
                await sys_.run("hyprctl", "dispatch", 'hl.dsp.dpms({ action = "off" })')
            else:
                await sys_.run("kscreen-doctor", "--dpms", "off")
            return Result("Screen off. Touch the trackpad to wake it.")
        if aid == "sleep":
            state = await sys_.can("CanSuspend")
            if state == "inhibited":
                who = await sys_.blockers()
                raise ToolError("Can't sleep yet: " + (who[0] if who else "something is blocking it"))
            if state not in ("yes", "challenge"):
                raise ToolError("Sleep isn't available on this PC")
            kind = sys_.kind()

            async def after():
                if kind:
                    try:
                        await self._lock(kind)
                    except ToolError:
                        pass          # sleep anyway: a missing lock shouldn't leave the PC awake
                    await asyncio.sleep(LOCK_SETTLE)
                await sys_.run_plain("systemctl", "suspend")
            return Result("Going to sleep", after)
        if aid == "logout":
            kind = self._need_desktop()

            async def after():
                if kind == "hyprland":
                    if LOGOUT_SCRIPT.exists():
                        await sys_.detach("setsid", "-f", str(LOGOUT_SCRIPT))
                    else:
                        await sys_.detach("uwsm", "stop")
                else:
                    await sys_.run("qdbus6", "org.kde.Shutdown", "/Shutdown", "org.kde.Shutdown.logout")
            return Result("Logging out", after)
        if aid in ("restart", "shutdown"):
            what, verb, word = (("CanReboot", "reboot", "Restarting") if aid == "restart"
                                else ("CanPowerOff", "poweroff", "Shutting down"))
            if await sys_.can(what) not in ("yes", "challenge"):
                raise ToolError(f"{a.label} isn't allowed right now")

            async def after():
                await sys_.run_plain("systemctl", verb)
            return Result(word, after)
        if aid in ("game_mode", "dnd"):
            self._need_desktop()
            target, toggle, query = (("gameMode", "toggle", "isEnabled") if aid == "game_mode"
                                     else ("notifs", "toggleDnd", "isDndEnabled"))
            await sys_.run("caelestia", "shell", target, toggle)
            on = (await sys_.run("caelestia", "shell", target, query)).strip() == "true"
            return Result(f"{a.label} {'on' if on else 'off'}")
        if aid.startswith("routine:") and self.run_routine is not None:
            r = self.routines[aid.split(":", 1)[1]]
            out = await self.run_routine.run({"routine": r})
            return Result(clean(str(out).split("\n")[0] or f"Ran {r.name}", 160))
        raise ToolError("unknown action")


def spawn_after(res: Result):
    """Run a result's follow-up in the background after the reply went out (errors only logged)."""
    if res.after is None:
        return None

    async def go():
        await asyncio.sleep(AFTER_DELAY)
        try:
            await res.after()
        except Exception as ex:
            log.warning("follow-up failed: %s", ex)
    return asyncio.ensure_future(go())
