"""
Which desktop session (if any) is running right now.

The daemon starts with the user manager at boot (linger), before anyone logs in, and keeps
running across logins and logouts. So the session variables it was started with are useless:
it re-reads them from the systemd user manager, where uwsm (Hyprland) and Plasma export them
when their session starts, and only believes them while the sockets they name exist.
"""
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger("companion")

SESSION_VARS = ("WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY", "HYPRLAND_INSTANCE_SIGNATURE", "XDG_CURRENT_DESKTOP",
                "XDG_SESSION_TYPE", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION", "KDE_FULL_SESSION")
# Processes of a running desktop whose environment holds the session variables, best first.
# (kwin_wayland itself isn't readable: it runs with extra capabilities, so it's not dumpable.)
SESSION_PROCS = ("plasmashell", "Xwayland", "Hyprland", ".Hyprland-wrapped", "kwin_wayland")
X11_DIR = Path("/tmp/.X11-unix")
NO_DESKTOP = "no desktop session yet (the PC is at the login screen)"


def _runtime_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")


def _manager_env() -> dict:
    try:
        out = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True,
                             text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    env = {}
    for line in out.splitlines():
        k, sep, v = line.partition("=")
        if sep and k in SESSION_VARS and not v.startswith("$'"):  # skip shell-quoted oddities
            env[k] = v
    return env


def _proc_env() -> dict:
    """Session variables from a running desktop process of ours (fallback for the user manager)."""
    uid = os.getuid()
    found = {}  # rank in SESSION_PROCS -> env; one pass over /proc
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != uid:
                continue
            name = (proc / "comm").read_text().strip()
            if name not in SESSION_PROCS or SESSION_PROCS.index(name) in found:
                continue
            raw = (proc / "environ").read_bytes()
        except OSError:
            continue
        env = {}
        for item in raw.split(b"\0"):
            k, sep, v = item.decode(errors="replace").partition("=")
            if sep and k in SESSION_VARS:
                env[k] = v
        if env.get("WAYLAND_DISPLAY") or env.get("DISPLAY"):
            found[SESSION_PROCS.index(name)] = env
    return found[min(found)] if found else {}


def _x_socket(display: str) -> Path:
    num = display.split(":")[-1].split(".")[0]  # ":0" or ":0.0" -> "0"
    return X11_DIR / f"X{num}"


def _alive(env: dict) -> dict:
    """Drop variables that point at a compositor, X server or cookie that isn't there any more."""
    rt = _runtime_dir()
    env = dict(env)
    if env.get("WAYLAND_DISPLAY") and not (rt / env["WAYLAND_DISPLAY"]).exists():
        env.pop("WAYLAND_DISPLAY")
    if env.get("DISPLAY") and not _x_socket(env["DISPLAY"]).exists():
        env.pop("DISPLAY")
    if env.get("XAUTHORITY") and not Path(env["XAUTHORITY"]).is_file():
        env.pop("XAUTHORITY")
    if env.get("HYPRLAND_INSTANCE_SIGNATURE") and not (rt / "hypr" / env["HYPRLAND_INSTANCE_SIGNATURE"]).is_dir():
        env.pop("HYPRLAND_INSTANCE_SIGNATURE")
    if "WAYLAND_DISPLAY" not in env and "DISPLAY" not in env:
        return {}  # no display at all: nothing else about the session is meaningful
    return env


def current(read_env=_manager_env, read_proc=_proc_env) -> dict:
    """The live session's variables: the user manager's, completed from a desktop process when
    the manager lacks the display ones (e.g. XAUTHORITY, a random path per login), all checked."""
    env = _alive(read_env())
    if not (env.get("WAYLAND_DISPLAY") and env.get("DISPLAY") and env.get("XAUTHORITY")):
        extra = _alive(read_proc())
        env = _alive({**extra, **env}) if env else extra
    return env


def launch_env(read_env=_manager_env, read_proc=_proc_env):
    """A complete environment for starting a desktop app now, read fresh (XAUTHORITY changes
    every login), or None when no graphical session is running."""
    live = current(read_env, read_proc)
    if not (live.get("WAYLAND_DISPLAY") or live.get("DISPLAY")):
        return None
    env = {k: v for k, v in os.environ.items() if k not in SESSION_VARS}
    env.update(live)
    env["XDG_RUNTIME_DIR"] = str(_runtime_dir())
    return env


def refresh(read_env=_manager_env, read_proc=_proc_env) -> bool:
    """Bring os.environ's session variables in line with what's running. True if anything changed."""
    want = current(read_env, read_proc)
    changed = False
    for k in SESSION_VARS:
        if os.environ.get(k) != want.get(k):
            changed = True
            if k in want:
                os.environ[k] = want[k]
            else:
                os.environ.pop(k, None)
    return changed


def desktop_ready() -> bool:
    w = os.environ.get("WAYLAND_DISPLAY")
    return bool(w) and (_runtime_dir() / w).exists()


def describe() -> str:
    if not desktop_ready():
        return "none (login screen)"
    return os.environ.get("XDG_CURRENT_DESKTOP") or "unknown desktop"
