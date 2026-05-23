#!/usr/bin/env python3
"""
服务器状态检查 + 数据同步
"""

import paramiko
import sys

SERVER = "36.213.180.206"
USER = "root"
PASS = "dingyuchenA1@"


def get_ssh():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SERVER, port=22, username=USER, password=PASS, timeout=10)
    return ssh


def check_status():
    """检查服务器抓取状态"""
    ssh = get_ssh()

    print("=" * 50)
    print("  服务器数据抓取状态")
    print("=" * 50)

    # Process
    stdin, stdout, stderr = ssh.exec_command('ps aux | grep fetch_minute | grep -v grep')
    proc = stdout.read().decode().strip()
    if proc:
        print(f"[RUNNING] Fetcher is running")
    else:
        print(f"[IDLE] Fetcher not running")

    # Log
    stdin, stdout, stderr = ssh.exec_command('tail -5 /root/quant_data/fetch.log')
    print(f"\nRecent log:\n{stdout.read().decode()}")

    # DB stats
    cmd = '''python3 -c "
import sqlite3
c = sqlite3.connect('/root/quant_data/market.db')
r = c.execute('SELECT COUNT(DISTINCT code), COUNT(*), MIN(date), MAX(date) FROM minute_kline').fetchone()
print(f'Stocks: {r[0]}, Rows: {r[1]:,}, Range: {r[2]} ~ {r[3]}')
c.close()
"'''
    stdin, stdout, stderr = ssh.exec_command(cmd)
    print(f"Data: {stdout.read().decode().strip()}")

    # Size
    stdin, stdout, stderr = ssh.exec_command('du -sh /root/quant_data/')
    print(f"Disk: {stdout.read().decode().strip()}")

    # State
    stdin, stdout, stderr = ssh.exec_command('cat /root/quant_data/fetch_state.json 2>/dev/null')
    state = stdout.read().decode().strip()
    if state:
        print(f"\nState: {state}")

    ssh.close()


def sync_db():
    """下载数据库到本地"""
    import shutil
    from pathlib import Path

    local_path = Path(__file__).parent.parent / "data" / "db" / "remote_market.db"
    local_path.parent.mkdir(parents=True, exist_ok=True)

    ssh = get_ssh()
    sftp = ssh.open_sftp()

    remote_path = "/root/quant_data/market.db"
    print(f"Downloading {remote_path} -> {local_path}")
    sftp.get(remote_path, str(local_path))
    print(f"Downloaded: {local_path} ({local_path.stat().st_size / 1024 / 1024:.1f}MB)")

    sftp.close()
    ssh.close()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'sync':
        sync_db()
    else:
        check_status()
