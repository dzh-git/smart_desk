# Changes: Task-012

## Files
- [new] backend/routers/attendees.py
- [mod] backend/routers/meetings.py
- [mod] backend/main.py
- [new] tests/test_meetings_router.py

## Summary
Refactored meetings router to use MeetingService instead of inline SQLAlchemy queries. Extracted attendee endpoints to new attendees.py router. Added missing endpoints: GET /api/meetings/active, POST /api/meetings/{id}/start, POST /api/meetings/{id}/end. Switched all endpoints to unified response format {"success": bool, "message": str, "data": {}}. Registered attendees router in main.py.
