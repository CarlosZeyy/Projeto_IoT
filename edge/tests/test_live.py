"""State machine, sessions and frame latency of the live mode (SPEC-019 sections 4.2 to 4.4)."""

from __future__ import annotations

import math
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from fractions import Fraction

import pytest
from PIL import ImageFile

from qc_contracts import Grade, ObjectType
from qc_edge.inference import InferenceResult
from qc_edge.limits import LIVE_MAX_PIXELS, load_live_image
from qc_edge.live import (
    LATENCY_MEMORY,
    FrameLatency,
    LiveSessions,
    LiveSessionsFullError,
    LiveStateMachine,
    p95_nearest_rank,
)
from qc_preprocess import InvalidImageError

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _result(
    object_type: ObjectType = ObjectType.SCREW,
    grade: Grade | None = Grade.FAIR,
    confidence: float = 0.9,
    latency_ms: int = 5,
) -> InferenceResult:
    graded = grade is not None
    return InferenceResult(
        object_type=object_type,
        grade=grade,
        grade_score=2.0 if graded else None,
        type_confidence=confidence,
        grade_confidence=0.8 if graded else None,
        needs_review=False,
        latency_ms=latency_ms,
    )


FAIR = _result()
POOR = _result(grade=Grade.POOR)
UNKNOWN = _result(ObjectType.UNKNOWN, None, 0.95)
NUT_GOOD = _result(ObjectType.NUT, Grade.GOOD)
DRILL = _result(ObjectType.DRILL, None)


def _feed(machine: LiveStateMachine, results: list[InferenceResult], start: int = 0) -> list:
    return [
        machine.feed(result, f"frame-{start + i}".encode(), T0 + timedelta(seconds=start + i))
        for i, result in enumerate(results)
    ]


def _emitting_machine() -> LiveStateMachine:
    machine = LiveStateMachine()
    _feed(machine, [FAIR] * 10)
    return machine


def _kept_frames(machine: LiveStateMachine) -> list[bytes | None]:
    return [entry.frame for entry in machine._window]


# ---------------------------------------------------------------------------------- emission


def test_emits_the_most_recent_frame_of_the_stable_pair() -> None:
    machine = LiveStateMachine()
    results = [POOR, *[_result(confidence=0.85)] * 8, POOR]
    steps = _feed(machine, results)
    assert [step.state for step in steps[:9]] == ["DETECTING"] * 9
    assert all(step.emit is None for step in steps[:9])
    last = steps[9]
    assert last.state == "EMIT"
    assert last.stability == 0.8
    emitted, frame, inspected_at = last.emit
    assert emitted.grade is Grade.FAIR
    assert frame == b"frame-8"
    assert inspected_at == T0 + timedelta(seconds=8)
    assert machine.state == "WAIT_REMOVAL"


@pytest.mark.parametrize(
    "results",
    [
        pytest.param([*[FAIR] * 7, *[POOR] * 3], id="only-7-agree"),
        pytest.param([*[_result(confidence=0.79)] * 8, *[POOR] * 2], id="mean-confidence-below"),
    ],
)
def test_no_emission_below_agreement_or_confidence(results: list[InferenceResult]) -> None:
    assert all(step.emit is None for step in _feed(LiveStateMachine(), results))


def test_mean_of_exactly_the_minimum_emits() -> None:
    results = [_result(confidence=0.80)] * 10
    assert _feed(LiveStateMachine(), results)[-1].state == "EMIT"


def test_confidence_mean_uses_only_the_frames_of_the_pair() -> None:
    results = [*[_result(confidence=0.9)] * 8, *[_result(grade=Grade.POOR, confidence=0.1)] * 2]
    assert _feed(LiveStateMachine(), results)[-1].state == "EMIT"


def test_a_full_window_is_required() -> None:
    assert all(step.emit is None for step in _feed(LiveStateMachine(), [FAIR] * 9))


def test_tie_at_the_top_does_not_emit_and_the_window_rolls() -> None:
    machine = LiveStateMachine(window=10, min_agree=5)
    steps = _feed(machine, [POOR, FAIR] * 5)
    assert all(step.emit is None for step in steps)
    assert steps[-1].stability == 0.5  # the tied count
    step = machine.feed(FAIR, b"frame-10", T0)
    assert step.state == "EMIT"
    assert step.emit[1] == b"frame-10"


