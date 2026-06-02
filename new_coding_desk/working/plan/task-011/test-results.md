# Test Results: Task-011

## Status
EXPECTED

## Test Results

| Test | Result | Expected | Blocked | Details |
|------|--------|----------|---------|---------|
| test_all_events_mapped | PASS | PASS | no | - |
| test_register_bridge_does_not_raise | PASS | PASS | no | - |
| test_event_with_meeting_id_broadcasts_to_room | PASS | PASS | no | - |
| test_event_without_meeting_id_broadcasts_all_rooms | PASS | PASS | no | - |
| test_checkin_prompt_with_seat_id_sends_to_target_seat | PASS | PASS | no | - |
| test_checkin_prompt_without_seat_id_falls_back_to_broadcast | PASS | PASS | no | - |
| test_event_with_unknown_meeting_id_creates_room | PASS | PASS | no | - |
| test_non_dict_payload_is_safely_ignored | PASS | PASS | no | - |
| test_event_name_maps_to_correct_ws_type | PASS | PASS | no | uses speaker_seat_set (1:1 mapping) |
| test_ensure_future_on_main_loop (ws_event_bridge) | PASS | PASS | no | - |
| test_run_coroutine_threadsafe_from_other_thread (ws_event_bridge) | PASS | PASS | no | - |
| test_full_pipeline_publish_to_broadcast | PASS | PASS | no | WS type now "service_update" per frontend |
| test_ensure_future_on_main_loop (desk_coordinator, CR-004) | PASS | PASS | no | desk_coordinator._run_async thread-safety |
| test_run_coroutine_threadsafe_from_other_thread (desk_coordinator, CR-004) | PASS | PASS | no | cross-thread scheduling |
| test_raises_when_no_main_loop_set (desk_coordinator, CR-004) | PASS | PASS | no | clear error when uninitialized |
| test_on_serial_seat_occupied_publishes_to_event_bus (SR-002) | PASS | PASS | no | desk._on_serial -> EventBus |
| test_on_serial_seat_vacant_publishes_to_event_bus (SR-002) | PASS | PASS | no | desk._on_serial -> EventBus |
| test_on_speaker_seat_publishes_speaker_seat_set (CR-006) | PASS | PASS | no | desk.on_speaker_seat -> EventBus |
| test_on_speaker_clear_publishes_speaker_seat_clear (CR-006) | PASS | PASS | no | desk.on_speaker_clear -> EventBus |
| test_on_meeting_end_publishes_meeting_ended (CR-006) | PASS | PASS | no | desk.on_meeting_end -> EventBus |
| test_on_translation_result_publishes_translation_final (CR-006) | PASS | PASS | no | includes is_final: True in payload |
| test_on_service_call_publishes_service_call_created (CR-006) | PASS | PASS | no | desk.on_service_call -> EventBus |
| test_on_vote_start_publishes_vote_started (CR-006) | PASS | PASS | no | desk.on_vote_start -> EventBus |
| test_on_vote_close_publishes_vote_closed (CR-006) | PASS | PASS | no | desk.on_vote_close -> EventBus |
| test_persist_vote_cast_publishes_vote_updated (CR-008) | PASS | PASS | no | persist_vote_cast -> EventBus vote_updated |
| test_persist_vote_cast_no_publish_on_invalid_vote (CR-008) | PASS | PASS | no | no publish when vote not found |
| test_persist_service_call_publishes_service_call_created (CR-008) | PASS | PASS | no | persist_service_call -> EventBus service_call_created |
| Step 4: app startup verification | PASS | PASS | no | `python -c "from backend.main import app; print('OK')"` outputs OK |

## Unfixed Blocked Tests

None.

## Summary
- EXPECTED (Result=Expected, Blocked=no): 28
- UNEXPECTED (Result≠Expected, Blocked=no): 0
- Blocked (Blocked=yes): 0
