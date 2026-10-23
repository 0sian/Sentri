"""
What the AI did, one JSON line per tool call, so Osian can ask "what did it do while I wasn't
looking?". Never stores tool output (no screenshots, clipboard or command output); typed text
is cut to 40 characters. File: ~/.local/state/companion/audit.jsonl, rotated at ~5 MB, 3 kept.
"""
import datetime
import json
import logging
import os
import re
from pathlib import Path

log = logging.getLogger("companion")

AUDIT_FILE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "companion" / "audit.jsonl"
MAX_BYTES = 5 * 1024 * 1024
KEEP = 3  # audit.jsonl, audit.jsonl.1, audit.jsonl.2
TYPED_LIMIT = 40
TYPING_TOOLS = {"type_text", "type"}


def _cut_typed(summary: str) -> str:
    """'Type "a long sentence..." into foot' -> the quoted text cut to TYPED_LIMIT chars."""
    first, last = summary.find('"'), summary.rfind('"')
    if first == -1 or last <= first:
        return summary
    typed = summary[first + 1:last]
    if len(typed) > TYPED_LIMIT:
        typed = typed[:TYPED_LIMIT] + "…"
    return summary[:first + 1] + typed + summary[last:]


class AuditLog:
    def __init__(self, path: Path = AUDIT_FILE):
        self.path = path

    def record(self, tool: str, summary: str, approval: str, result: str, session: str = None, detail: str = None):
        """approval: auto / allowed / denied / timeout. result: ok / error / not run.
        detail: why it failed (our own error message), for result=error."""
        summary = re.sub(r"[\x00-\x1f\x7f]", " ", str(summary))[:200]
        if tool in TYPING_TOOLS:
            summary = _cut_typed(summary)
        entry = {"ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "tool": tool,
                 "summary": summary, "approval": approval, "result": result}
        if session:
            entry["session"] = session
        if detail:
            entry["detail"] = re.sub(r"[\x00-\x1f\x7f]", " ", str(detail))[:120]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > MAX_BYTES:
                self._rotate()
            with open(self.path, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            os.chmod(self.path, 0o600)
        except OSError as ex:
            log.warning("can't write the audit log: %s", ex)

    def _rotate(self):
        for i in range(KEEP - 1, 0, -1):
            src = self.path.with_name(f"{self.path.name}.{i - 1}" if i > 1 else self.path.name)
            if src.exists():
                src.replace(self.path.with_name(f"{self.path.name}.{i}"))

    def tail(self, n: int) -> list:
        """The last n entries, oldest first, reading into rotated files if needed."""
        out = []
        for i in range(KEEP):
            f = self.path if i == 0 else self.path.with_name(f"{self.path.name}.{i}")
            try:
                lines = f.read_text().splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
                if len(out) >= n:
                    return list(reversed(out))
        return list(reversed(out))
