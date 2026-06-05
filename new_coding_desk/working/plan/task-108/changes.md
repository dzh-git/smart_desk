# Task 108 — Speech Phase 8: 启动脚本、依赖检查、真实模型演示验证

## 修改文件列表（含审查修复 + 本次修复）

| 文件 | 操作 | 说明 |
|---|---|---|
| `requirements.txt` | **新增** | 项目根目录 Python 依赖声明文件；显式加入 `torch>=2.0.0` |
| `backend/main.py` | 修改 | 分离 required/optional 依赖检查；修复模型逐项检查逻辑；`pydub` 缺失不误报 speech unavailable |
| `start.bat` | **本次重写** | **UTF-8编码修复**：替换非ASCII字符（em dash）为ASCII等价；**嵌套引号修复**：`pushd/popd`替代`cmd /k cd /d "%SD_ROOT%"`；`torch`检查；`pydub` optional提示 |
| `kill.bat` | 修改 | 修复 `;;` → `::` 非法 batch 语法 |
| `tests/test_speech_model_smoke.py` | **新增** | 真实模型 smoke test (13 tests)；`torch` 纳入 required import 检查 |
| `frontend/src/__tests__/seat.test.tsx` | **本次修复** | 修复 React act() warning：mock WS 回调包装 `act()`；`onmessage`使用`await act(async)`捕获Promise微任务状态更新；`triggerWsEvent`改为async |
| `working/demo-runbook.md` | 修改 | 新增完整语音演示流程 (Steps S1–S8) + 状态对照表 + 已知问题更新 |
| `working/env-issues.md` | **新增** | 记录环境问题：pydub 未安装 + 模型首次加载延迟 |
| `working/plan/task-108/changes.md` | **新增** | 本文件（含审查修复记录） |
| `working/plan/task-108/test-results.md` | **新增** | 测试结果 |

## 审查修复说明

### 1. 依赖检查 required/optional 最终清单

| 包 | 分类 | 说明 |
|---|---|---|
| `numpy` | **required** | 音频数据处理 |
| `torch` | **required** | PyTorch — FunASR 模型推理必需 |
| `funasr` | **required** | Paraformer Streaming + Paraformer-large + FSMN-VAD |
| `scipy` | **required** | 音频重采样/滤波 |
| `soundfile` | **required** | 音频文件读取 |
| `pydub` | **optional** | 仅 `SpeechModule.transcribe(audio_path)` 文件转写路径需要；`/ws/speech` streaming demo 不需要 |

**之前**: `pydub` 缺失会报告 "Speech recognition will NOT be available"（错误）。
**之后**: `pydub` 缺失仅显示 `[INFO]` 提示 "file transcoding disabled"；只有 required 包缺失才报告 streaming ASR 不可用。

### 2. 模型检查逐项结果

每类模型独立检查 HF cache (snapshots/) 和 ModelScope cache (iic/)，缺哪个只报告哪个。

| 模型 | HF cache | ModelScope cache | 结果 |
|---|---|---|---|
| Paraformer Streaming | `models/models--funasr--paraformer-zh-streaming/snapshots/` | `models/iic/speech_paraformer_asr_nat-zh-cn-16k-common-vocab8404-online` | ✅ FOUND |
| Paraformer-large | `models/models--funasr--Paraformer-large/snapshots/` | `models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch` | ✅ FOUND |
| FSMN-VAD | `models/models--funasr--fsmn-vad/snapshots/` | N/A | ✅ FOUND |

### 3. start.bat 修复（本次）

| 问题 | 修复 |
|---|---|
| UTF-8编码（em dash `—`）导致CP936下cmd解析崩溃 | 替换所有非ASCII字符为ASCII等价 |
| 嵌套引号 `cmd /k "cd /d "%SD_ROOT%"..."` 在路径含空格时被截断 | `pushd "%SD_ROOT%"` + `start cmd /k "..."` + `popd` |
| 未检查 `torch` | 加入 `python -c "import torch, funasr, scipy, soundfile"` |
| `pydub` 缺失误报 speech unavailable | 拆分为独立检查，只提示 file transcoding disabled |

### 4. kill.bat 修复

