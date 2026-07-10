# Arduino 灯带串口协议

本文件冻结 `arduino_nano_controller` 与主程序 `new_coding_desk` 之间的 USB 串口通信协议。协议定位为"简单、文本化、易调试"，是集成第一阶段（Phase 1）的产出，供 Phase 2 固件改造与 Phase 3 后端 `ArduinoManager` 双方对齐实现。

协议冻结后，任何一方的实现都以本文件为准。修改协议必须同步更新本文件。

## 1. 设计原则

- Arduino 只是灯效执行端，不理解会议业务。
- 主程序只下发中性的模式/亮度命令，业务事件到模式的转换由主程序 `LightingManager` 完成。
- 命令与响应均为纯文本行，便于用 Arduino IDE 串口监视器直接手工调试。
- 协议只包含最小必要命令，第一阶段不引入 `MEETING START`、`VOTE OPEN` 等业务命令。

## 2. 串口参数

| 参数 | 值 |
| --- | --- |
| 波特率 baudrate | `115200` |
| 数据位 / 停止位 / 校验 | 8 / 1 / None |
| 编码 | ASCII（兼容 UTF-8） |
| 行结束符 | `\n`（LF，`0x0A`） |

说明：

- 主程序发送命令时以 `\n` 结尾。Arduino 逐字节读取，遇到 `\n` 视为一条完整命令。
- Arduino 的每条响应/上报同样以 `\n` 结尾，一行一条。
- 建议忽略行尾可能出现的 `\r`（`0x0D`），以兼容不同串口工具。

## 3. 命令集（主程序 → Arduino）

| 命令 | 语法 | 示例 | 用途 |
| --- | --- | --- | --- |
| `PING` | `PING` | `PING` | 心跳检测，确认设备在线 |
| `SET_MODE` | `SET_MODE <mode>` | `SET_MODE VOTE_OPEN` | 切换灯效模式，`<mode>` 见第 5 节枚举 |
| `SET_BRIGHTNESS` | `SET_BRIGHTNESS <0-255>` | `SET_BRIGHTNESS 40` | 设置全局亮度 |
| `OFF` | `OFF` | `OFF` | 熄灭灯带（等价于进入 `OFF` 模式） |

命令解析约定：

- 命令关键字统一大写。
- 关键字与参数之间用单个空格分隔。
- 未识别的命令关键字返回 `ERR UNKNOWN_COMMAND`。

### 3.1 SET_BRIGHTNESS 与供电安全

- 协议对外统一接受 `0-255` 的亮度值，主程序无需关心硬件供电上限。
- 固件内部会将收到的亮度裁剪到供电安全上限 `80`（对应现有 `MAX_LED_BRIGHTNESS`）。即传入大于 80 的值时，实际亮度按 80 生效，但仍返回 `OK`。
- 传入超出 `0-255` 范围或非数字的参数返回 `ERR BAD_ARG`。

## 4. 响应与上报（Arduino → 主程序）

| 类型 | 语法 | 示例 | 含义 |
| --- | --- | --- | --- |
| 心跳响应 | `PONG` | `PONG` | 对 `PING` 的应答 |
| 成功响应 | `OK <原命令回显>` | `OK SET_MODE IDLE` | 命令执行成功，回显原命令便于主程序匹配 |
| 错误响应 | `ERR <错误码>` | `ERR UNKNOWN_MODE` | 命令执行失败 |
| 事件上报 | `EVENT <类型> <值>` | `EVENT PIR 1` | Arduino 主动上报的传感器事件 |

### 4.1 错误码

| 错误码 | 触发条件 |
| --- | --- |
| `UNKNOWN_COMMAND` | 命令关键字无法识别 |
| `UNKNOWN_MODE` | `SET_MODE` 的模式名不在枚举内 |
| `BAD_ARG` | 参数缺失、非数字或超出取值范围（如亮度非 0-255） |

### 4.2 PIR 事件上报

第一阶段正式纳入 PIR 上报，格式如下：

| 上报 | 含义 |
| --- | --- |
| `EVENT PIR 1` | 复合入座判定成立（上升沿）：SR505 PIR 高电平 **且** VL53L0X 激光测距 <100mm（取最近 8 次均值，约 266ms 窗口）→ 判有人入座 |
| `EVENT PIR 0` | 复合入座判定解除（下降沿）：PIR 变低 或 测距 ≥100mm（人离远 / 离开）→ 判无人 |

说明：

- PIR 事件仅在状态发生跳变（边沿）时上报一次，避免每帧刷屏。
- PIR 上报独立于灯效命令：主程序是否据此做业务反应由主程序决定，Arduino 只负责如实上报。
- 第一阶段 Arduino 收到 `SET_MODE` 后以主程序命令为准，PIR 不再自行改变业务灯效，只做事件上报。
- 入座判定为复合条件：`EVENT PIR 1` 不再由单纯 PIR 高电平产生，而是 **SR505 PIR 高电平 且 VL53L0X（I2C，A4=SDA / A5=SCL）测距均值 <100mm**。测距取最近 `TOF_SAMPLES=8` 次采样平均（约 266ms 滑动窗口）以平滑临界抖动；仅 PIR 触发但人距桌面 ≥100mm（如路过人员）不会上报 `EVENT PIR 1`，从而避免误触迎宾灯。

### 4.3 PIR → 灯效联动（主程序侧实现约定）

