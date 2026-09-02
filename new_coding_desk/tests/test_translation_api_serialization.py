"""Regression tests for translation API response serialization."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from backend.api.translations import _to_json
from backend.schemas import ApiResponse
from backend.schemas.translation import TranslationRecordResponse


def test_translation_response_serializes_created_at_datetime() -> None:
    created_at = datetime(2026, 8, 9, 7, 5, 34, tzinfo=timezone.utc)
    record = TranslationRecordResponse(
        id=535,
        meeting_id=44,
        seat_id=1,
        source_lang="zh",
        target_lang="en",
        source_text="开放时间，早上九点至下午五点。",
        translated_text="Open from 9:00 a.m. to 5:00 p.m.",
        created_at=created_at,
    )

    response = _to_json(ApiResponse.ok(data=record), status_code=201)
    payload = json.loads(response.body)

    assert response.status_code == 201
    assert payload["data"]["created_at"] == "2026-08-09T07:05:34Z"
