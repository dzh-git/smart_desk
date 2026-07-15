# SmartDesk 文档索引与统一约定

本文件是项目的文档导航和跨模块约定。它不替代各模块的接口规范；发生冲突时，按“权威来源”一节裁决。

## 当前统一基线

- **席位规模**：9 个完整席位，编号 `1..9`；`seat 1` 为主持人位，`seat 2..9` 为 8 个参会位。
- **每席硬件**：一个 Arduino Nano、WS2812B 灯带、SR505 PIR、VL53L0X，以及本席 Windows 终端和触控屏。
- **主程序**：`new_coding_desk/`，提供会议业务、前端、数据库、语音与翻译。
- **手势控制**：`smartdesk_gesture_controller/`，是中央主机上的独立本地进程；只向主程序暴露可选状态服务 `ws://127.0.0.1:8765`，不参与会议业务协议。
- **灯控固件**：`arduino_nano_controller/`。串口文本协议的唯一权威来源为 `arduino_nano_controller/protocol.md`。
- **部署模式**：`central` 用于单机/台架联调，由中央主机直接打开 1–9 号串口；`distributed` 用于正式分布式部署，每席 `Seat Edge Agent` 管理本地串口并通过 WebSocket 连接中央主机。

> 本次整理只统一文档和采购基线，不修改代码。后续实现、测试夹具和数据库初始化必须以 1–9 的席位范围收敛后，才能宣告运行时完全符合该基线。

## 权威来源与阅读顺序

| 主题 | 权威文档 | 说明 |
|---|---|---|
| 产品范围与席位布局 | `project-goals.md`、`智能会议桌实体集成需求.md` | 前者定义产品目标，后者用于与桌体合作方沟通。 |
| 总体架构 | `new_coding_desk/docs/system_architecture.md` | 主程序运行组件、边界和数据流。 |
| 前后端接口 | `new_coding_desk/docs/API_SPEC.md`、`new_coding_desk/docs/WEBSOCKET_PROTOCOL.md`、`new_coding_desk/docs/EVENT_BUS_SPEC.md` | HTTP、WebSocket 与业务事件的冻结契约。 |
| 前端状态与交互 | `new_coding_desk/docs/FRONTEND_STATE_SPEC.md`、`new_coding_desk/docs/FRONTEND_INTERACTION_SPEC.md`、`new_coding_desk/docs/FRONTEND_VISUAL_SPEC.md` | 三端 UI 的状态、交互和视觉规则。 |
| 灯控硬件 | `arduino_nano_controller/protocol.md` | 由 `config/smartdesk.integration.json` 决定当前串口映射。 |
| 手势控制 | `smartdesk_gesture_controller/docs/` | 映射、状态机、动作意图、配置、验收和状态卡规范。 |
| 部署与验收 | `scripts/智能会议桌硬件集成-部署与联调.md`、`new_coding_desk/docs/DEMO_RUNBOOK.md` | 前者覆盖三模块联调，后者覆盖主程序演示。 |

## 文档分类

### 维护中的规范文档

- `new_coding_desk/docs/`：主程序的接口、架构、运行与验收规范；`docs/adr/` 保存仍有效的技术决策。
- `arduino_nano_controller/protocol.md`：Arduino 与主程序/Seat Edge Agent 的串口协议。
- `smartdesk_gesture_controller/docs/`：手势识别与 Windows 输入控制规范。
- `project-goals.md`、`智能会议桌实体集成需求.md`：产品目标和实体桌集成约束。

### 规划、采购与现场参考

- `project_proposal/计划.md`：9 席实施计划和验收范围。
- `project_proposal/各组件连接方式.md`：实体设备连接与端口规划。
- `project_proposal/功能需求分析.md`：早期需求拆分，仅作方案讨论参考，不定义当前接口或实现。
- `project_proposal/智能会议桌项目计划书.docx`、`物品清单.docx`、`预算清单.xlsx`：采购和预算基线。
- `project_proposal/设备检查清单.docx`：现场设备验收清单。

### 非规范性材料

- `graphify-*/graphify-out/`：自动生成的代码关系图；需要重新运行 Graphify 更新，不作为产品或接口规范。
- `host_services/screen_stream/dxdiag*.txt`：机器诊断快照；仅供排障。
- `AGENTS.md`、`superteam-usage.md`、依赖清单、`总结与反思.txt`：协作、依赖或复盘材料，不定义产品行为。

## 维护规则

1. 新增或变更接口时，先改对应权威规范，再改实现与测试。
2. 不得在其他文档重新定义席位规模；统一写作“9 席（1 名主持人 + 8 名参会者）”。
3. 传感器型号、串口命令、灯效名以 Arduino 协议为准；规划文档只描述采购或部署，不复制协议细节。
4. 手势模块不得写入主程序会议事件或控制协议；主程序只可探测其可选状态服务。
5. 历史方案、生成报告和诊断输出必须明确标注其非规范性，不能作为实施依据。
