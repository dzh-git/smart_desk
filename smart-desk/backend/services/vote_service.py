from __future__ import annotations
from backend.services.event_bus import EventBus, BaseEvent


class VoteError(Exception):
    """Base exception for vote service errors."""
    pass


class VoteNotFoundError(VoteError):
    """Vote does not exist."""
    pass


class VoteClosedError(VoteError):
    """Vote is not in 'open' status."""
    pass


class InvalidVoteOptionError(VoteError):
    """The chosen option is not in the vote's option list."""
    pass


class VoteService:
    def __init__(self, event_bus: EventBus, vote_repo):
        self.bus = event_bus
        self.vote_repo = vote_repo

    def create(self, meeting_id: int, title: str, options: list[str], is_anonymous: bool = False):
        if not title or not title.strip():
            raise ValueError("title must not be empty")
        if not options:
            raise ValueError("options must not be empty")
        v = self.vote_repo.create(meeting_id, title, options, is_anonymous)
        self.bus.publish(BaseEvent(
            name="vote_started",
            payload={"vote_id": v.id, "title": title},
        ))
        return v

    def get_by_id(self, vote_id: int, meeting_id: int | None = None):
        return self.vote_repo.get_by_id(vote_id, meeting_id)

    def list_by_meeting(self, meeting_id: int):
        return self.vote_repo.list_by_meeting(meeting_id)

    def cast(self, meeting_id: int, vote_id: int, attendee_id: int, option: str):
        v = self.vote_repo.get_by_id(vote_id, meeting_id)
        if not v:
            raise VoteNotFoundError(f"Vote {vote_id} not found in meeting {meeting_id}")
        if v.status != "open":
            raise VoteClosedError(f"Vote {vote_id} is {v.status}")
        if option not in v.options:
            raise InvalidVoteOptionError(
                f"Option '{option}' not in vote options: {v.options}"
            )
        self.vote_repo.cast(vote_id, attendee_id, option)
        self.bus.publish(BaseEvent(
            name="vote_updated",
            payload={"vote_id": vote_id},
        ))

    def close(self, meeting_id: int, vote_id: int):
        v = self.vote_repo.get_by_id(vote_id, meeting_id)
        if not v:
            raise VoteNotFoundError(f"Vote {vote_id} not found in meeting {meeting_id}")
        if v.status != "open":
            raise VoteClosedError(f"Vote {vote_id} already {v.status}")
        v = self.vote_repo.close(vote_id)
        self.bus.publish(BaseEvent(
            name="vote_closed",
            payload={"vote_id": vote_id},
        ))
        return v

    def get_statistics(self, vote_id: int):
        v = self.vote_repo.get_by_id(vote_id)
        if not v:
            raise VoteNotFoundError(f"Vote {vote_id} not found")
        results = self.vote_repo.get_results(vote_id)
        if v.is_anonymous:
            return {"vote_id": vote_id, "is_anonymous": True, "results": results}
        else:
            voters = self.vote_repo.get_voter_ids(vote_id)
            named = {}
            for opt in v.options:
                named[opt] = [aid for aid, o in voters if o == opt]
            return {"vote_id": vote_id, "is_anonymous": False, "results": named}
