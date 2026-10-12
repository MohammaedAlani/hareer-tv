# Optional kiosk setup

Hareer TV's normal Back/Exit flow requires a star-counting puzzle. Blocking Home and Recents additionally requires Android lock-task mode, a supported device, and a device policy controller. The app includes a minimal device-admin receiver for dedicated-device testing.

## Dedicated test device

Install the app first. On a device that allows device-owner provisioning:

```sh
adb shell dpm set-device-owner family.blossom.tv/.KioskAdmin
adb shell am start -n family.blossom.tv/.MainActivity
```

This changes persistent device management state. Use a disposable emulator or a device intended for this purpose. Existing accounts, prior setup, or manufacturer restrictions may prevent provisioning. Do not reset a household TV just to try it. A separate device-management provider can instead allowlist `family.blossom.tv` for lock-task mode.

At launch, Hareer TV allowlists itself if it is the device owner and starts lock-task mode only when allowed. A correct puzzle answer ends lock-task mode and closes the app. It does **not** remove the device-owner registration. If kiosk configuration cannot be used, a message explains that Home may still leave the app.

## Verify and recover

1. Confirm that Home and Recents stay inside the app.
2. Confirm that a wrong puzzle answer keeps it open.
3. Confirm that Back from the puzzle returns to the library.
4. Confirm that a correct answer ends lock-task and closes the app.
5. Reopen the app and verify kiosk mode starts again.

Keep your device-management recovery access available while testing. Solving the puzzle is the app's normal exit route. For deprovisioning, follow your management provider's or device manufacturer's documented procedure; uninstalling a device-owner app may be restricted. A disposable emulator can be deleted after use.

A simple puzzle cannot prevent a child who knows the answer from exiting. Lock-task also does not guarantee protection against power-off, administrator actions, or every vendor remote shortcut. Test the physical TV before relying on it.

Reference: [Android lock-task mode documentation](https://developer.android.com/work/dpc/dedicated-devices/lock-task-mode).
