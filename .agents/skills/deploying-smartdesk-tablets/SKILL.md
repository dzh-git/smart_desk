---
name: deploying-smartdesk-tablets
description: Use when configuring, auditing, reprovisioning, or accepting SmartDesk Android tablets for Seat 1 through Seat 9, including APK, HOME, lock screen, permissions, Wi-Fi, and seat-page checks.
---

# Deploying SmartDesk Tablets

## Overview

Use one APK for all nine tablets. Treat Seat 1 as the host and Seat 2–9 as
parameterized participant seats; never clone or fork seat-specific application code.

Read `docs/integration/TABLET_FLEET_DEPLOYMENT.md` before changing a device.

## Modes

| Intent | Command action | Mutation |
|---|---|---|
| Inspect current state | `Audit` | No |
| Preview setup | `Configure` without `-Apply` | No |
| Apply setup | `Configure -Apply` | Yes |
| Produce acceptance report | `Verify` | No |

Run `scripts/manage_android_tablet.ps1 -?` for parameters.

Before `Configure -Apply`, confirm the user authorized changes to the named tablet
and Seat ID. Connect exactly one unlocked tablet unless an explicit `-Serial` is
provided.

The Android contract uses SmartDesk as the default `HOME` application. Do not add
or depend on a `BOOT_COMPLETED` receiver. The script handles standard Android
settings; require a visible manual confirmation for manufacturer auto-start and
background-unrestricted controls.

Never place a maintenance PIN, provisioning password, Wi-Fi password, device
token, or face template in a command, report, Skill file, or Git-tracked inventory.
Complete secret-bearing provisioning in the tablet UI.

## Example

```powershell
.\scripts\manage_android_tablet.ps1 -Action Configure -SeatId 2
.\scripts\manage_android_tablet.ps1 -Action Configure -SeatId 2 -Apply
.\scripts\manage_android_tablet.ps1 -Action Verify -SeatId 2 -ExpectedWifiSsid "SmartDesk"
```

After configuration, verify the report and then commission the matching ESP32
with `scripts/provision_esp32.ps1 -SeatId 2`.

## Common Mistakes

- Seat 2 validates shared participant code, not another tablet's identity or wiring.
- Windows Mobile Hotspot is a debug fallback, not the formal eighteen-client AP.
- `Audit` and `Verify` do not silently repair failures; return to a reviewed
  `Configure` run.
- Do not clear app data during an ordinary APK upgrade; it erases local
  provisioning and persistent host authorization.