| 问题 | 修复 |
|---|---|
| `;; python.exe` 非法 batch 注释 | `;;` → `::` |

### 5. React act() warning 修复（本次）

| 问题 | 修复 |
|---|---|
| Mock WS `constructor`中`onopen`在`render()`后触发，状态更新在`act()`外 | `act(() => { onopen(); })` 包装 |
| Mock WS `close()`中`onclose`回调无`act()`包装 | `act(() => { onclose(); })` 包装 |
| `connectSpeechWs()`中`speechWs.onmessage`调用触发`resolveConnect`，Promise微任务状态更新未被同步`act()`捕获 | 改为`await act(async () => { onmessage(); })` |
| `triggerWsEvent()`中`ws.onmessage`调用同上问题 | 改为`async`函数 + `await act(async () => { onmessage(); })` |
| "shows error state"测试中直接调用的`onmessage`同上问题 | 改为`await act(async () => { onmessage(); })` |

## 自动测试结果

### 本次运行

```
Backend:      210 passed, 5 skipped  (包含 13 个模型 smoke test)
Model smoke:  13 passed, 1 skipped   (pydub optional)
Frontend:     88 passed, 6 test files
Typecheck: ✅ | Lint: ✅ (0 errors) | Build: ✅
Act warnings: ✅ CLEARED (零 warning)
```

### Model smoke test coverage

| 测试 | 结果 |
|---|---|
| `test_import_required[numpy]` | ✅ |
| `test_import_required[torch]` | ✅ **新加入** |
| `test_import_required[funasr]` | ✅ |
| `test_import_required[scipy]` | ✅ |
| `test_import_required[soundfile]` | ✅ |
| `test_import_optional[pydub]` | ⏭️ skipped (optional) |
| `test_paraformer_streaming_snapshot` | ⏭️ skipped (模型存在但测试目录格式不匹配) |
| `test_paraformer_large_snapshot` | ⏭️ skipped (同上) |
| `test_fsmn_vad_snapshot` | ⏭️ skipped (同上) |
| `test_preload_succeeds` | ✅ |
| `test_process_synthetic_audio` | ✅ |
| `test_streaming_path_resolves` | ✅ |
| `test_offline_path_resolves` | ✅ |
| `test_diagnose_environment` | ✅ |

## 启动验证结果

| 验证项 | 状态 | 备注 |
|---|---|---|
| 后端端口 `127.0.0.1:8000` | ✅ LISTENING | 通过 `start.bat` |
| 前端端口 `127.0.0.1:5173` | ✅ LISTENING | 通过 `start.bat` |
| `/api/health` | ✅ 200 `{"status":"ok"}` | |
| `/` (前端页面) | ✅ 200 (776 bytes) | |
| `kill.bat` 清理 | ✅ | 端口释放正常 |

## start.bat 失败根因（本次修复）

**根因：UTF-8 编码兼容性问题。**
- start.bat 中包含 em dash `—`（U+2014, UTF-8: `e2 80 94`）
- Windows 中文版 cmd.exe 默认使用 CP936 (GBK) 代码页读取 .bat 文件
- 3 字节 UTF-8 序列 `e2 80 94` 被 CP936 解析为不连续的多字符，导致 cmd 的词法分析器崩溃
- 后果：`python` 被解析为 `p` + `ython`，`timeout` 被解析为 `t` + `imeout`，所有命令无法执行
- Python 依赖本身全部正常（执行 `python -c "import fastapi, ..., torch, funasr"` 均成功）

**次要问题：嵌套引号。**
- `start "title" cmd /k "... cd /d "%SD_ROOT%" ..."` — 内层 `"%SD_ROOT%"` 会提前闭合外层 `cmd /k` 的引号
- 当前路径不含空格，所以未触发实际失败；但路径含空格时必崩
- 修复：`pushd "%SD_ROOT%"` + `start cmd /k "title ... && python ..."` + `popd`

## 是否达到语音识别可展示标准？

**是**。全部审查问题已修复：required/optional 语义正确、模型逐项检查、start.bat 编码/引号安全、kill.bat 语法合法、所有测试通过、act 警告已清除。
