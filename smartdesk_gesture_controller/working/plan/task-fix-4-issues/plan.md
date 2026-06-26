# 修复计划：pause启动模式 / 日志字段清理 / stable_gesture重置 / mode_swipe_timeout默认值

## 问题1：双击 start_gesture.bat 仍进入 pause 模式

### 根因
`hands/gesture_config.py` 数据类默认值已改为 `False`（第181-182行），但 `config_from_args()` 第330行**无条件覆盖**：
```python
config.pause_on_start = not (args.no_pause_on_start or args.start_unpaused)
```
双击 bat 无参数时 `not (False or False)` = `True` → 强制暂停。

### 修复
改为仅在显式传标志时才覆盖默认值：
```python
if args.no_pause_on_start or args.start_unpaused:
    config.pause_on_start = False
    config.start_paused = False
```

---

## 问题2：日志中移除 mode_before_state_step / mode_after_state_step / state_result_mode

### 根因
三字段产生于 `hands/gesture_replay.py` `_build_record()` 第223-225行。

### 修复
- `_build_record()`：删除 `mode_after`/`state_result_mode` 参数及返回 dict 中三字段，保留 `mode` 和 `mode_changed`
- `record_frame()`：删除 `mode_after`/`state_result_mode` 参数
- `gesture_controller.py` `_process_frame()`：删除调用时两参数
- `tests/test_gesture_replay.py`：移除三字段断言及参数
- `working/日志字段说明.md`：移除三字段描述

---

## 问题3：手丢失超时后 stable_gesture 未重置为 None

### 根因
`gesture_intent_tracker.py` `_handle_hand_absent()` fire 分支清理了 session/attempt/hold_attempt/zoom，但遗漏 `_stable_gesture`。`update()` 手丢失时提前 return，不调用 `_update_candidate()`（唯一清空路径）。

### 修复
在 fire 分支 zoom 重置后添加：
```python
self._stable_gesture = None
self._stable_since = 0.0
self._gesture_history.clear()
```
新增测试：手丢失超时后断言 `_stable_gesture is None`。

---

## 问题4：mode_swipe_timeout 默认值改为 3

### 修复
- `gesture_config.py` 第159行 `1.20` → `3.0`
- `tests/test_gesture_intent_tracker.py` 第74行 `1.20` → `3`
- `docs/CONFIG_SPEC.md` 第143、437行 → `3`

---

## 关键文件清单
| 文件 | 修改内容 |
|------|----------|
| `hands/gesture_config.py` | 问题1（330-331行）、问题4（159行） |
| `hands/gesture_intent_tracker.py` | 问题3（511-513行新增重置） |
| `hands/gesture_replay.py` | 问题2（_build_record + record_frame 移除三字段及参数） |
| `hands/gesture_controller.py` | 问题2（_process_frame 调用移除两参数） |
| `tests/test_gesture_replay.py` | 问题2（移除三字段断言及参数） |
| `tests/test_gesture_intent_tracker.py` | 问题3（新增测试）、问题4（第74行默认值） |
| `working/日志字段说明.md` | 问题2（移除三字段描述） |
| `docs/CONFIG_SPEC.md` | 问题4（mode_swipe_timeout 默认值） |
