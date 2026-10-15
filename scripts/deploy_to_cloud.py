#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crypto-G V1.04 Production Deployment Script
Deploys updated quantitative scanner daemon to Tokyo Cloud Node (43.163.203.127)
"""

import sys
import os
import time
import paramiko

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

LOCAL_DAEMON_FILE = os.path.join(os.path.dirname(__file__), "..", "scratch", "remote_scanner_daemon.py")
REMOTE_HOST = "43.163.203.127"
REMOTE_USER = "ubuntu"
REMOTE_PASS = os.environ.get("CRYPTO_G_SSH_PASS", "")
REMOTE_TARGET_PATH = "/opt/shotcrypto/scanner_daemon.py"
REMOTE_SERVICE_NAME = "shotcrypto.service"


def main():
    print("=" * 65)
    print(">>> Crypto-G V1.04 Tokyo Cloud Deployment Starting <<<")
    print("=" * 65)

    if not REMOTE_PASS:
        print("Set CRYPTO_G_SSH_PASS in the environment. The password is not stored in this script.")
        sys.exit(1)

    if not os.path.exists(LOCAL_DAEMON_FILE):
        print(f"Error: Local file {LOCAL_DAEMON_FILE} not found!")
        sys.exit(1)

    with open(LOCAL_DAEMON_FILE, "r", encoding="utf-8", newline="") as f:
        local_content = f.read().replace("\r\n", "\n").replace("\r", "\n")

    print(f"Local V1.04 daemon file loaded ({len(local_content)} chars, {len(local_content.splitlines())} lines).")

    print(f"Connecting to {REMOTE_USER}@{REMOTE_HOST}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(REMOTE_HOST, username=REMOTE_USER, password=REMOTE_PASS, timeout=10.0)
    print("Connected successfully!")

    # Step 1: Backup current production daemon
    print("Step 1: Creating backup of current production daemon...")
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_cmd = f"sudo cp {REMOTE_TARGET_PATH} {REMOTE_TARGET_PATH}.bak_{timestamp}"
    _, stdout, stderr = client.exec_command(f"echo '{REMOTE_PASS}' | sudo -S {backup_cmd}")
    stdout.read()
    print(f"Backup created: {REMOTE_TARGET_PATH}.bak_{timestamp}")

    # Step 2: Upload new version to /tmp/scanner_daemon.py
    print("Step 2: Uploading V1.04 daemon via SFTP...")
    sftp = client.open_sftp()
    tmp_remote_path = "/tmp/scanner_daemon_v104.py"
    with sftp.file(tmp_remote_path, "w") as rf:
        rf.write(local_content)
    sftp.close()
    print(f"Uploaded to {tmp_remote_path} successfully.")

    # Step 3: Copy to target directory and set permissions
    print("Step 3: Installing V1.04 daemon to /opt/shotcrypto/...")
    install_cmd = f"echo '{REMOTE_PASS}' | sudo -S cp {tmp_remote_path} {REMOTE_TARGET_PATH} && sudo chmod 755 {REMOTE_TARGET_PATH}"
    _, stdout, stderr = client.exec_command(install_cmd)
    stdout.read()

    # Step 4: Verify Python syntax on server
    print("Step 4: Compiling Python code on remote server...")
    check_cmd = f"/opt/shotcrypto/venv/bin/python3 -m py_compile {REMOTE_TARGET_PATH}"
    _, stdout, stderr = client.exec_command(check_cmd)
    err = stderr.read().decode('utf-8')
    if err:
        print(f"Remote compilation error:\n{err}")
        client.close()
        sys.exit(1)
    print("Remote compilation passed with 0 errors!")

    # Step 5: Restart Systemd service
    print(f"Step 5: Restarting {REMOTE_SERVICE_NAME}...")
    restart_cmd = f"echo '{REMOTE_PASS}' | sudo -S systemctl restart {REMOTE_SERVICE_NAME}"
    _, stdout, stderr = client.exec_command(restart_cmd)
    stdout.read()
    time.sleep(3.0)

    # Step 6: Verify service status
    print("Step 6: Checking service status...")
    status_cmd = f"systemctl status {REMOTE_SERVICE_NAME} --no-pager"
    _, stdout, stderr = client.exec_command(status_cmd)
    status_out = stdout.read().decode('utf-8')
    print("\n--- Systemd Service Status ---")
    print("\n".join(status_out.splitlines()[:20]))

    # Step 7: Check scanner logs
    print("\nStep 7: Inspecting latest scanner daemon log...")
    log_cmd = "tail -n 20 /opt/shotcrypto/logs/scanner.log"
    _, stdout, stderr = client.exec_command(log_cmd)
    log_out = stdout.read().decode('utf-8')
    print("\n--- Latest /opt/shotcrypto/logs/scanner.log ---")
    print(log_out)

    client.close()
    print("\n" + "=" * 65)
    print(">>> Deployment to Tokyo Cloud Node Successfully Completed! <<<")
    print("=" * 65)


if __name__ == "__main__":
    main()
