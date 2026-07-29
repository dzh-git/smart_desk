# SmartDesk 内部演示版便携包

在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File deployment\portable\build-portable.ps1
```

生成物位于被 Git 忽略的 `artifacts/`。包内四个双击入口为
`INSTALL.bat`、`START.bat`、`DOCTOR.bat` 和 `UNINSTALL.bat`。

默认包不含语音、人脸或手势模型。只有使用显式的受控目录参数时，
构建脚本才会把本地模型加入内部包；模型不会进入 Git 或 CI artifact。
这是内部演示版，商业模型许可门禁仍会阻断正式 Release。
