# Changes: Task-005

## Files
- [new] D:\learning\smart_desktop\smart-desk\backend\repositories\vote_repository.py
- [new] D:\learning\smart_desktop\smart-desk\tests\test_vote_repository.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\models.py

## Summary
Implemented `VoteRepository` with full CRUD for votes and vote records:
- `create` - create votes with options (as JSON), default status "open"
- `get_by_id` - lookup by vote_id, optional meeting_id scope
- `list_by_meeting` - list all votes for a meeting
- `get_active` - find open vote for a meeting (returns `None` if none open)
- `close` - close a single vote, sets `closed_at` timestamp
- `close_all_open` - bulk-close all open votes for a meeting, returns count
- `get_all_open` - get all open votes (used for per-vote close events)
- `cast` - submit or update a vote record (upsert on attendee dedup)
- `get_results` - tally results with zero-count options for all vote options
- `get_voter_ids` - list (attendee_id, option) tuples for a vote

Added `closed_at` column to `Vote` model (was missing; `is_anonymous` already existed).
