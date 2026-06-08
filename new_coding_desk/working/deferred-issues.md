# SmartDesk — Deferred (Non-Blocking) Issues

> 本文档记录了已知但不阻塞演示流程的非关键问题。
> 记录时间: 2026-06-07 (Task 118)

---

## 1. 语音识别准确率（ASR）

**状态**: 已知 — 不阻塞演示

**实际测试结果**:
- E2E 测试使用 speech_sample.pcm（短中文音频）→ 识别结果为 "共青台。"
- 准确率取决于模型、音频质量和环境噪声；当前阶段不承诺准确率
- 较长或清晰的中文语音准确率可能更高，但未系统测试

**影响**: 演示时识别文本可能不完全准确，但不影响功能链路验证。
**解决方向**: 生产环境应使用定制微调模型或更高质量的 ASR 服务。
**当前任务**: 不解决 ASR 准确率问题。

---

## 2. 首次模型加载延迟

**状态**: 已知 — 不阻塞演示

**测试记录**:
- 首次 `start` 后，SpeechStreamService 触发模型懒加载
- 从 `process_pcm_frame` 首次调用到第一个 `translation_interim` 事件：约 **759ms**
- 这包括了模型加载 + PCM16 转换 + 流式 ASR 推理 + EventBus 发布
- 后续 frame 的延迟类似（持续流式推理）
- 但如果模型需要从 HuggingFace 首次下载，首次加载时间可达 **30-60 秒**

**影响**: 首次说话后需要等待 ~1 秒才看到字幕（已缓存模型时），如未缓存可能更久。
**解决方向**: 后端启动时预加载模型（通过 `preload()`），当前懒加载策略在预热后表现可接受。
**后续建议**: 在 `start.bat` 或启动脚本中添加选项，指定 `--preload-speech` 以预先加载模型。

---

## 3. Playwright 无法自动化真实麦克风

**状态**: 已知 — 不阻塞验证

**原因**: Playwright 的浏览器自动化不授予 `getUserMedia` 权限。
这是 Playwright 的已知限制（https://github.com/microsoft/playwright/issues/2971）。

**当前方案**:
- `deterministic-caption.spec.ts` 使用 mock WebSocket + 真实 speech WS
- `speech-consistency.spec.ts` 使用真实 speech WS + PCM fixture 文件
- 两个测试均在同一 utterance_id 上验证 caption 链路完整性

**替代验证方式**:
- 手动演示：使用真实麦克风 + 浏览器（见 `working/demo-runbook.md` §3）
- E2E 测试：覆盖 caption 显示、revision 替换、final 清理、三端一致性
- CI 中运行 E2E 测试（无需物理麦克风）

---

## 4. 数据库清理由旧 meetings 导致管理不便

**状态**: 低优先级

**说明**: 每次 E2E 测试会创建新的 meeting 但可能未清理。多次运行后
数据库会积累大量 finished/pending meeting。虽然 `ENABLE_DEMO_SEED_WHEN_NO_ACTIVE`
会在无 active meeting 时创建新 demo meeting，但数据量大会影响管理端体验。

**临时方案**: `del test.db && start.bat`
**改进方向**: 添加 `/api/meetings/cleanup` 端点或按保留天数自动清理。
**优先级**: 低（仅影响开发/演示环境，不影响功能）

---

## 5. start.bat 关闭窗口后的清理依赖 kill.bat

**状态**: 设计确认 — 不阻塞

**说明**: `start.bat` 使用 `start "title" cmd /k` 在新窗口中启动服务。
关闭 start.bat 窗口不会停止服务。必须运行 `kill.bat` 或手动关闭后台窗口。

**当前行为**（by design）:
- 好处：关闭 launcher 窗口后服务继续运行
- 代价：用户需要知道 `kill.bat` 的存在

**改进方向**: 在 `start.bat` 窗口关闭时触发 cleanup（通过 Windows 事件处理），
但这不是演示阻塞问题。

---

## 6. 前端在 weak 网络下 WS 重连时的短暂闪烁

**状态**: 低优先级 — 偶现

**说明**: 当 WebSocket 断连后，3 秒重连间隔内前端会显示 "Connection Lost"
覆盖层和 "Attempting to reconnect..."。对于短暂断连（<1s），这会造成视觉闪烁。

**影响**: 仅在弱网环境下出现，本地演示不常见。
**改进方向**: 添加重连去抖（debounce），短于 1 秒的断连不显示覆盖层。

---

## 7. 翻译功能（EN/ZH）在非中文语音输入时可能不准确

**状态**: 低优先级 — 设计边界

**说明**: 当前语音识别主要针对中文。后端 TranslationService 会尝试自动检测
源语言，但非中文输入的翻译质量未测试。

**影响**: 仅演示中文语音场景。
**改进方向**: 当检测到非中文时，可以跳过翻译或使用更稳定的翻译方案。

---

## 8. NPM 命令警告（非阻塞）

**状态**: 已知 — 无需解决

**说明**:
- `npm run lint`: 5 个 `react-refresh/only-export-components` 警告
  （文件 `shared.tsx` 导出非组件函数，不影响运行）
- `npm test`: 无警告
- `npm run typecheck`: 无错误
- `npm run build`: 无问题

**影响**: 无

---

## 9. ASR 模型的标点符号可能不符合中文书写规范

**状态**: 已知 — 不阻塞

**说明**: 后端通过 `punctuation.py` 或 ASR 模型自身生成标点。
在测试中发现标点有时位置不标准（如句号前有多余空格）。

**影响**: 演示时字幕标点可能不够美观，但不影响可读性。
**改进方向**: 优化标点后处理或使用更专业的标点恢复模型。
