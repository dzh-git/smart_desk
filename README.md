# SmartDesk 智能会议桌

SmartDesk 是一个本地运行的九席智能会议系统。`seat 1` 为主持人位，`seat 2..9` 为参会位。

## 项目结构

| 目录 | 职责 |
|---|---|
| `new_coding_desk/` | React 前端、FastAPI 后端、语音翻译、Display Agent 与席位代理。 |
| `smartdesk_gesture_controller/` | 摄像头手势识别、模式状态机及中央大屏应用切换。 |
| `arduino_nano_controller/` | Arduino Nano 灯光固件与串口协议。 |
| `config/` | 三模块共享的实体集成配置。 |
| `docs/` | 产品、部署与归档资料。 |
| `graphify-out/` | 根级代码知识图谱。 |

当前规范入口见 [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)。归档资料不定义当前接口或产品行为。

## 启动

```powershell
cd new_coding_desk
.\start.bat
```

`start.bat` 默认启动会议前后端和 Display Agent。屏幕串流仍由 `ENABLE_SCREEN_STREAM=true` 单独启用。

手势控制器单独启动：

```powershell
cd smartdesk_gesture_controller
.\start_gesture.bat
```

使用 I Love You 手势右滑在会议屏与 PowerPoint 间切换，左滑在会议屏与 SolidWorks 间切换。PowerPoint 和 SolidWorks 文件需提前打开。

## 验证

```powershell
cd smartdesk_gesture_controller
.venv\Scripts\python -m pytest tests -q

cd ..\new_coding_desk
pytest -q
cd frontend
npm run typecheck
npm test -- --run
npm run build
```

## Graphify

架构问题先查询根图谱：

```powershell
graphify query "手势如何切换中央大屏应用？"
```

代码或当前规范变化后更新：

```powershell
scripts\\graphify_update_single.bat
```

该脚本设置 `GRAPHIFY_NO_BACKUP=1`，只更新 `graphify-out/graph.json` 等根级当前快照，不在仓库中创建按日期命名的备份目录。若直接调用 Graphify，可临时使用：

```powershell
$env:GRAPHIFY_NO_BACKUP = "1"
graphify update .
```

交互式 HTML 按需生成：`graphify export html`。
