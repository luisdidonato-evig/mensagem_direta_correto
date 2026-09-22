import time
from dataclasses import dataclass, field
from threading import Lock

FAILURE_THRESHOLD = 5
COOLDOWN_SECONDS = 60.0


@dataclass
class _BreakerState:
    consecutive_failures: int = 0
    open_until: float = 0.0


@dataclass
class CircuitBreaker:
    """Per-key (typically per organization) breaker guarding Meta calls.

    In-process only: state lives in this worker's memory, so a multi-process
    deployment gets one breaker per process, not one globally shared. Good
    enough to stop a single hot loop from hammering a down Meta endpoint;
    a real multi-worker deployment would want this backed by Redis instead.
    """

    failure_threshold: int = FAILURE_THRESHOLD
    cooldown_seconds: float = COOLDOWN_SECONDS
    _states: dict[str, _BreakerState] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def is_open(self, key: str) -> bool:
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return False
            return time.monotonic() < state.open_until

    def record_success(self, key: str) -> None:
        with self._lock:
            self._states.pop(key, None)

    def record_failure(self, key: str) -> None:
        with self._lock:
            state = self._states.setdefault(key, _BreakerState())
            state.consecutive_failures += 1
            if state.consecutive_failures >= self.failure_threshold:
                state.open_until = time.monotonic() + self.cooldown_seconds


meta_circuit_breaker = CircuitBreaker()