第一阶段已确认：有人坐下时主程序联动 `WELCOME` 迎宾灯效。该逻辑由主程序 `LightingManager`（Phase 4）实现，规则如下：

| 条件 | 主程序动作 | 灯效结果 |
| --- | --- | --- |
| 当前模式为 `IDLE`，收到 `EVENT PIR 1` | 下发 `SET_MODE WELCOME` | 中心能量点亮一次性动画（青绿，约 5s 后自动回 `IDLE`） |
| 当前模式非 `IDLE`（如 `MEETING_ACTIVE` / `VOTE_OPEN` 等会议业务模式） | 忽略 `EVENT PIR 1`，不改灯 | 维持当前业务灯效 |

约定：

- 仅在 `IDLE` 待机状态下联动，避免会议进行中有人走动触发迎宾灯造成干扰。
- `WELCOME` 为**一次性动画**：固件播放完整段（中心外扩 → 约 5s 缓慢呼吸）后**自动回 `IDLE`**，主程序无需再下发 `IDLE`。因此删除了原「`EVENT PIR 0` 驱动回 `IDLE`」规则——`EVENT PIR 0` 仅作占用感知上报，不再参与灯效回退。
- `PIR` 事件本身已是边沿触发（入座/离座各报一次），主程序无需额外去抖；如需更稳，可在主程序侧加 1–2 秒软件去抖，可选。
- 后端 `current_mode` 在发送 `WELCOME` 后记为 `WELCOME`，但固件侧会自动回 `IDLE`；下次 `EVENT PIR 1` 仍可在 `IDLE` 下再次触发 `WELCOME`，状态不影响后续联动。

## 5. 灯效模式枚举

`SET_MODE` 的合法 `<mode>` 取值共 11 种，与主程序后端 `lighting_modes.py`（Phase 4）保持一一对应。固件动画全部要求非阻塞（基于 `millis()` 驱动，禁止长时间 `delay()`）。

| 模式 | 含义 | 固件灯效（Phase 2 目标） |
| --- | --- | --- |
| `BOOT` | Arduino 启动或主程序刚连接 | 白色短闪 |
| `IDLE` | 系统空闲 | 青色低亮呼吸（沿用现有效果） |
| `WELCOME` | 欢迎 / 签到（IDLE 下 `EVENT PIR 1` 触发） | 中心能量点亮一次性动画，约 5s 后自动回 `IDLE` |
| `MEETING_ACTIVE` | 会议进行中 | 蓝白常亮或缓慢呼吸 |
| `AGENDA_ACTIVE` | 当前议程进行中 | 柔和白色聚焦 |
| `VOTE_OPEN` | 投票进行中 | 黄色脉冲 |
| `AI_SPEAKING` | AI / 语音相关状态 | 紫色流水 |
| `SERVICE_CALL` | 服务呼叫提醒 | 橙红闪烁 |
| `MEETING_ENDED` | 会议结束动画 | 绿色收束后自动进入 `IDLE` |
| `ERROR` | 硬件或通信错误 | 红色慢闪 |
| `OFF` | 熄灭 | 灯带全灭 |

约定：

- 模式名统一大写，主程序与固件严格一致。
- `MEETING_ENDED` 播放完收束动画后由固件自动切回 `IDLE`，主程序无需再下发 `IDLE`。

## 6. 调试示例

使用 Arduino IDE 串口监视器（波特率 115200，行结束符设为 "换行符 NL"）逐条输入：

```text
发送: PING
返回: PONG

发送: SET_MODE IDLE
返回: OK SET_MODE IDLE
（灯带进入青色低亮呼吸）

发送: SET_MODE MEETING_ACTIVE
返回: OK SET_MODE MEETING_ACTIVE

发送: SET_MODE VOTE_OPEN
返回: OK SET_MODE VOTE_OPEN
（灯带进入黄色脉冲）

发送: SET_BRIGHTNESS 40
返回: OK SET_BRIGHTNESS 40

发送: SET_BRIGHTNESS 200
返回: OK SET_BRIGHTNESS 200
（实际亮度被裁剪到 80）

发送: OFF
返回: OK OFF
（灯带熄灭）

发送: SET_MODE UNKNOWN
返回: ERR UNKNOWN_MODE

发送: FOO
返回: ERR UNKNOWN_COMMAND

发送: SET_BRIGHTNESS abc
返回: ERR BAD_ARG
```

有人入座 / 离座时会异步看到（与上述命令交错出现）：

```text
EVENT PIR 1
EVENT PIR 0
```

## 7. 实现约束备注（给 Phase 2 / Phase 3）

固件侧（Phase 2）：

- 所有动画基于 `millis()` 非阻塞渲染，主循环需保持对串口输入的响应，禁止长时间 `delay()`。
- 用一个行缓冲区累积串口字节，遇 `\n` 解析一条命令；缓冲区应有上限并对超长输入容错。
- 未知输入必须返回对应 `ERR`，不能静默忽略，以便主程序诊断。
- 亮度裁剪逻辑放在固件内部，对外仍回显主程序传入的原始值。

主程序侧（Phase 3）：

- `ArduinoManager` 按行读取响应，通过 `OK <原命令>` 回显匹配命令，通过 `PONG` 判定在线。
- 写命令需设置写超时（见 `config/smartdesk.integration.json` 的 `write_timeout_seconds`），发送失败只记日志不抛业务异常。
- 串口参数（COM 口、波特率、心跳/重连间隔）一律从 `config/smartdesk.integration.json` 读取，不硬编码。