def test_empty_table_never_emits_but_counts_for_stability() -> None:
    machine = LiveStateMachine(window=10, min_agree=3, empty_frames=10)
    steps = _feed(machine, [FAIR, *[UNKNOWN] * 9])
    assert all(step.emit is None for step in steps)
    assert steps[-1].state == "DETECTING"
    assert steps[-1].stability == 0.9
    last = machine.feed(UNKNOWN, b"x", T0)
    assert (last.state, last.stability, last.emit) == ("IDLE", 0, None)


def test_empty_table_on_top_blocks_a_second_pair_that_would_qualify() -> None:
    machine = LiveStateMachine(window=10, min_agree=3, empty_frames=10)
    steps = _feed(machine, [FAIR, UNKNOWN, FAIR, UNKNOWN, FAIR, UNKNOWN, *[UNKNOWN] * 4])
    assert all(step.emit is None for step in steps)


def test_known_type_without_grade_emits() -> None:
    steps = _feed(LiveStateMachine(), [DRILL] * 10)
    assert steps[-1].state == "EMIT"
    assert steps[-1].emit[0].object_type is ObjectType.DRILL


# --------------------------------------------------------------------------------- transitions


def test_idle_ignores_unknown_and_has_zero_stability() -> None:
    machine = LiveStateMachine()
    step = machine.feed(UNKNOWN, b"x", T0)
    assert (step.state, step.stability, step.emit) == ("IDLE", 0, None)
    assert list(machine._window) == []


def test_first_known_result_goes_to_detecting_with_partial_stability() -> None:
    step = LiveStateMachine().feed(FAIR, b"x", T0)
    assert (step.state, step.stability) == ("DETECTING", 0.1)


def test_consecutive_unknowns_in_detecting_go_back_to_idle() -> None:
    machine = LiveStateMachine()
    steps = _feed(machine, [FAIR, FAIR, UNKNOWN, UNKNOWN, FAIR, UNKNOWN, UNKNOWN, UNKNOWN])
    assert steps[3].state == "DETECTING"  # 2 in a row
    assert steps[6].state == "DETECTING"  # the run was broken by a known result
    assert (steps[7].state, steps[7].stability) == ("IDLE", 0)
    assert list(machine._window) == []


def test_wait_removal_never_emits_and_keeps_rolling_for_stability() -> None:
    machine = _emitting_machine()
    steps = _feed(machine, [FAIR] * 20)
    assert all(step.emit is None and step.state == "WAIT_REMOVAL" for step in steps)
    assert steps[-1].stability == 1.0
    # A different pair rolls in, which only the stability sees.
    step = _feed(machine, [POOR] * 3)[-1]
    assert step.stability == 0.7


def test_removal_needs_consecutive_unknowns_then_a_new_part_emits() -> None:
    machine = _emitting_machine()
    assert _feed(machine, [UNKNOWN, UNKNOWN, FAIR])[-1].state == "WAIT_REMOVAL"
    steps = _feed(machine, [UNKNOWN] * 3)
    assert steps[1].state == "WAIT_REMOVAL"
    assert (steps[2].state, steps[2].stability) == ("IDLE", 0)
    steps = _feed(machine, [NUT_GOOD] * 10)
    assert [step.state for step in steps] == ["DETECTING"] * 9 + ["EMIT"]
    assert steps[-1].emit[0].object_type is ObjectType.NUT


def test_reset_clears_everything() -> None:
    machine = LiveStateMachine()
    _feed(machine, [FAIR] * 9)
    machine.reset()
    assert machine.state == "IDLE"
    assert list(machine._window) == []
    steps = _feed(machine, [FAIR] * 10)
    assert steps[8].emit is None and steps[9].state == "EMIT"


# ------------------------------------------------------------------- frames in memory (R-02, R-14)


