"""
VoteService — vote lifecycle, ballot casting, statistics.

Per system_architecture §4.2, EVENT_BUS_SPEC §8:
    - All business rules enforced here.
    - Publishes vote_started, vote_updated, vote_closed events.
    - Uses VoteRepository for data access.

Business rules:
    V1: Only one open vote at a time.
    V2: vote.status ∈ {open, closed}.
    V3: No voting after close.
    V4: (attendee_id, vote_id) unique — upsert on re-vote.
    V5: is_anonymous controls statistics output format.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.events.event_bus import EventBus
from backend.events.vote_events import VoteStartedEvent, VoteUpdatedEvent, VoteClosedEvent
from backend.exceptions import NotFoundError, ConflictError, ValidationError
from backend.models.vote import Vote
from backend.repositories.vote_repository import VoteRepository
from backend.schemas.vote import VoteOptionStat, VoteStatistics
from backend.services.base import BaseService


class VoteService(BaseService):
    """Vote lifecycle and ballot management.

    Business rules V1-V5 enforced here.
    Events published: vote_started, vote_updated, vote_closed.
    """

    def __init__(self, db: Session, event_bus: EventBus) -> None:
        super().__init__(db, event_bus)
        self.vote_repo = VoteRepository(db)

    # ── Vote CRUD ────────────────────────────────────────────────────────────

    def create_vote(
        self,
        meeting_id: int,
        title: str,
        options: list[str],
        is_anonymous: bool = False,
    ) -> Vote:
        """Create a new vote with status='open'.

        Rules:
            V1: Only one open vote allowed at any time.
        Publishes: vote_started event.
        """
        # V1: check no open vote exists
        existing = self.vote_repo.get_open_vote()
        if existing is not None:
            raise ConflictError(
                "Another vote is already open",
                "OPEN_VOTE_EXISTS",
            )

        vote = self.vote_repo.create(
            meeting_id=meeting_id,
            title=title,
            options_json=json.dumps(options),
            is_anonymous=is_anonymous,
            status="open",
        )

        self.event_bus.publish(
            VoteStartedEvent(
                meeting_id=meeting_id,
                payload={"vote_id": vote.id, "title": vote.title},
            )
        )

        return vote

    def get_active_vote(self) -> Vote | None:
        """Return the currently open vote, or None."""
        return self.vote_repo.get_open_vote()

    def list_votes_by_meeting(self, meeting_id: int) -> list[Vote]:
        """Return all votes for a meeting, including closed vote history."""
        return self.vote_repo.list_by_meeting(meeting_id)

    def get_vote(self, vote_id: int) -> Vote:
        """Get vote by ID. Raises NotFoundError if missing."""
        vote = self.vote_repo.get_by_id(vote_id)
        if not vote:
            raise NotFoundError(
                f"Vote {vote_id} not found",
                "VOTE_NOT_FOUND",
            )
        return vote

    def get_record_count(self, vote_id: int) -> int:
        """Return the number of ballots cast for a vote."""
        return self.vote_repo.count_records_by_vote(vote_id)

    # ── Voting ───────────────────────────────────────────────────────────────

    def submit_vote(self, vote_id: int, attendee_id: int, option: str) -> Vote:
        """Cast or update a ballot.

        Rules:
            V3: Vote must be open.
            V4: One ballot per attendee — upsert on re-vote.
        Publishes: vote_updated event.
        """
        vote = self.get_vote(vote_id)

        # V3: check status
        if vote.status != "open":
            raise ValidationError(
                "Vote is closed",
                "VOTE_CLOSED",
            )

        # Validate option
        options: list[str] = json.loads(vote.options_json)
        if option not in options:
            raise ValidationError(
                f"Invalid option: {option}",
                "INVALID_VOTE_OPTION",
            )

        # V4: upsert — one ballot per attendee
        existing = self.vote_repo.get_record(vote_id, attendee_id)
        if existing:
            existing.option = option
            self.vote_repo.save_record(existing)
        else:
            self.vote_repo.create_record(
                vote_id=vote_id,
                attendee_id=attendee_id,
                option=option,
            )

        self.event_bus.publish(
            VoteUpdatedEvent(
                meeting_id=vote.meeting_id,
                payload={"vote_id": vote_id},
            )
        )

        return vote

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def close_vote(self, vote_id: int) -> Vote:
        """Close a vote. Idempotent if already closed.

        Publishes: vote_closed event.
        """
        vote = self.get_vote(vote_id)

        if vote.status == "closed":
            return vote  # idempotent

        vote.status = "closed"
        vote.closed_at = datetime.now(timezone.utc)
        self.vote_repo.save(vote)

        self.event_bus.publish(
            VoteClosedEvent(
                meeting_id=vote.meeting_id,
                payload={"vote_id": vote_id},
            )
        )

        return vote

    # ── Statistics ───────────────────────────────────────────────────────────

    def get_statistics(self, vote_id: int) -> VoteStatistics:
        """Compute vote statistics.

        V5: Anonymous → attendee_ids set to None.
            Named    → attendee_ids list included.
        """
        vote = self.get_vote(vote_id)
        options: list[str] = json.loads(vote.options_json)
        records = self.vote_repo.list_records_by_vote(vote_id)

        # Build per-option accumulator
        acc: dict[str, list[int]] = {opt: [] for opt in options}
        for r in records:
            if r.option in acc:
                acc[r.option].append(r.attendee_id)

        results: list[VoteOptionStat] = []
        for opt in options:
            ids = acc[opt]
            results.append(
                VoteOptionStat(
                    option=opt,
                    count=len(ids),
                    attendee_ids=None if vote.is_anonymous else ids,
                )
            )

        return VoteStatistics(
            vote_id=vote.id,
            title=vote.title,
            is_anonymous=vote.is_anonymous,
            status=vote.status,
            total_votes=len(records),
            results=results,
        )
