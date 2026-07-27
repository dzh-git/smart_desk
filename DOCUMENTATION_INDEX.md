# SmartDesk 文档索引与统一约定

本文件是唯一文档导航。冲突时以表中“权威文档”为准，`docs/archive/` 不参与裁决。

## 当前统一基线

- 9 个完整席位：`seat 1` 为主持人位，`seat 2..9` 为八个参会位。
- 主程序：`new_coding_desk/`。
- 席位终端：`android_tablet/`；正式会议页面仍唯一位于
  `new_coding_desk/frontend/`。
- 手势控制：`smartdesk_gesture_controller/`，运行在中央 Windows 主机。
- 灯控固件：`arduino_nano_controller/`。
- I Love You 右滑控制 PowerPoint，左滑控制 SolidWorks；应用切换统一通过 Display Agent `127.0.0.1:8766`。
- 手势状态服务 `ws://127.0.0.1:8765` 仅提供诊断状态，不写入会议业务。

## 权威来源

| 主题 | 权威文档 |
|---|---|
| 产品范围与实体约束 | `docs/product/project-goals.md`、`docs/product/智能会议桌实体集成需求.md` |
| 总体架构 | `new_coding_desk/docs/system_architecture.md` |
| HTTP、WebSocket 与事件 | `new_coding_desk/docs/API_SPEC.md`、`WEBSOCKET_PROTOCOL.md`、`EVENT_BUS_SPEC.md` |
| 前端状态、交互与视觉 | `new_coding_desk/docs/FRONTEND_STATE_SPEC.md`、`FRONTEND_INTERACTION_SPEC.md`、`FRONTEND_VISUAL_SPEC.md` |
| 中央大屏与应用切换 | `new_coding_desk/docs/HOST_DISPLAY_CONTRACT.md` |
| 手势映射与切屏 | `smartdesk_gesture_controller/docs/GESTURE_AND_DISPLAY_SPEC.md` |
| 手势配置与状态 | `smartdesk_gesture_controller/docs/CONFIG_AND_STATUS_SPEC.md` |
| 手势部署与验收 | `smartdesk_gesture_controller/docs/OPERATIONS_AND_ACCEPTANCE.md` |
| Arduino 串口协议 | `arduino_nano_controller/protocol.md` |
| 三模块部署联调 | `docs/deployment/智能会议桌硬件集成-部署与联调.md`、`new_coding_desk/docs/DEMO_RUNBOOK.md` |
| Android 平板、Bridge 与人脸标定 | `android_tablet/README.md`、`android_tablet/docs/CALIBRATION.md` |

## 维护规则

1. 接口或产品行为变更时，同步修改对应权威文档与测试。
2. 席位统一写作“9 席（1 名主持人 + 8 名参会者）”。
3. Windows 窗口发现、移动和激活只在 Display Agent 中实现。
4. 手势模块不写会议数据库，不发布会议业务事件。
5. 根级 `graphify-out/` 是唯一代码图谱；架构查询不得使用历史归档或旧子图。
6. `docs/archive/` 只用于追溯，不复制当前接口细节。