def test_only_frames_that_can_be_emitted_are_kept() -> None:
    machine = LiveStateMachine(window=4, min_agree=4)
    _feed(machine, [FAIR, UNKNOWN, FAIR])
    assert _kept_frames(machine) == [b"frame-0", None, b"frame-2"]


def test_frames_leaving_the_window_are_dropped() -> None:
    machine = LiveStateMachine(window=3, min_agree=3)
    _feed(machine, [FAIR, POOR, NUT_GOOD, DRILL])
    assert _kept_frames(machine) == [b"frame-1", b"frame-2", b"frame-3"]


def test_emit_drops_the_kept_frames_and_wait_removal_keeps_none() -> None:
    machine = _emitting_machine()
    assert _kept_frames(machine) == [None] * 10
    _feed(machine, [FAIR] * 5)
    assert _kept_frames(machine) == [None] * 10


@pytest.mark.parametrize(
    "kwargs",
    [
        {"window": 0, "min_agree": 1},
        {"window": 5, "min_agree": 6},
        {"min_agree": 0},
        {"min_confidence": 1.5},
        {"min_confidence": -0.1},
        {"empty_frames": 0},
    ],
)
def test_invalid_parameters(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        LiveStateMachine(**kwargs)


# ------------------------------------------------------------------------------------ sessions


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def at(self, seconds: float) -> None:
        self.now = T0 + timedelta(seconds=seconds)


def _sessions(clock: _Clock, **kwargs: int) -> LiveSessions:
    kwargs.setdefault("max_sessions", 2)
    return LiveSessions(clock, **kwargs)


def test_new_session_over_the_maximum_is_refused_until_one_expires() -> None:
    clock = _Clock()
    sessions = _sessions(clock)
    sessions.admit("a")
    clock.at(30)
    sessions.admit("b")
    clock.at(31)
    with pytest.raises(LiveSessionsFullError):
        sessions.admit("c")
    clock.at(60)
    with pytest.raises(LiveSessionsFullError):  # exactly 60 s is not "more than 60 s"
        sessions.admit("c")
    clock.at(61)
    sessions.admit("c")
    assert len(sessions) == 2


def test_existing_session_at_the_maximum_keeps_working() -> None:
    clock = _Clock()
    sessions = _sessions(clock, max_sessions=1)
    sessions.admit("a")
    clock.at(59)
    sessions.admit("a")
    clock.at(118)  # 59 s after the last frame
    sessions.admit("a")
    assert sessions.feed("a", "L-1", FAIR, b"x", T0).state == "DETECTING"


def test_session_that_comes_back_after_expiring_starts_over() -> None:
    clock = _Clock()
    sessions = _sessions(clock)
    for _ in range(9):
        sessions.feed("a", "L-1", FAIR, b"x", T0)
    clock.at(61)
    steps = [sessions.feed("a", "L-1", FAIR, b"x", T0) for _ in range(10)]
    assert steps[0].stability == 0.1
    assert steps[8].emit is None and steps[9].state == "EMIT"


def test_changing_the_lot_resets_the_machine() -> None:
    sessions = _sessions(_Clock())
    for _ in range(9):
        sessions.feed("a", "L-1", FAIR, b"x", T0)
    steps = [sessions.feed("a", "L-2", FAIR, b"x", T0) for _ in range(10)]
    assert all(step.emit is None for step in steps[:9])
    assert steps[9].state == "EMIT"


def test_admit_alone_never_touches_the_window() -> None:
    sessions = _sessions(_Clock())
    for _ in range(9):
        sessions.feed("a", "L-1", FAIR, b"x", T0)
    sessions.admit("a")
    assert sessions.feed("a", "L-1", FAIR, b"x", T0).state == "EMIT"


def test_clock_going_backwards_restarts_the_idle_count() -> None:
    clock = _Clock()
    sessions = _sessions(clock, max_sessions=1)
    clock.at(1000)
    sessions.admit("a")
    clock.at(0)  # backwards: a plain "now - last" would never pass 60 s until t = 1060
    sessions.sweep()
    assert len(sessions) == 1
    clock.at(61)
    sessions.admit("b")
    assert len(sessions) == 1


def test_sweep_discards_idle_sessions_without_a_new_frame() -> None:
    clock = _Clock()
    sessions = _sessions(clock)
    sessions.admit("a")
    clock.at(40)
    sessions.admit("b")
    clock.at(61)
    sessions.sweep()
    assert len(sessions) == 1


def test_sweep_of_no_session_does_not_read_the_clock() -> None:
    def forbidden() -> datetime:
        raise AssertionError("clock read")

    LiveSessions(forbidden).sweep()


def test_reset_of_a_missing_session_is_ignored_and_clear_ends_all() -> None:
    sessions = _sessions(_Clock())
    sessions.reset("nobody")
    sessions.admit("a")
    sessions.clear()
    assert len(sessions) == 0


def test_reset_restarts_the_window_of_the_session() -> None:
    sessions = _sessions(_Clock())
    for _ in range(9):
        sessions.feed("a", "L-1", FAIR, b"x", T0)
    sessions.reset("a")
    assert sessions.feed("a", "L-1", FAIR, b"x", T0).stability == 0.1


def test_feed_of_a_session_that_expired_and_lost_its_slot_is_refused() -> None:
    clock = _Clock()
    sessions = _sessions(clock, max_sessions=1)
    sessions.admit("a")
    clock.at(61)
    sessions.admit("b")
    with pytest.raises(LiveSessionsFullError):
        sessions.feed("a", "L-1", FAIR, b"x", T0)


def test_machine_factory_is_used() -> None:
    sessions = LiveSessions(_Clock(), machine_factory=lambda: LiveStateMachine(3, 3))
    steps = [sessions.feed("a", "L-1", FAIR, b"x", T0) for _ in range(3)]
    assert steps[-1].state == "EMIT"


def test_simultaneous_frames_of_a_session_emit_once() -> None:
    sessions = LiveSessions(_Clock())
    barrier = threading.Barrier(8)

    def worker(_: int) -> int:
        barrier.wait(timeout=5)
        steps = [sessions.feed("a", "L-1", FAIR, b"x", T0) for _ in range(50)]
        return sum(step.emit is not None for step in steps)

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(worker, range(8))) == 1


