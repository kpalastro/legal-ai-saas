"""9-turn debate state machine (TECH_STACK.md, TEST_PLAN G6).

Exactly 9 turns, fixed order. Judge belief updates at turns 3/6/9. Pause/intervention
resumes the same turn. Out-of-order transitions rejected by construction — the machine
is a linear list cursor, not a graph, so there is no way to skip or reorder.
100% coverage mandatory on this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class AgentRole(StrEnum):
    USER_ADVOCATE = "user_advocate"  # argues the user's position
    OPPONENT = "opponent"  # adversarial counter-arguments
    JUDGE = "judge"  # neutral adjudicator, belief state


@dataclass(frozen=True)
class Turn:
    index: int  # 1..9
    role: AgentRole
    name: str
    is_belief_update: bool = False


# The full protocol (REQUIREMENTS.md §3). Belief updates at 3, 6, 9.
PROTOCOL: tuple[Turn, ...] = (
    Turn(1, AgentRole.USER_ADVOCATE, "plaintiff_opening"),
    Turn(2, AgentRole.OPPONENT, "defendant_opening"),
    Turn(3, AgentRole.JUDGE, "judge_initial_belief", is_belief_update=True),
    Turn(4, AgentRole.USER_ADVOCATE, "plaintiff_rebuttal"),
    Turn(5, AgentRole.OPPONENT, "defendant_rebuttal"),
    Turn(6, AgentRole.JUDGE, "judge_mid_belief", is_belief_update=True),
    Turn(7, AgentRole.USER_ADVOCATE, "plaintiff_closing"),
    Turn(8, AgentRole.OPPONENT, "defendant_closing"),
    Turn(9, AgentRole.JUDGE, "judge_final_verdict", is_belief_update=True),
)


@dataclass
class DebateState:
    """Pause/resume/intervention state for one simulation."""

    cursor: int = 1  # next turn to execute (1-based)
    paused: bool = False
    interventions: list[str] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.cursor > len(PROTOCOL)

    def current_turn(self) -> Turn:
        if self.finished:
            raise IndexError("debate complete")
        return PROTOCOL[self.cursor - 1]

    def advance(self, content: str) -> Turn:
        """Execute the current turn and move the cursor. Raises if paused/finished."""
        if self.paused:
            raise RuntimeError("debate is paused — resume before advancing")
        turn = self.current_turn()
        self.transcript.append(
            {"turn": turn.index, "role": turn.role.value, "name": turn.name, "content": content}
        )
        self.cursor += 1
        return turn

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def intervene(self, note: str) -> None:
        """User intervention: recorded, replayed on resume; does not move the cursor."""
        self.interventions.append(note)
