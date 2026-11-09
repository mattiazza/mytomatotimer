from mytomatotimer.engine import (
    Beep, BreakEnded, Engine, FocusEnded, Phase, SegmentEnded, SegmentStarted,
    SessionEnded, Settings,
)

# Small numbers keep the arithmetic readable: focus 100 s, break 20 s, long break 60 s.
S = Settings(
    focus_seconds=100, break_seconds=20, long_break_seconds=60,
    blocks_before_long_break=2, auto_start=True, idle_timeout_seconds=50,
    beep_seconds=3, beeps_at_focus_end=False,
)


def make(**changes) -> Engine:
    from dataclasses import replace
    e = Engine(replace(S, **changes))
    e.start(0)
    return e


def test_start_is_focus_with_full_planned_time():
    e = make()
    assert e.phase is Phase.FOCUS
    assert e.remaining(30) == 70 and e.elapsed(30) == 30


def test_focus_end_starts_break_at_exact_end_time():
    e = make()
    events = e.tick(100)
    assert events == [
        FocusEnded(), SegmentEnded(100), SegmentStarted(Phase.BREAK, 20, 100),
    ]
    assert e.phase is Phase.BREAK


def test_long_break_after_n_blocks_and_auto_start():
    e = make()
    e.tick(100)  # block 1 -> break
    events = e.tick(120)  # break -> auto-start block 2
    assert events == [SegmentEnded(120), BreakEnded(), SegmentStarted(Phase.FOCUS, 100, 120)]
    events = e.tick(220)  # block 2 -> long break
    assert SegmentStarted(Phase.LONG_BREAK, 60, 220) in events


def test_take_break_counts_toward_long_break_counter():
    e = make()
    assert e.take_break(40) == [SegmentEnded(40), SegmentStarted(Phase.BREAK, 20, 40)]
    e.tick(60)  # break ends, fresh full focus block
    assert e.phase is Phase.FOCUS and e.remaining(60) == 100
    events = e.take_break(70)  # second block (cut short) -> long break
    assert events[-1] == SegmentStarted(Phase.LONG_BREAK, 60, 70)


def test_take_break_only_during_focus():
    e = make()
    e.take_break(10)
    assert e.take_break(15) == []


def test_late_tick_processes_every_due_transition_at_its_own_time():
    e = make()
    events = e.tick(250)  # tick arrives long after: focus, break, focus 2 all due
    starts = [ev for ev in events if isinstance(ev, SegmentStarted)]
    assert [(s.kind, s.at) for s in starts] == [
        (Phase.BREAK, 100), (Phase.FOCUS, 120), (Phase.LONG_BREAK, 220),
    ]


def test_auto_start_off_waits_then_user_starts_block():
    e = make(auto_start=False)
    e.tick(100)
    events = e.tick(120)
    assert events == [SegmentEnded(120), BreakEnded()]
    assert e.waiting and e.phase is None and e.session_active
    assert e.start_next_block(130) == [SegmentStarted(Phase.FOCUS, 100, 130)]
    assert not e.waiting


def test_idle_timeout_closes_session_at_deadline():
    e = make(auto_start=False)
    e.tick(100)
    e.tick(120)
    assert e.tick(169) == []
    assert e.tick(500) == [SessionEnded("idle_timeout", 170)]
    assert not e.session_active


def test_idle_timeout_does_not_apply_with_auto_start():
    e = make(auto_start=True)
    e.tick(100)
    e.tick(120)
    assert e.phase is Phase.FOCUS and e.session_active


def test_break_beeps_once_per_second_in_last_n_seconds():
    e = make()
    e.tick(100)  # break runs 100..120
    beeps = [t for t in range(100, 121) if Beep() in e.tick(t)]
    assert beeps == [117, 118, 119]  # remaining 3, 2, 1


def test_repeated_tick_in_same_second_does_not_double_beep():
    e = make()
    e.tick(100)
    assert e.tick(117) == [Beep()]
    assert e.tick(117) == []


def test_zero_beep_seconds_means_no_beeps():
    e = make(beep_seconds=0)
    e.tick(100)
    assert not any(Beep() in e.tick(t) for t in range(100, 120))


def test_focus_beeps_only_when_enabled():
    off = make()
    assert not any(Beep() in off.tick(t) for t in range(90, 100))
    on = make(beeps_at_focus_end=True)
    assert [t for t in range(90, 100) if Beep() in on.tick(t)] == [97, 98, 99]


def test_no_beeps_while_waiting_after_break():
    e = make(auto_start=False)
    e.tick(100)
    e.tick(120)
    assert not any(Beep() in e.tick(t) for t in range(121, 160))


def test_stop_resets_block_counter():
    e = make()
    e.take_break(10)
    e.stop(20)
    e.start(30)
    assert e.take_break(40)[-1].kind is Phase.BREAK  # counter restarted, not a long break


def test_session_focus_excludes_breaks():
    e = make()  # focus 100, break 20
    assert e.session_focus(40) == 40
    e.tick(100)  # break starts at 100
    assert e.session_focus(110) == 100  # frozen during the break
    e.tick(120)  # second focus block starts at 120
    assert e.session_focus(150) == 130


def test_session_focus_counts_partial_block_and_resets():
    e = make()
    e.take_break(30)
    assert e.session_focus(35) == 30
    e.stop(40)
    e.start(50)
    assert e.session_focus(60) == 10
