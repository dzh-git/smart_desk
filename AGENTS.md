# 项目协作约定

- 所有源码和文档使用 UTF-8；PowerShell 读取文本时显式指定 `-Encoding UTF8`。
- 三个核心模块保持独立：会议业务、手势控制、Arduino 固件不得相互复制实现。
- Display Agent 是 Windows 应用切换的唯一实现；手势模块只调用其 loopback HTTP API。
- `docs/archive/` 仅保存历史资料，不得作为当前接口、配置或验收依据。
- 代码库问题优先执行 `graphify query`；代码和当前规范变化后执行 `scripts\\graphify_update_single.bat`（只维护根级单一快照，不创建日期备份）。
- 修改范围保持最小，新增行为必须有可复现测试，避免顺手重构无关代码。
