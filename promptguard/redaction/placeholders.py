"""Session-scoped placeholder numbering shared by the daemon, tests and evaluation."""

from __future__ import annotations

from promptguard.redaction.engine import PlaceholderAllocator


class PlaceholderRegistry:
    """Numbers each distinct value per session and type: session → type → fingerprint → index.

    The same fingerprint always maps to the same placeholder within a session, so a value
    repeated across operations stays referable. Not thread-safe; callers hold their own lock.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, dict[str, int]]] = {}

    def allocate(self, session_id: str, candidate_type: str, digest: str) -> str:
        by_type = self._sessions.setdefault(session_id, {}).setdefault(candidate_type, {})
        if digest not in by_type:
            by_type[digest] = len(by_type) + 1
        return f"[{candidate_type}_{by_type[digest]}]"

    def allocator(self, session_id: str) -> PlaceholderAllocator:
        return lambda candidate_type, digest: self.allocate(session_id, candidate_type, digest)

    def drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
