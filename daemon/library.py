"""What the phone's Activity screen shows and edits: the audit log (read-only), memory (add / edit /
forget, through the same MemoryStore checks the AI's tools use) and routines (read-only: they live in
ai.toml, which holds the API key and decides what may run, so the phone never edits it).
PROTOCOL.md "Activity, memory and routines".
"""
import logging

import memory as memory_mod
from pc_tools import clean

log = logging.getLogger("companion.library")

MAX_AUDIT = 200
KEEP_KEYS = ("ts", "tool", "summary", "approval", "result", "detail", "session")


class Library:
    def __init__(self, audit=None, store=None, routines=None):
        self.audit, self.store, self.routines = audit, store, routines or {}

    def caps(self) -> list:
        return [c for c, on in (("audit", self.audit), ("memory", self.store), ("routines", self.routines)) if on]

    def audit_items(self, n) -> list:
        n = n if isinstance(n, int) and not isinstance(n, bool) else 50
        n = max(1, min(n, MAX_AUDIT))
        out = []
        for e in self.audit.tail(n) if self.audit else []:
            if isinstance(e, dict):
                out.append({k: clean(str(e[k]), 200) for k in KEEP_KEYS if k in e})
        return out

    def memory_view(self) -> dict:
        entries = self.store.entries() if self.store else []
        return {"items": [{"id": e.id, "text": e.text, "created": e.created} for e in entries],
                "max": memory_mod.MAX_ENTRIES, "max_text": memory_mod.MAX_TEXT,
                "broken": bool(getattr(self.store, "_broken", False))}

    def memory_op(self, m: dict):
        """(ok, msg) for memory_add / memory_edit / memory_forget. Never raises."""
        if not self.store:
            return False, "memory isn't available"
        try:
            t, text, mid = m.get("t"), m.get("text"), m.get("id")
            if t == "memory_add":
                _, replaced = self.store.add(text)
                self._log("Memory added" + (" (updated a similar one)" if replaced else ""))
                return True, "Updated an existing memory" if replaced else "Saved"
            if not isinstance(mid, str):
                return False, "no memory chosen"
            if t == "memory_edit":
                self.store.update(mid, text)
                self._log("Memory edited")
                return True, "Saved"
            if t == "memory_forget":
                self.store.forget(mid)
                self._log("Memory forgotten")
                return True, "Forgotten"
        except memory_mod.MemoryError_ as ex:
            return False, str(ex)[:160]
        except OSError:
            return False, "couldn't write the memory file"
        return False, "unknown memory request"

    def _log(self, summary: str):
        if self.audit:
            self.audit.record("memory", summary, "phone", "ok")      # what changed isn't logged, only that it did

    def routine_items(self) -> list:
        return [{"name": r.name, "description": clean(r.description, 200), "risk": r.risk,
                 "steps": [clean(s.summary, 120) for s in r.steps]} for _, r in sorted(self.routines.items())]
