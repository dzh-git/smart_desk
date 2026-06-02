# Changes: Task-010

## Files
- [mod] D:\learning\smart_desktop\smart-desk\backend\services\translation_service.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\services\dashboard_service.py
- [mod] D:\learning\smart_desktop\smart-desk\tests\test_translation_service.py
- [mod] D:\learning\smart_desktop\smart-desk\tests\test_dashboard_service.py

## Summary
Implemented TranslationService and DashboardService per spec. Fixed all 8 review issues:
- CR-001: Replaced unreliable CJK auto-detection with explicit source_lang/target_lang params (default "zh"/"en")
- CR-002: Added meeting_id, source_lang, target_lang to translation_final event payload
- CR-003: Changed `if seat_id:` to `if seat_id is not None:` in get_history
- CR-004: self.mt now referenced in ready property (checks mt_engine readiness via getattr)
- CR-005: attendee_repo now used to resolve attendee names in get_dashboard seats block
- CR-006: Expanded test coverage from 4 tests to 42 tests (29 TranslationService + 13 DashboardService)
- CR-007: Replaced N+1 per-seat query in DashboardService with batch fetch via list_by_meeting, removed _resolve_attendee_name
- CR-008: Changed getattr(self.mt, 'ready', True) to getattr(self.mt, 'ready', False) — conservative default
