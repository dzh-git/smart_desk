"""
Business logic — pure state machine for smart desk.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class SeatPhase(str, Enum):
    EMPTY = "empty"
    OCCUPIED = "occupied"       # TOF detected someone, not yet checked in
    CHECKED_IN = "checked_in"    # UI confirmed attendance


class VotePhase(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass
class SeatState:
    seat_id: int
    phase: SeatPhase = SeatPhase.EMPTY
    attendee_id: int = 0
    attendee_name: str = ""

    # LED state derived from phase
    @property
    def led_pattern(self) -> str:
        if self.phase == SeatPhase.EMPTY:
            return "breathe"   # warm dim standby
        elif self.phase == SeatPhase.OCCUPIED:
            return "wave"      # blue wave — someone sat down
        else:
            return "solid"     # warm white — confirmed

    @property
    def led_color(self) -> tuple[int, int, int]:
        if self.phase == SeatPhase.EMPTY:
            return (255, 200, 150)   # warm dim
        elif self.phase == SeatPhase.OCCUPIED:
            return (80, 140, 255)    # blue
        else:
            return (255, 220, 180)   # warm white


@dataclass
class VoteState:
    vote_id: int
    title: str
    options: list[str]
    phase: VotePhase = VotePhase.OPEN
    votes: dict[int, str] = field(default_factory=dict)  # attendee_id -> option

    def cast(self, attendee_id: int, option: str) -> bool:
        """Returns True if vote was accepted."""
        if self.phase != VotePhase.OPEN:
            return False
        if option not in self.options:
            return False
        self.votes[attendee_id] = option
        return True

    @property
    def results(self) -> list[dict]:
        counts: dict[str, int] = {opt: 0 for opt in self.options}
        for opt in self.votes.values():
            if opt in counts:
                counts[opt] += 1
        return [{"option": k, "count": v} for k, v in counts.items()]

    @property
    def total_votes(self) -> int:
        return len(self.votes)


class DeskStateMachine:
    """Pure state machine for the 8-seat smart desk.

    No I/O — callers push events in and read state out.
    """

    SEATS = 8

    def __init__(self):
        self.seats: dict[int, SeatState] = {
            i: SeatState(seat_id=i) for i in range(1, self.SEATS + 1)
        }
        self.active_vote: VoteState | None = None

    # ── Seat events ──

    def seat_occupied(self, seat_id: int) -> SeatState:
        """TOF detected someone sitting."""
        seat = self.seats[seat_id]
        if seat.phase == SeatPhase.EMPTY:
            seat.phase = SeatPhase.OCCUPIED
        return seat

    def seat_vacant(self, seat_id: int) -> SeatState:
        """Person left."""
        seat = self.seats[seat_id]
        seat.phase = SeatPhase.EMPTY
        seat.attendee_id = 0
        seat.attendee_name = ""
        return seat

    def check_in(self, seat_id: int, attendee_id: int = 0, name: str = "") -> SeatState:
        """UI confirmed check-in."""
        seat = self.seats[seat_id]
        seat.phase = SeatPhase.CHECKED_IN
        seat.attendee_id = attendee_id
        seat.attendee_name = name
        return seat

    # ── Vote ──

    def start_vote(self, vote_id: int, title: str, options: list[str]) -> VoteState:
        self.active_vote = VoteState(vote_id=vote_id, title=title, options=options)
        return self.active_vote

    def cast_vote(self, attendee_id: int, option: str) -> bool:
        if not self.active_vote:
            return False
        return self.active_vote.cast(attendee_id, option)

    def close_vote(self) -> VoteState | None:
        if self.active_vote:
            self.active_vote.phase = VotePhase.CLOSED
        return self.active_vote

    # ── Derived state ──

    @property
    def checked_in_count(self) -> int:
        return sum(1 for s in self.seats.values() if s.phase == SeatPhase.CHECKED_IN)

    @property
    def occupied_count(self) -> int:
        return sum(1 for s in self.seats.values() if s.phase != SeatPhase.EMPTY)

    @property
    def all_seats_state(self) -> list[dict]:
        return [
            {
                "seat_id": s.seat_id,
                "phase": s.phase.value,
                "attendee_name": s.attendee_name,
                "led_pattern": s.led_pattern,
                "led_color": list(s.led_color),
            }
            for s in self.seats.values()
        ]
