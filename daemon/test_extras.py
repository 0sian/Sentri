#!/usr/bin/env python3
"""Auth limiting, Wake-on-LAN MAC, close codes, token rotation and the audit log."""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import tempfile
from pathlib import Path

import websockets

import ai
import audit
import companion_daemon as cd
import pc_tools

TMP = Path(tempfile.mkdtemp())
TOKEN = "test-token"
PORT = 18805
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class FakeUInput:
    def __init__(self, *a, **k):
        pass

    def write(self, *a):
        pass

    def syn(self):
        pass

    def close(self):
        pass


cd.UInput = FakeUInput


async def try_auth(port, token):
    ws = await websockets.connect(f"ws://127.0.0.1:{port}")
    try:
        ch = json.loads(await ws.recv())
    except websockets.ConnectionClosed as ex:
        return None, ex.rcvd.code if ex.rcvd else None
    await ws.send(json.dumps({"t": "auth", "hmac": hmac.new(token.encode(), ch["nonce"].encode(), hashlib.sha256).hexdigest()}))
    reply = json.loads(await ws.recv())
    return ws, reply


def limiter_tests():
    now = [1000.0]
    lim = cd.AuthLimiter(clock=lambda: now[0])
    for _ in range(4):
        lim.failed("1.2.3.4")
    check("limiter: 4 failures, no wait", lim.wait("1.2.3.4") == 0)
    lim.failed("1.2.3.4")
    check("limiter: 5th failure -> 30 s", lim.wait("1.2.3.4") == 30)
    now[0] += 31
    check("limiter: free again after 30 s", lim.wait("1.2.3.4") == 0)
    for _ in range(15):
        lim.failed("1.2.3.4")
    check("limiter: 20 failures -> 10 min", lim.wait("1.2.3.4") == 600)
    check("limiter: other addresses unaffected", lim.wait("5.6.7.8") == 0)
    now[0] += 3601
    check("limiter: forgotten after an hour quiet", lim.wait("1.2.3.4") == 0 and "1.2.3.4" not in lim.fails)
    lim.failed("9.9.9.9")
    lim.succeeded("9.9.9.9")
    check("limiter: success clears", "9.9.9.9" not in lim.fails)


def wol_tests():
    def nic(name, wired=True, wake="enabled", mac="02:00:5e:10:00:01"):
        d = TMP / "net" / name
        (d / "device" / "power").mkdir(parents=True, exist_ok=True)
        (d / "type").write_text("1\n")
        (d / "address").write_text(mac + "\n")
        (d / "device" / "power" / "wakeup").write_text(wake + "\n")
        if not wired:
            (d / "wireless").mkdir(exist_ok=True)
    nic("eth0")
    nic("eth1", wake="disabled")
    nic("wlan0", wired=False)
    route = "1.1.1.1 via 192.168.1.1 dev {} src 192.168.1.100"
    check("WoL: wired + wakeup enabled -> MAC", cd.wol_mac(TMP / "net", route.format("eth0")) == "02:00:5e:10:00:01")
    check("WoL: wakeup disabled -> no MAC", cd.wol_mac(TMP / "net", route.format("eth1")) is None)
    check("WoL: wireless -> no MAC", cd.wol_mac(TMP / "net", route.format("wlan0")) is None)
    check("WoL: no route -> no MAC", cd.wol_mac(TMP / "net", "") is None)


def token_tests():
    cd.TOKEN_FILE = TMP / "token"
    cd.CONFIG_DIR = TMP
    t1 = cd.write_new_token()
    t2 = cd.write_new_token()
    check("rotate: new 192-bit token, mode 600, replaces the old one",
          t1 != t2 and cd.token_bits(t2) >= 192 and (TMP / "token").read_text().strip() == t2
          and ((TMP / "token").stat().st_mode & 0o777) == 0o600)
    (TMP / "token").write_text("short\n")
    import logging
    seen = []
    h = logging.Handler()
    h.emit = lambda r: seen.append(r.getMessage())
    logging.getLogger("companion").addHandler(h)
    cd.load_or_create_token()
    logging.getLogger("companion").removeHandler(h)
    check("short token -> warning naming --rotate-token", any("--rotate-token" in m for m in seen), seen)


