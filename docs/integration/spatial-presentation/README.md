# SmartDesk 空间界面截图

改造前为 `058a8c0` 交付的演示界面。改造后由 Chromium 打开本分支的演示构建，在相同尺寸的视口采集。两版使用同名样例会议。新版截图使用 SwiftShader、手动高画质与减少动效，保留实时渲染的静止画面。

| 页面 | 视口 | 改造前 | 改造后 |
| --- | --- | --- | --- |
| `/admin` 电脑主持人 | 1600 × 1000 | [控制台](../presentation/after/admin.png) | [九席总览](admin.webp) · [议程与投票](agenda.webp) · [服务与记录](service.webp) |
| `/host` 主持人平板 | 1280 × 800 | [演示预览](../presentation/after/host.png) | [三维主持席](host.webp) |
| `/seat/2` 参会平板 | 1280 × 800 | [参会席](../presentation/after/seat.png) | [三维参会席](seat.webp) |
| `/display` 中央大屏 | 1920 × 1080 | [会议投票](../presentation/after/display.png) | [三维会议核心与投票](display.webp) |
| `/screen` 共享等待页 | 1600 × 900 | [等待共享](../presentation/after/screen.png) | [共享信号透镜](screen.webp) |

[参会页面窄屏检查（390 × 844）](seat-mobile.webp)

`/host` 显示无 Android 设备的演示入口。`/screen` 显示等待中央主机共享的状态。截图中的样例会议由演示库提供。启动方法、渲染设置及测试命令见 [空间界面](../../../new_coding_desk/docs/SPATIAL_UI.md)。
