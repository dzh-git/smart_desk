# SmartDesk 演示界面截图

两组截图均以 Chromium 打开实际页面采集。改造前采用基线提交 `5bc824b`，改造后采用本分支。两组使用同名样例会议，改造后的演示种子额外预置当前议题、席位分配和三张样例选票。

| 页面 | 视口 | 改造前 | 改造后 |
| --- | --- | --- | --- |
| 电脑主持人 `/admin` | 1600 × 1000 | [原始截图](before/admin.png) | [主持人控制台](after/admin.png) |
| Seat 1 主持人平板 `/host` | 1280 × 800 | [浏览器设备提示](before/host.png) | [浏览器演示预览](after/host.png) |
| 参会平板 `/seat/2` | 1280 × 800 | [原始截图](before/seat.png) | [参会平板](after/seat.png) |
| 中央大屏 `/display` | 1920 × 1080 | [原始截图](before/display.png) | [议程与投票大屏](after/display.png) |
| 主机画面 `/screen` | 1600 × 900 | [原始截图](before/screen.png) | [等待主机共享](after/screen.png) |

`/host` 截图展示无 Android 设备的浏览器演示入口。`/screen` 截图展示中央主机尚未共享时的状态。

[演示启动与复现步骤](../../../new_coding_desk/docs/DEMO_RUNBOOK.md)
