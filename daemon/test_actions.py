#!/usr/bin/env python3
"""Quick actions (phone Quick actions screen): whitelist, confirmation, deferred follow-ups, routines,
and the protocol wiring in Server._quick. A fake System stands in for the machine."""
import asyncio
import sys
import types

import actions
import companion_daemon as cd
import pc_tools

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class FakeSystem:
    def __init__(self, kind="hyprland", caelestia=True):
        self._kind, self.caelestia = kind, caelestia
        self.calls, self.states, self.block = [], {"CanSuspend": "yes", "CanReboot": "yes", "CanPowerOff": "yes"}, []
        self.toggle = "false"

    def kind(self): return self._kind
    def has(self, cmd): return self.caelestia if cmd == "caelestia" else True

    async def run(self, *argv):
        self.calls.append(("run",) + argv)
        if argv[-1] in ("isEnabled", "isDndEnabled"):
            return self.toggle + "\n"
        return ""

    async def run_plain(self, *argv): self.calls.append(("plain",) + argv); return ""
    async def detach(self, *argv): self.calls.append(("detach",) + argv)
    async def can(self, what): return self.states[what]
    async def blockers(self): return self.block


class Routine:
    def __init__(self, name, risk): self.name, self.risk = name, risk
    def card(self): return f"Routine {self.name}: open things"


class FakeRunRoutine:
    def __init__(self): self.ran = []
    async def run(self, a): self.ran.append(a["routine"].name); return "Ran it fine\nstep 2 ok"


class FakeAudit:
    def __init__(self): self.rows = []
    def record(self, *a, **k): self.rows.append((a, k))


def make(**kw):
    sy = kw.pop("system", FakeSystem())
    rr = FakeRunRoutine()
    au = FakeAudit()
    return actions.Actions({"work_mode": Routine("work_mode", None), "wipe": Routine("wipe", "high")}, rr, au,
                           lambda: kw.get("wol", False), sy), sy, rr, au


async def expect_error(coro, text):
    try:
        await coro
    except pc_tools.ToolError as ex:
        return text in str(ex), str(ex)
    return False, "no error"


