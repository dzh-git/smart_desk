# SmartDesk 运行库与语音问题修复报告（2026-06-04）

## 已修复

1. 运行数据库位置
   - `backend/database.py` 默认数据库从项目目录 `smart_desk.db` 改为 `%LOCALAPPDATA%\SmartDesk\smart_desk.db`。
   - `start.bat` 启动时设置 `SMART_DESK_DB_PATH=%LOCALAPPDATA%\SmartDesk\smart_desk.db`。
   - 目的：避开项目目录内 SQLite journal 写入 `disk I/O error` 的问题。

2. 语音上传链路
   - `frontend/src/composables/useAudioRecorder.js`
     - AudioWorklet 接入静音 gain，再接到 destination，保证浏览器持续驱动录音处理器。
     - 用户手动再次点击麦克风停止时，现在会先把缓存音频作为 final 上传，不再直接丢弃 `_rawChunks`。
   - `frontend/src/components/TranslationPanel.vue`
     - 麦克风停止动作改为 `await stopRecording({ finalize: true })`。
     - 面板打开后主动触发 `/api/translations/preload` 后台加载。
     - 预加载错误会显示在翻译面板中。

3. 模型加载与 sentencepiece 崩溃保护
   - `speech_module/speech_module.py`
     - 预加载前先检查 `torch`、`funasr`，缺依赖时抛普通 `RuntimeError`，不继续触碰模型原生库。
     - 机器翻译 MT 只有设置 `SMART_DESK_ENABLE_MT=1` 时才加载。
   - `speech_module/mt_engine.py`
     - 缺 `torch` 或未显式启用 MT 时，不加载 MarianTokenizer/sentencepiece。
     - 这避免了 `sentencepiece` C++ 扩展导致 `python.exe` 直接弹内存读取错误。
   - `backend/routers/translation.py`
     - `/api/translations/preload` 改为后台加载，立即返回 `{ready, loading, error}`。
     - `/api/translations/preload/status` 也返回 `error` 字段。

4. 依赖声明
   - `backend/requirements.txt`
     - 新增 `torch>=2.2.0`。
     - `transformers` 限制为 `>=4.40.0,<5`。
     - `sentencepiece` 固定为 `0.2.0`，避免继续使用本机已触发崩溃的 `0.2.1` 组合。

5. 测试隔离
   - `conftest.py`、`tests/conftest.py`
     - 测试数据库使用进程隔离文件名，避免并行 pytest 互相清库。
     - 测试临时目录固定到 `%TEMP%\smart_desk_tests`，并覆写 pytest 运行中的 `tempfile.mkdtemp()`，避开 Windows 随机临时目录 ACL 异常。

## 已验证

| 验证项 | 结果 |
|---|---|
| 缺依赖下调用 `SpeechModule.preload()` | 返回普通 `RuntimeError: Missing required speech dependency: torch`，不再弹 python.exe 内存错误 |
| 未启用 MT 下调用 `MTEngine.preload()` | 返回普通 `RuntimeError: Machine translation preload is disabled` |
| `pytest tests -q` | 335 passed, 1 skipped |
| `pytest speech_module\tests -q` | 8 passed, 3 skipped |
| `npm.cmd run build` | 通过，仅有 chunk size 警告 |

## 当前仍不能完成的部分

真实语音识别/翻译模型测试尚未完成，因为当前后端 Python 环境为：

- `python`: `D:\ProgramData\anaconda3\python.exe`
- `torch`: 未安装
- `funasr`: 因缺 `torch` 无法导入
- `sentencepiece`: 当前环境为 `0.2.1`，直接加载本地 `.spm` 曾触发 `python.exe` 原生崩溃
- `transformers`: 当前环境为 `5.10.1`

我已尝试请求安装/更新 `backend\requirements.txt` 依赖，但权限审查超时，未对 Python 环境执行安装。

## 下一步

1. 安装后端依赖：
   - `python -m pip install -r backend\requirements.txt`
2. 安装完成后再运行：
   - `set SMART_DESK_RUN_SLOW_MODELS=1`
   - `set SMART_DESK_ENABLE_MT=1`
   - `pytest speech_module\tests\test_mt_engine.py -q`
3. 重新用 `start.bat` 启动，进入发言席后测试：
   - 点击麦克风开始
   - 说话 2 秒以上
   - 再次点击麦克风停止
   - 检查 `/api/translations/audio` 是否收到 final 上传，以及页面是否显示识别/翻译结果
