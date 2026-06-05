# Phase 04: 后端会议与座位正确性

## 阶段目标

修复会议生命周期、座位签到和座位事件广播，并提供受控的开发演示座位接口。

## 前置条件与允许读取

- Phase 03 已通过验证。
- 可读取本阶段文档、`docs/API_SPEC.md`、`docs/EVENT_BUS_SPEC.md`、`docs/WEBSOCKET_PROTOCOL.md` 和相关后端模块。

## 允许修改范围

- 后端会议、座位、参会者、事件广播和开发接口模块
- 对应后端测试
- 不修改前端页面

## 修改内容

- 会议结束时执行规范要求的座位与活动投票处理。
- 签到时校验参会者，绑定座位并更新签到状态。
- 确保座位变化事件携带会议 ID，可被 WebSocket 房间广播。
- 增加受 `ENABLE_DEMO_SEAT_API=true` 控制的接口：
  - `POST /api/dev/seats/{seat_id}/occupy`
  - `POST /api/dev/seats/{seat_id}/vacate`

## 验证与验收

先运行会议、座位和事件广播的定向 pytest，再运行：

```powershell
pytest -q
```

- 开发接口默认不可用，启用后可改变座位状态。
- 全量后端测试必须通过。

## 停止条件

任一后端测试失败或开发接口可在未启用时访问，不进入 Phase 05。