async def server_tests():
    srv = cd.Server(cd.VirtualInput("us"), TOKEN, 400.0)
    real_wol = cd.wol_mac
    cd.wol_mac = lambda: "aa:bb:cc:dd:ee:ff"
    async with websockets.serve(srv.handler, "127.0.0.1", PORT):
        ws, ok = await try_auth(PORT, TOKEN)
        check("ok carries the WoL MAC when available", ok.get("mac") == "aa:bb:cc:dd:ee:ff", ok)
        await ws.close()
        cd.wol_mac = lambda: None
        ws, ok = await try_auth(PORT, TOKEN)
        check("no MAC field when WoL can't work", "mac" not in ok, ok)
        await ws.close()
        for _ in range(5):
            ws, reply = await try_auth(PORT, "wrong")
            await ws.close()
        _, code = await try_auth(PORT, TOKEN)
        check("after 5 failed logins the address is refused (1008), even with the right token", code == 1008, code)
        srv.limiter.fails.clear()
        ws, ok = await try_auth(PORT, TOKEN)
        check("success afterwards clears the count", ok["t"] == "ok" and "127.0.0.1" not in srv.limiter.fails)
        await ws.close()
    cd.wol_mac = real_wol

    # leaving serve() (what SIGTERM now does) closes phones with 1001, not a dropped socket
    srv = cd.Server(cd.VirtualInput("us"), TOKEN, 400.0)
    async with websockets.serve(srv.handler, "127.0.0.1", PORT + 1):
        ws, ok = await try_auth(PORT + 1, TOKEN)
    try:
        await asyncio.wait_for(ws.recv(), 2)
        code = None
    except websockets.ConnectionClosed as ex:
        code = ex.rcvd.code if ex.rcvd else None
    check("shutdown closes with 1001", code == 1001, code)

    # replaced -> 4000 still
    srv = cd.Server(cd.VirtualInput("us"), TOKEN, 400.0)
    async with websockets.serve(srv.handler, "127.0.0.1", PORT + 2):
        ws1, _ = await try_auth(PORT + 2, TOKEN)
        ws2, _ = await try_auth(PORT + 2, TOKEN)
        try:
            await asyncio.wait_for(ws1.recv(), 2)
            code = None
        except websockets.ConnectionClosed as ex:
            code = ex.rcvd.code if ex.rcvd else None
        check("replaced client closed with 4000", code == 4000, code)
        await ws2.close()


async def audit_tests():
    log = audit.AuditLog(TMP / "audit" / "audit.jsonl")
    log.record("type_text", 'Type "' + "x" * 100 + '" into firefox', "allowed", "ok")
    log.record("open_url", "Open example.com\x1b[2J in Vivaldi", "denied", "not run")
    rows = log.tail(10)
    check("audit: typed text cut to 40 chars, control chars stripped, fields present",
          rows[0]["summary"] == 'Type "' + "x" * 40 + '…" into firefox' and "\x1b" not in rows[1]["summary"]
          and rows[1]["approval"] == "denied" and rows[1]["result"] == "not run" and "ts" in rows[0], rows)
    check("audit file is private", (os.stat(log.path).st_mode & 0o777) == 0o600)
    audit.MAX_BYTES = 300
    for i in range(30):
        log.record("get_status", f"Check status {i}", "auto", "ok")
    files = sorted(p.name for p in log.path.parent.iterdir())
    check("audit rotates and keeps 3 files", files == ["audit.jsonl", "audit.jsonl.1", "audit.jsonl.2"], files)
    tail = log.tail(5)
    check("tail reads the newest entries in order", [r["summary"] for r in tail] == [f"Check status {i}" for i in range(25, 30)],
          [r["summary"] for r in tail])
    audit.MAX_BYTES = 5 * 1024 * 1024

    # wired into the assistant: auto / allowed / denied, plus recent_actions
    class T(pc_tools.Tool):
        name, risk = "gated", "low"
        schema = pc_tools._schema({"n": {"type": "integer"}}, ["n"])

        def validate(self, a):
            return {"n": a["n"]}

        def summary(self, a):
            return f"Gated {a['n']}"

        async def run(self, a):
            return "done"

    class A(T):
        name, risk = "auto_thing", None

        def summary(self, a):
            return f"Auto {a['n']}"

    class Backend:
        def __init__(self):
            self.scripts = []

        async def complete(self, system, messages, on_text, tools, **kw):
            return self.scripts.pop(0)

    log2 = audit.AuditLog(TMP / "a2" / "audit.jsonl")
    be = Backend()
    a = ai.Assistant(ai.AIConfig(api_key="k"), be, usage_file=TMP / "u.json", tools={"gated": T(), "auto_thing": A()},
                     audit=log2)
    answers = iter([True, False])

    async def confirm(*x):
        return (next(answers), "user")
    for name, n in (("auto_thing", 1), ("gated", 2), ("gated", 3)):
        be.scripts += [ai.Reply([{"type": "tool_use", "id": "t", "name": name, "input": {"n": n}}], "tool_use", 1, 1),
                       ai.Reply([{"type": "text", "text": "ok"}], "end_turn", 1, 1)]
        assert a.claim()
        await a.turn("x", lambda s: asyncio.sleep(0), lambda e: asyncio.sleep(0), None, confirm)
    got = [(r["tool"], r["summary"], r["approval"], r["result"]) for r in log2.tail(10)]
    check("assistant audits auto / allowed / denied calls",
          got == [("auto_thing", "Auto 1", "auto", "ok"), ("gated", "Gated 2", "allowed", "ok"),
                  ("gated", "Gated 3", "denied", "not run")], got)
    out = await a.tools["recent_actions"].run(a.tools["recent_actions"].validate({"n": 2}))
    check("recent_actions reads the log back", "Gated 2 [allowed, ok]" in out and "Gated 3 [denied, not run]" in out
          and "Auto 1" not in out, out)


async def main():
    limiter_tests()
    wol_tests()
    token_tests()
    await server_tests()
    await audit_tests()
    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        sys.exit(1)
    print("all tests passed")


asyncio.run(main())
