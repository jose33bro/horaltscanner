"""Cross-process reservation lock for physical scanner hardware."""

from __future__ import annotations

import os
import tempfile
import threading


class HardwareReservationLock:
    """Combine a process-local lock with Linux flock for worker exclusion."""

    def __init__(self, path: str | None = None) -> None:
        self._thread_lock = threading.Lock()
        self._path = path or os.environ.get(
            "HORALSCANNER_HARDWARE_LOCK",
            os.path.join(tempfile.gettempdir(), "horalscanner-hardware.lock"),
        )
        self._file = None
        self._owner_thread_id: int | None = None

    def acquire(self, blocking: bool = True) -> bool:
        if not self._thread_lock.acquire(blocking=blocking):
            return False
        try:
            try:
                import fcntl
            except ImportError:
                self._owner_thread_id = threading.get_ident()
                return True
            self._file = open(self._path, "a+", encoding="ascii")
            flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            try:
                fcntl.flock(self._file.fileno(), flags)
            except BlockingIOError:
                self._file.close()
                self._file = None
                self._thread_lock.release()
                return False
            self._owner_thread_id = threading.get_ident()
            return True
        except Exception:
            if self._file is not None:
                self._file.close()
                self._file = None
            self._thread_lock.release()
            raise

    def release(self) -> None:
        try:
            if self._file is not None:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                self._file.close()
                self._file = None
        finally:
            self._owner_thread_id = None
            self._thread_lock.release()

    @property
    def owned_by_current_thread(self) -> bool:
        return self._owner_thread_id == threading.get_ident()