async def main():
    actions.AFTER_DELAY = 0.01
    actions.LOCK_SETTLE = 0.01
    a, sy, rr, au = make()
    ids = [i["id"] for i in a.listing()]
    check("list has the session, power, desktop and routine actions",
          ids == ["lock", "sleep", "screen_off", "logout", "game_mode", "dnd", "restart", "shutdown", "routine:wipe", "routine:work_mode"], ids)
    items = {i["id"]: i for i in a.listing()}
    check("destructive ones are danger + need confirmation", all(items[x].get("danger") and items[x].get("confirm") for x in ("logout", "restart", "shutdown")))
    check("shutdown card warns when Wake-on-LAN isn't set up", "Wake-on-LAN" in items["shutdown"]["confirm"])
    check("shutdown card doesn't warn when it is", "Wake-on-LAN" not in make(wol=True)[0].listing()[7]["confirm"])
    check("lock/sleep/screen off need no confirmation", not any("confirm" in items[x] for x in ("lock", "sleep", "screen_off")))
    check("risky routine asks, harmless one doesn't", "confirm" in items["routine:wipe"] and "confirm" not in items["routine:work_mode"])
    check("no caelestia -> no desktop toggles", "game_mode" not in [i["id"] for i in make(system=FakeSystem(caelestia=False))[0].listing()])
    check("on KDE -> no caelestia toggles", "dnd" not in [i["id"] for i in make(system=FakeSystem(kind="kde"))[0].listing()])

    # lock
    r = await a.run("lock")
    check("lock on Hyprland uses caelestia's lock", sy.calls[-1] == ("run", "caelestia", "shell", "lock", "lock") and r.msg == "Locked", sy.calls)
    k, ks = make(system=FakeSystem(kind="kde"))[:2]
    await k.run("lock")
    check("lock on KDE uses loginctl", ks.calls[-1] == ("run", "loginctl", "lock-sessions"), ks.calls)
    ok, d = await expect_error(make(system=FakeSystem(kind=None))[0].run("lock"), "login screen")
    check("lock at the login screen: clear refusal", ok, d)

    # screen off
    sy.calls.clear(); await a.run("screen_off")
    check("screen off on Hyprland = dpms off", sy.calls[0][:3] == ("run", "hyprctl", "dispatch") and "off" in sy.calls[0][3], sy.calls)
    await k.run("screen_off")
    check("screen off on KDE = kscreen-doctor", ks.calls[-1] == ("run", "kscreen-doctor", "--dpms", "off"), ks.calls)

    # sleep: replies first, then locks, then suspends
    sy.calls.clear()
    r = await a.run("sleep")
    check("sleep: nothing happens before the reply", sy.calls == [] and r.msg == "Going to sleep" and r.after is not None, sy.calls)
    await r.after()
    check("sleep: lock then suspend", [c[1:] for c in sy.calls] == [("caelestia", "shell", "lock", "lock"), ("systemctl", "suspend")], sy.calls)
    sy.states["CanSuspend"] = "inhibited"; sy.block = ["media-idle-inhibit: Media is actively playing"]
    ok, d = await expect_error(a.run("sleep"), "media-idle-inhibit")
    check("sleep blocked by an inhibitor says who", ok, d)
    sy.states["CanSuspend"] = "na"
    ok, d = await expect_error(a.run("sleep"), "isn't available")
    check("sleep unavailable is reported", ok, d)
    sy.states["CanSuspend"] = "yes"
    nd = make(system=FakeSystem(kind=None))[0]
    r = await nd.run("sleep"); sy2 = nd.sys; await r.after()
    check("sleep at the login screen skips the lock", [c[1:] for c in sy2.calls] == [("systemctl", "suspend")], sy2.calls)

    # confirmation
    sy.calls.clear()
    ok, d = await expect_error(a.run("logout"), "confirmation")
    check("logout without confirmed refuses and does nothing", ok and sy.calls == [], (d, sy.calls))
    ok, d = await expect_error(a.run("logout", "yes"), "confirmation")
    check("confirmed must be exactly true", ok, d)
    r = await a.run("logout", True)
    check("logout answers first", sy.calls == [] and r.msg == "Logging out")
    await r.after()
    check("logout uses the detached SDDM-safe script when present",
          sy.calls[0][0] == "detach" and (sy.calls[0][-1].endswith("caelestia-logout.sh") or sy.calls[0][1:] == ("uwsm", "stop")), sy.calls)
    kr = await k.run("logout", True); await kr.after()
    check("logout on KDE uses org.kde.Shutdown", ks.calls[-1][:3] == ("run", "qdbus6", "org.kde.Shutdown") and ks.calls[-1][-1].endswith("logout"), ks.calls)
    sy.calls.clear()
    r = await a.run("restart", True); await r.after()
    check("restart", sy.calls == [("plain", "systemctl", "reboot")], sy.calls)
    sy.calls.clear()
    r = await a.run("shutdown", True); await r.after()
    check("shutdown", sy.calls == [("plain", "systemctl", "poweroff")], sy.calls)
    sy.states["CanReboot"] = "no"
    ok, d = await expect_error(a.run("restart", True), "isn't allowed")
    check("restart refused by logind is reported", ok, d)

    # toggles
    sy.toggle = "true"
    r = await a.run("game_mode")
    check("game mode toggles and reports the new state", r.msg == "Game mode on" and ("run", "caelestia", "shell", "gameMode", "toggle") in sy.calls, (r.msg, sy.calls))
    sy.toggle = "false"
    check("dnd reports off", (await a.run("dnd")).msg == "Do not disturb off")

    # routines
    r = await a.run("routine:work_mode")
    check("harmless routine runs without confirmation", rr.ran == ["work_mode"] and r.msg == "Ran it fine", (rr.ran, r.msg))
    ok, d = await expect_error(a.run("routine:wipe"), "confirmation")
    check("risky routine needs confirmation", ok and rr.ran == ["work_mode"], d)
    await a.run("routine:wipe", True)
    check("risky routine runs once confirmed", rr.ran == ["work_mode", "wipe"])

    # whitelist
    for bad in ("rm -rf /", "lock; reboot", "routine:nope", "", None, 5):
        ok, d = await expect_error(a.run(bad), "unknown")
        if not ok:
            check(f"unknown id {bad!r} refused", False, d)
            break
    else:
        check("unknown / malformed ids are refused", True)

    # audit
    check("every run is audited, errors too", len(au.rows) >= 10 and any(r[0][3] == "error" for r in au.rows) and all(r[0][0] == "quick_action" and r[0][2] == "phone button" for r in au.rows))

    # busy
    a2, s2, _, _ = make()
    gate = asyncio.Event()

    async def slow(*argv): await gate.wait(); return ""
    s2.run = slow
    t = asyncio.ensure_future(a2.run("lock"))
    await asyncio.sleep(0.02)
    ok, d = await expect_error(a2.run("lock"), "busy")
    gate.set(); await t
    check("a second action while one runs is refused", ok, d)

    # protocol wiring
    srv = cd.Server(None, "tok", 400, None, None, make()[0])
    sent = []

    async def send(m): sent.append(m)
    await srv._quick({"t": "actions_get"}, send)
    check("actions_get -> actions list", sent[-1]["t"] == "actions" and sent[-1]["items"][0]["id"] == "lock", sent)
    await srv._quick({"t": "action", "id": "lock", "rid": 7}, send)
    check("action -> action_result ok", sent[-1] == {"t": "action_result", "rid": 7, "id": "lock", "ok": True, "msg": "Locked"}, sent[-1])
    await srv._quick({"t": "action", "id": "logout", "rid": 8}, send)
    check("unconfirmed logout -> ok:false, nothing runs", sent[-1]["ok"] is False and "confirmation" in sent[-1]["msg"], sent[-1])
    n = len(sent)
    await srv._quick({"t": "action", "rid": 9}, send); await srv._quick({"t": "action", "id": 5, "rid": 1}, send); await srv._quick({"t": "action", "id": "lock", "rid": True}, send)
    check("malformed action messages are ignored", len(sent) == n)
    await srv._quick({"t": "action", "id": "sleep", "rid": 10}, send)
    await asyncio.sleep(0.2)
    check("deferred follow-up runs after the reply", srv.quick.sys.calls[-1] == ("plain", "systemctl", "suspend"), srv.quick.sys.calls)

    # inhibitor parsing against real-looking rows
    m = actions.INHIBITOR.match("Realtime Kit       0    root  943   rtkit-daemon    sleep      Demote realtime scheduling and stop canary. delay")
    m2 = actions.INHIBITOR.match("media-idle-inhibit 1000 user 75359 systemd-inhibit sleep:idle Media is actively playing                   block")
    check("inhibitor rows parse (names with spaces, block vs delay)", m and m["who"] == "Realtime Kit" and m["mode"] == "delay" and m2["who"] == "media-idle-inhibit" and m2["why"] == "Media is actively playing" and m2["mode"] == "block")

    if failures:
        print(f"{len(failures)} FAILED: {failures}"); sys.exit(1)
    print("all tests passed")

asyncio.run(main())