# ------------------------------------------------------------------------------------- latency


def test_p95_of_the_acceptance_example() -> None:
    assert p95_nearest_rank([300, 300, *[100] * 18]) == 300


def test_p95_rank_matches_the_exact_formula_for_every_size() -> None:
    for size in range(1, LATENCY_MEMORY + 1):
        values = list(range(size))
        rank = math.ceil(Fraction(95, 100) * size)
        assert p95_nearest_rank(values) == sorted(values)[rank - 1], size


def test_p95_of_nothing_is_an_error() -> None:
    with pytest.raises(ValueError):
        p95_nearest_rank([])


def test_frame_latency_keeps_the_last_100() -> None:
    latency = FrameLatency()
    assert latency.summary() is None
    latency.record(9000)
    assert latency.summary() == (9000, 9000)
    for _ in range(LATENCY_MEMORY):
        latency.record(10)
    assert latency.summary() == (10, 10)  # the 9000 left the memory


# ---------------------------------------------------------------------------------- frame image


def test_live_image_accepts_a_jpeg_at_the_pixel_limit(make_image) -> None:
    assert load_live_image(make_image((1000, 1000))).size == (1000, 1000)
    assert LIVE_MAX_PIXELS == 1_000_000


def test_live_image_refuses_above_the_pixel_limit_before_decoding(
    make_image, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(_: bytes) -> None:
        raise AssertionError("decoded")

    monkeypatch.setattr("qc_edge.limits.load_image", forbidden)
    with pytest.raises(InvalidImageError, match="live pixel limit"):
        load_live_image(make_image((1001, 1000)))


@pytest.mark.parametrize("fmt", ["PNG", "GIF", "BMP"])
def test_live_image_accepts_only_jpeg(make_image, fmt: str) -> None:
    with pytest.raises(InvalidImageError):
        load_live_image(make_image(fmt=fmt))


def test_live_image_refuses_the_truncated_images_flag(
    make_image, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    with pytest.raises(RuntimeError, match="LOAD_TRUNCATED_IMAGES"):
        load_live_image(make_image())
