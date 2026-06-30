from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter, sleep


@dataclass
class FrameTimer:
    """Monotonic frame timer with an optional FPS cap.

    `perf_counter()` measures elapsed time, not wall-clock time. This makes it
    appropriate for frame deltas, cooldowns, and animation timers.
    """

    target_fps: int
    max_delta_seconds: float

    def __post_init__(self) -> None:
        if self.target_fps < 0:
            raise ValueError('target_fps must be zero or greater.')
        if self.max_delta_seconds <= 0:
            raise ValueError('max_delta_seconds must be greater than zero.')

        self._last_frame_started = perf_counter()
        self._current_frame_started = self._last_frame_started
        self.game_time = 0.0

    @property
    def target_frame_seconds(self) -> float:
        return 0.0 if self.target_fps == 0 else 1.0 / self.target_fps

    def begin_frame(self) -> float:
        self._current_frame_started = perf_counter()
        raw_delta = self._current_frame_started - self._last_frame_started
        self._last_frame_started = self._current_frame_started

        # Prevent window dragging, breakpoints, or alt-tab from moving an
        # entity an enormous distance in one update.
        delta_seconds = min(raw_delta, self.max_delta_seconds)
        self.game_time += delta_seconds
        return delta_seconds

    def end_frame(self) -> None:
        if self.target_fps == 0:
            return

        elapsed = perf_counter() - self._current_frame_started
        remaining = self.target_frame_seconds - elapsed
        if remaining > 0.0:
            sleep(remaining)
