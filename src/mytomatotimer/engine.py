"""Pure state machine for the focus/break cycle. No UI, no DB, no clock of its own.

Every method takes `now` (UTC epoch seconds). Time is derived from timestamps, so a
late or skipped tick can't drift anything. Methods return a list of events; the app
reacts to them (persist segments, notify, beep). The engine never does I/O.
"""

from dataclasses import dataclass
from enum import Enum


class Phase(Enum):
    FOCUS = "focus"
    BREAK = "break"
    LONG_BREAK = "long_break"


@dataclass(frozen=True)
class Settings:
    focus_seconds: int = 50 * 60
    break_seconds: int = 10 * 60
    long_break_seconds: int = 30 * 60
    blocks_before_long_break: int = 4
    auto_start: bool = True
    idle_timeout_seconds: int = 5 * 60
    beep_seconds: int = 5
    beeps_at_focus_end: bool = False


# --- events -----------------------------------------------------------------

@dataclass(frozen=True)
class SegmentEnded:
    """Close the open segment at `at` (may be earlier than the tick that found it)."""
    at: int


@dataclass(frozen=True)
class SegmentStarted:
    kind: Phase
    planned_seconds: int
    at: int


@dataclass(frozen=True)
class SessionEnded:
    reason: str  # matches sessions.end_reason: 'idle_timeout'
    at: int


@dataclass(frozen=True)
class FocusEnded:
    """Alert: a focus block ran its full length."""


@dataclass(frozen=True)
class BreakEnded:
    """Alert: a break ran its full length."""


@dataclass(frozen=True)
class Beep:
    pass


Event = SegmentEnded | SegmentStarted | SessionEnded | FocusEnded | BreakEnded | Beep


class Engine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.phase: Phase | None = None  # None: no block running
        self.phase_started_at = 0
        self.phase_planned = 0
        self.session_started_at: int | None = None
        # Set while a session is open but waiting for a click (auto-start off).
        self.waiting_since: int | None = None
        self._blocks_done = 0
        self._focus_done = 0  # seconds of finished focus blocks in this session
        self._last_beep_remaining: int | None = None

    # --- state -------------------------------------------------------------

    @property
    def session_active(self) -> bool:
        return self.session_started_at is not None

    @property
    def waiting(self) -> bool:
        return self.waiting_since is not None

    def remaining(self, now: int) -> int:
        """Seconds left in the current block (0 if none is running)."""
        if self.phase is None:
            return 0
        return max(0, self.phase_started_at + self.phase_planned - now)

    def elapsed(self, now: int) -> int:
        """Seconds spent in the current block (0 if none is running)."""
        if self.phase is None:
            return 0
        return max(0, now - self.phase_started_at)

    def session_focus(self, now: int) -> int:
        """Focus seconds in this session so far. Breaks and waiting don't count."""
        current = self.elapsed(now) if self.phase is Phase.FOCUS else 0
        return self._focus_done + current

    # --- user actions ------------------------------------------------------

    def start(self, now: int) -> None:
        """Begin a session with a focus block.

        No events: the caller creates the session and its first focus segment
        (repo.start_session), with the same planned length as `settings.focus_seconds`.
        """
        self.session_started_at = now
        self._blocks_done = 0
        self._focus_done = 0
        self.waiting_since = None
        self._begin(Phase.FOCUS, now)

    def stop(self, now: int) -> None:
        """End the session (the caller closes the segment and session in the DB)."""
        self._reset()

    def take_break(self, now: int) -> list[Event]:
        """End the focus block early (its time counts) and start a break right away."""
        if self.phase is not Phase.FOCUS:
            return []
        return self._end_focus(now)

    def start_next_block(self, now: int) -> list[Event]:
        """Start a focus block while waiting after a break (auto-start off)."""
        if not self.waiting:
            return []
        self.waiting_since = None
        return [self._begin(Phase.FOCUS, now)]

    # --- clock -------------------------------------------------------------

    def tick(self, now: int) -> list[Event]:
        events: list[Event] = []
        # A tick can arrive late (or after a long gap), so process every transition
        # that is due, each at its own end time rather than at `now`.
        while self.session_active:
            if self.waiting:
                deadline = self.waiting_since + self.settings.idle_timeout_seconds
                if now < deadline:
                    break
                events.append(SessionEnded("idle_timeout", deadline))
                self._reset()
                break
            end = self.phase_started_at + self.phase_planned
            if now < end:
                break
            if self.phase is Phase.FOCUS:
                events.append(FocusEnded())
                events += self._end_focus(end)
            else:
                events += self._end_break(end)
        if self.session_active and not self.waiting:
            events += self._beeps(now)
        return events

    # --- internals ---------------------------------------------------------

    def _reset(self) -> None:
        self.phase = None
        self.session_started_at = None
        self.waiting_since = None
        self._blocks_done = 0
        self._focus_done = 0

    def _begin(self, phase: Phase, at: int) -> SegmentStarted:
        planned = {
            Phase.FOCUS: self.settings.focus_seconds,
            Phase.BREAK: self.settings.break_seconds,
            Phase.LONG_BREAK: self.settings.long_break_seconds,
        }[phase]
        self.phase = phase
        self.phase_started_at = at
        self.phase_planned = planned
        self._last_beep_remaining = None
        return SegmentStarted(phase, planned, at)

    def _end_focus(self, at: int) -> list[Event]:
        # A block cut short counts toward the long-break counter too.
        self._blocks_done += 1
        self._focus_done += at - self.phase_started_at
        long = self._blocks_done % self.settings.blocks_before_long_break == 0
        return [SegmentEnded(at), self._begin(Phase.LONG_BREAK if long else Phase.BREAK, at)]

    def _end_break(self, at: int) -> list[Event]:
        events: list[Event] = [SegmentEnded(at), BreakEnded()]
        if self.settings.auto_start:
            events.append(self._begin(Phase.FOCUS, at))
        else:
            self.phase = None
            self.waiting_since = at
        return events

    def _beeps(self, now: int) -> list[Event]:
        """One beep per second in the last N seconds of a break (and optionally of focus)."""
        n = self.settings.beep_seconds
        if n <= 0:
            return []
        if self.phase is Phase.FOCUS and not self.settings.beeps_at_focus_end:
            return []
        remaining = self.remaining(now)
        if not 0 < remaining <= n or remaining == self._last_beep_remaining:
            return []
        self._last_beep_remaining = remaining
        return [Beep()]
