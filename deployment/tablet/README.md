# SmartDesk 新平板一键部署包

在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File deployment\tablet\build-tablet-deploy.ps1
```

生成物位于 `artifacts/SmartDesk-Tablet-Deploy-<commit>.zip`。解压后只需连接并
授权一台平板，再双击 `DEPLOY_TABLET.bat`。包内自带审核 APK 和 Android ADB
运行文件；只预填非敏感 Seat ID 与中央主机，所有口令仍在平板本地输入。
