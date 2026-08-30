"""G6: debate state machine — exactly 9 turns, in order, belief updates at 3/6/9,
pause/intervention semantics, out-of-order impossible."""

import pytest

from app.agents.debate_state_machine import PROTOCOL, AgentRole, DebateState


def test_protocol_exactly_nine_turns() -> None:
    assert len(PROTOCOL) == 9
    assert [t.index for t in PROTOCOL] == list(range(1, 10))


def test_belief_updates_at_3_6_9() -> None:
    belief_turns = [t.index for t in PROTOCOL if t.is_belief_update]
    assert belief_turns == [3, 6, 9]
    assert all(PROTOCOL[i - 1].role == AgentRole.JUDGE for i in belief_turns)


def test_full_run_in_order() -> None:
    state = DebateState()
    roles = []
    names = []
    while not state.finished:
        t = state.advance(content="x")
        roles.append(t.role)
        names.append(t.name)
    assert names == [t.name for t in PROTOCOL]
    assert len(state.transcript) == 9
    with pytest.raises(IndexError):
        state.current_turn()


def test_pause_blocks_advance_and_resume_continues() -> None:
    state = DebateState()
    state.advance("t1")
    state.pause()
    with pytest.raises(RuntimeError):
        state.advance("t2")
    state.intervene("judge, reconsider element 3")
    state.resume()
    t = state.advance("t2")
    assert t.index == 2  # resumed at the same turn, no skip
    assert state.interventions == ["judge, reconsider element 3"]
