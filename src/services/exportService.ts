/**
 * The daemon text is the same file the server runs. It is not a second copy.
 */
const daemonSource = '# 服务端已模块化。请使用仓库完整部署包，不能只复制单个脚本。';

export const PYTHON_DAEMON_SCRIPT = daemonSource;

export const SYSTEMD_SERVICE_FILE = `[Unit]
Description=Crypto-G BTC monitor
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/shotcrypto
EnvironmentFile=/etc/shotcrypto/production.env
ExecStart=/opt/shotcrypto/venv-v113/bin/python /opt/shotcrypto/scanner_daemon.py
UMask=0077
Restart=always
RestartSec=3
StandardOutput=append:/opt/shotcrypto/logs/scanner.log
StandardError=append:/opt/shotcrypto/logs/scanner.log

[Install]
WantedBy=multi-user.target
`;

export const UBUNTU_DEPLOY_GUIDE = `# Crypto-G 云端守护进程

程序目录：/opt/shotcrypto
服务：shotcrypto.service
脚本：/opt/shotcrypto/scanner_daemon.py
正式买入候选只扫描 BTCUSDT。

部署必须包含 scratch/cryptog、requirements.txt 和入口脚本；配置 TLS 与独立设备凭据。参阅阶段一交付文档。
服务器口令放在环境变量 CRYPTO_G_SSH_PASS 中，不要写进仓库。
不要把 Firebase 私钥贴进日志或对话。

更新后需要在服务器上重启 shotcrypto.service，本仓库里的修改不会自动生效。
`;
