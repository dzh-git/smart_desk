"""
Demo seed data — quick-showcase meeting with realistic state.

Controlled by ENABLE_DEMO_SEED=true environment variable.

Rules:
    - Default off (ENABLE_DEMO_SEED must be explicitly "true").
    - Only seeds when no meetings exist in the database (idempotent).
    - Never modifies or supplements existing data.
    - Creates attendees, seat states, votes, service calls, and
      translation records consistent with each other.

Usage (in main.py lifespan):
    from backend.seed_demo import seed_demo_data
    db = SessionLocal()
    try:
        SeatRepository.init_seats(db)
        seed_demo_data(db)
    finally:
        db.close()
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.models.agenda import Agenda
from backend.models.attendee import Attendee
from backend.models.meeting import Meeting
from backend.models.seat_state import SeatState
from backend.models.service_call import ServiceCall
from backend.models.speaker_seat import SpeakerSeat
from backend.models.translation_record import TranslationRecord
from backend.models.vote import Vote

logger = logging.getLogger(__name__)


def seed_demo_data(db: Session) -> None:
    """Seed demo data if ENABLE_DEMO_SEED=true and no meetings exist.

    Idempotent: subsequent calls with existing meetings are no-ops.
    """
    enabled = os.environ.get("ENABLE_DEMO_SEED", "").lower() == "true"
    if not enabled:
        logger.debug("seed_demo_data: disabled (ENABLE_DEMO_SEED != true)")
        return

    existing = db.query(Meeting).count()
    if existing > 0:
        logger.info(
            "seed_demo_data: %d meetings already exist, skipping",
            existing,
        )
        return

    now = datetime.now(timezone.utc)

    # ── 1 active meeting ────────────────────────────────────────────────
    meeting = Meeting(
        title="2026年第二季度产品评审",
        description="演示用—产品路线图评审会议",
        status="active",
        created_at=now,
        started_at=now,
    )
    db.add(meeting)
    db.flush()

    # ── 5 agenda items ──────────────────────────────────────────────────
    for item in [
        ("开场致辞", 1),
        ("产品路线图回顾", 2),
        ("技术方案评审", 3),
        ("市场策略讨论", 4),
        ("总结与下一步计划", 5),
    ]:
        db.add(Agenda(meeting_id=meeting.id, title=item[0], sort_order=item[1]))
    db.flush()

    # ── 8 attendees ─────────────────────────────────────────────────────
    # First 4 will be checked in (seats 1-4), last 4 unbound.
    attendee_names = [
        ("张伟", "产品总监"),
        ("李娜", "技术经理"),
        ("王强", "市场总监"),
        ("陈静", "前端工程师"),
        ("刘洋", "后端工程师"),
        ("赵磊", "测试工程师"),
        ("孙莉", "设计师"),
        ("周明", "运营主管"),
    ]
    attendees = []
    for name, title in attendee_names:
        att = Attendee(
            meeting_id=meeting.id,
            name=name,
            title=title,
            seat_id=None,
            checked_in=False,
        )
        db.add(att)
        attendees.append(att)
    db.flush()

    # ── 10 seat_states (mix of states) ──────────────────────────────────
    # Seat 1-4: checked_in (bound to attendees 0-3)
    # Seat 5-6: occupied_unchecked (no attendee bound yet)
    # Seat 7-10: vacant
    seat_assignments: list[tuple[int, int | None, str]] = [
        (1, attendees[0].id, "checked_in"),
        (2, attendees[1].id, "checked_in"),
        (3, attendees[2].id, "checked_in"),
        (4, attendees[3].id, "checked_in"),
        (5, None, "occupied_unchecked"),
        (6, None, "occupied_unchecked"),
        (7, None, "vacant"),
        (8, None, "vacant"),
        (9, None, "vacant"),
        (10, None, "vacant"),
    ]
    for seat_id, att_id, status in seat_assignments:
        seat = db.get(SeatState, seat_id)
        if seat is not None:
            seat.status = status
            seat.attendee_id = att_id
            seat.updated_at = now

    # Update attendee bindings for checked-in attendees
    for idx in range(4):
        attendees[idx].seat_id = seat_assignments[idx][0]
        attendees[idx].checked_in = True
    db.flush()

    # ── 1 speaker seat (preserved — seat 1) ─────────────────────────────
    speaker = db.get(SpeakerSeat, 1)
    if speaker is not None:
        speaker.seat_id = 1

    # ── 1 open vote ────────────────────────────────────────────────────
    vote = Vote(
        meeting_id=meeting.id,
        title="是否批准2026年Q3产品路线图",
        options_json=json.dumps(["批准", "修改后批准", "不批准"]),
        is_anonymous=False,
        status="open",
        created_at=now,
    )
    db.add(vote)

    # ── 1 pending service call ─────────────────────────────────────────
    sc = ServiceCall(
        meeting_id=meeting.id,
        seat_id=3,
        service_type="coffee",
        status="pending",
        created_at=now,
    )
    db.add(sc)

    # ── 2 translation records ──────────────────────────────────────────
    translations = [
        TranslationRecord(
            meeting_id=meeting.id,
            seat_id=1,
            source_lang="zh",
            target_lang="en",
            source_text="欢迎各位参加今天的会议",
            translated_text="Welcome everyone to today's meeting",
            created_at=now,
        ),
        TranslationRecord(
            meeting_id=meeting.id,
            seat_id=2,
            source_lang="zh",
            target_lang="en",
            source_text="接下来我们讨论产品路线图",
            translated_text="Next, let's discuss the product roadmap",
            created_at=now,
        ),
    ]
    for tr in translations:
        db.add(tr)

    db.commit()
    logger.info("seed_demo_data: demo data created successfully")
