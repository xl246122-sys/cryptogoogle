# Crypto-G Project Rules & Instructions for AI Coding Assistants

## APK Delivery Rule
- **Target Output Directory**: `D:\Crypto-Google\release`
- **File Naming Pattern**: `Crypto-G V{versionName}.apk` (e.g. `Crypto-G V1.03.apk`)
- **Version Increment**: Increment `versionName` by `+0.01` and `versionCode` by `+1` on each release in `android/app/build.gradle`.
- **Automated Copy**: Gradle `assembleDebug` automatically executes `copyApkToRelease` to place the compiled APK directly into `D:\Crypto-Google\release`.

## Quantitative Engine Rules
- **Asset**: Focused exclusively on `BTCUSDT`.
- **Signals**: BUY signals only.
- **Micro-Range Bounces**: Enforce 5-barrier anti-knife reversal gates before issuing `RANGE_MICRO` or `RANGE_MEDIUM`.
- **Friction Gate**: Require Net TP1 $\ge 0.40\%$ and Net Risk-Reward $\ge 1.10:1$ after deducting 0.11% friction.
- **Server Sync**: Remote daemon at `43.163.203.127:/opt/shotcrypto/scanner_daemon.py` (`shotcrypto.service`).
