"""In-memory state for bounded, single-process evidence searches.

Nesta versão, o estado da busca é mantido em memória por usuário, versão e
sentença. É perdido após reinicialização e não é compartilhado entre workers.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import AsyncIterator, TypeAlias

from app.tools.schemas import EvidenceSearchCandidate


SearchSessionKey: TypeAlias = tuple[int, int, str]
"""Stable key ordered as user ID, document-version ID, and sentence UUID."""


class SearchSessionStatus(str, Enum):
    """Lifecycle states for an in-memory evidence search session."""

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EXHAUSTED = "EXHAUSTED"
    FAILED = "FAILED"


@dataclass
class ProviderSearchStatistics:
    """Aggregated operational statistics for one provider across search rounds."""

    provider: str
    successful_rounds: int = 0
    failed_rounds: int = 0
    results_found: int = 0
    after_deduplication: int = 0
    after_filters: int = 0


@dataclass
class EvidenceSearchSession:
    """Mutable transient state for one user, version, and sentence search."""

    current_round: int = 0
    queries_used: list[str] = field(default_factory=list)
    provider_statistics: dict[str, ProviderSearchStatistics] = field(default_factory=dict)
    candidates: dict[str, EvidenceSearchCandidate] = field(default_factory=dict)
    evaluated_candidate_keys: set[str] = field(default_factory=set)
    presented_candidate_keys: set[str] = field(default_factory=set)
    strong_support_keys: set[str] = field(default_factory=set)
    partial_support_keys: set[str] = field(default_factory=set)
    status: SearchSessionStatus = SearchSessionStatus.ACTIVE
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    search_in_progress: bool = False

    def touch(self) -> None:
        """Refresh the session timestamp after a controlled state mutation."""
        self.updated_at = datetime.now(UTC)

    def has_pending_or_reserved_candidates(self) -> bool:
        """Return whether useful candidates still need evaluation or presentation."""
        for key, candidate in self.candidates.items():
            if key not in self.evaluated_candidate_keys:
                return True
            if key not in self.presented_candidate_keys and candidate.evaluation_status.value == "evaluated":
                return True
        return False


class SearchAlreadyInProgressError(RuntimeError):
    """Raised when the same sentence already has an active search operation."""


class SearchStoreCapacityError(RuntimeError):
    """Raised when capacity is full and every existing session is in use."""


class EvidenceSearchSessionStore:
    """Concurrency-safe in-memory session store for one asynchronous process.

    The store deliberately provides no coordination between processes or workers.
    A short-lived global lock protects internal mappings, while a lock per active
    key serializes searches for the same sentence without blocking other keys.
    """

    def __init__(self, ttl_seconds: int = 1800, max_sessions: int = 500) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_sessions <= 0:
            raise ValueError("max_sessions must be positive")
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_sessions = max_sessions
        self._sessions: dict[SearchSessionKey, EvidenceSearchSession] = {}
        self._locks: dict[SearchSessionKey, asyncio.Lock] = {}
        self._state_lock = asyncio.Lock()

    @staticmethod
    def _validate_key(key: SearchSessionKey) -> None:
        """Reject malformed keys before they enter internal mappings."""
        if (
            not isinstance(key, tuple)
            or len(key) != 3
            or not isinstance(key[0], int)
            or key[0] <= 0
            or not isinstance(key[1], int)
            or key[1] <= 0
            or not isinstance(key[2], str)
            or not key[2].strip()
        ):
            raise ValueError("key must be (positive user_id, positive version_id, sentence_uuid)")

    @staticmethod
    def _is_expired(session: EvidenceSearchSession, now: datetime, ttl: timedelta) -> bool:
        return not session.search_in_progress and now - session.updated_at >= ttl

    def _remove_unlocked(self, key: SearchSessionKey) -> None:
        """Remove a session and an idle auxiliary lock while state lock is held."""
        self._sessions.pop(key, None)
        key_lock = self._locks.get(key)
        if key_lock is not None and not key_lock.locked():
            self._locks.pop(key, None)

    def _cleanup_expired_unlocked(self, now: datetime) -> int:
        expired = [
            key
            for key, session in self._sessions.items()
            if self._is_expired(session, now, self._ttl)
        ]
        for key in expired:
            self._remove_unlocked(key)
        return len(expired)

    def _ensure_capacity_unlocked(self, incoming_key: SearchSessionKey) -> None:
        if incoming_key in self._sessions or len(self._sessions) < self._max_sessions:
            return
        removable = [
            (key, session)
            for key, session in self._sessions.items()
            if not session.search_in_progress
            and not (self._locks.get(key) and self._locks[key].locked())
        ]
        if not removable:
            raise SearchStoreCapacityError("all in-memory search sessions are currently in use")
        oldest_key, _ = min(removable, key=lambda item: item[1].updated_at)
        self._remove_unlocked(oldest_key)

    async def get(self, key: SearchSessionKey) -> EvidenceSearchSession | None:
        """Return the session for a key and remove expired state first."""
        self._validate_key(key)
        async with self._state_lock:
            now = datetime.now(UTC)
            session = self._sessions.get(key)
            if session is not None and self._is_expired(session, now, self._ttl):
                self._remove_unlocked(key)
                return None
            return session

    async def set(self, key: SearchSessionKey, session: EvidenceSearchSession) -> None:
        """Insert or replace a session while enforcing TTL and capacity."""
        self._validate_key(key)
        async with self._state_lock:
            self._cleanup_expired_unlocked(datetime.now(UTC))
            self._ensure_capacity_unlocked(key)
            session.touch()
            self._sessions[key] = session

    async def delete(self, key: SearchSessionKey) -> None:
        """Delete one session and remove its idle auxiliary lock."""
        self._validate_key(key)
        async with self._state_lock:
            self._remove_unlocked(key)

    async def clear_document(self, document_version_id: int) -> int:
        """Remove sessions for exactly one document-version identifier."""
        async with self._state_lock:
            keys = [key for key in self._sessions if key[1] == document_version_id]
            for key in keys:
                self._remove_unlocked(key)
            return len(keys)

    async def clear_user(self, user_id: int) -> int:
        """Remove all sessions owned by one user."""
        async with self._state_lock:
            keys = [key for key in self._sessions if key[0] == user_id]
            for key in keys:
                self._remove_unlocked(key)
            return len(keys)

    async def cleanup_expired(self) -> int:
        """Remove expired sessions that are not currently in use."""
        async with self._state_lock:
            return self._cleanup_expired_unlocked(datetime.now(UTC))

    async def size(self) -> int:
        """Return the number of non-expired sessions."""
        async with self._state_lock:
            self._cleanup_expired_unlocked(datetime.now(UTC))
            return len(self._sessions)

    @asynccontextmanager
    async def search_guard(self, key: SearchSessionKey) -> AsyncIterator[EvidenceSearchSession]:
        """Exclusively guard one key and always release it after success or error."""
        self._validate_key(key)
        key_lock: asyncio.Lock
        session: EvidenceSearchSession
        async with self._state_lock:
            self._cleanup_expired_unlocked(datetime.now(UTC))
            key_lock = self._locks.setdefault(key, asyncio.Lock())
            if key_lock.locked():
                raise SearchAlreadyInProgressError(f"search already in progress for key {key!r}")
            await key_lock.acquire()
            session = self._sessions.get(key) or EvidenceSearchSession()
            if key not in self._sessions:
                try:
                    self._ensure_capacity_unlocked(key)
                except Exception:
                    key_lock.release()
                    self._locks.pop(key, None)
                    raise
                self._sessions[key] = session
            session.search_in_progress = True
            session.touch()

        try:
            yield session
        finally:
            async with self._state_lock:
                current = self._sessions.get(key)
                if current is not None:
                    current.search_in_progress = False
                    current.touch()
                key_lock.release()
                if current is not None and (
                    current.status is SearchSessionStatus.FAILED
                    or (
                        current.status in {SearchSessionStatus.COMPLETED, SearchSessionStatus.EXHAUSTED}
                        and not current.has_pending_or_reserved_candidates()
                    )
                ):
                    self._remove_unlocked(key)
                else:
                    self._locks.pop(key, None)
