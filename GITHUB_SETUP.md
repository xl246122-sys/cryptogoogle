# 源码交接与配置恢复

本仓库为 2026-10-15 V1.21 的干净源码快照，不包含原本地 Git 历史，避免传播历史中的私钥。原工作区保持原样。

先阅读 `交接总结文件.md` 和 `AGENTS.md`。生产 Python 源码位于 `scratch/cryptog` 与 `scratch/remote_scanner_daemon.py`，不是可删除的临时文件。

## 安装与验证

使用 Node.js 与 npm：`npm ci`、`npm run lint`、`npm run build`。后端依赖见 `scratch/requirements.txt`。测试入口和覆盖限制见交接总结。

## 私有配置

以下文件必须由所有者通过安全渠道恢复，禁止提交：
- Firebase Android 配置 `android/app/google-services.json`（需要时根目录也放置同一配置）。
- Firebase 服务账户私钥、服务器环境文件与设备访问凭据。
- Android SDK 的 `android/local.properties`、签名密钥及签名环境变量。
- 运维使用的 `.ssh_known_hosts`，需从可信渠道验证主机指纹后创建。

服务器密码通过 `CRYPTO_G_SSH_PASS` 环境变量提供，不写入源码。部署前阅读具体脚本；部分历史脚本有固定版本和哈希，不能直接重复运行。

本仓库未附 APK、原始运行账本、私有配置、依赖缓存及审计截图；保留应用与后端源码、测试夹具、运维脚本和文字交付文档。没有这些私有配置时不能直接完成 Android Firebase 构建或生产部署。

原本地历史中存在服务账户私钥。应在确认新密钥部署后撤销旧密钥，防止历史副本泄露；本次未擅自轮换生产凭据。
