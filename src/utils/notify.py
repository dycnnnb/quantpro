"""
通知推送
"""

import json
import requests
from pathlib import Path

_SETTINGS_FILE = Path(__file__).resolve().parents[2] / "config" / "notify_settings.json"


def _load_settings():
    try:
        if _SETTINGS_FILE.exists():
            with open(_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_settings(settings: dict):
    try:
        _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[NOTIFY] 保存设置失败: {e}")
        return False


def send_wechat_notification(message: str, webhook_url: str = ""):
    if not webhook_url:
        s = _load_settings()
        webhook_url = s.get('wechat_webhook', '')
    if not webhook_url:
        print(f"[NOTIFY-WECHAT] 无webhook地址: {message}")
        return False
    try:
        resp = requests.post(
            webhook_url,
            json={"msgtype": "text", "text": {"content": message}},
            timeout=10,
        )
        ok = resp.status_code == 200
        if not ok:
            print(f"[NOTIFY-WECHAT] 发送失败 HTTP {resp.status_code}")
        return ok
    except Exception as e:
        print(f"[NOTIFY-WECHAT] 发送异常: {e}")
        return False


def send_feishu_notification(message: str, webhook_url: str = ""):
    if not webhook_url:
        s = _load_settings()
        webhook_url = s.get('feishu_webhook', '')
    if not webhook_url:
        print(f"[NOTIFY-FEISHU] 无webhook地址: {message}")
        return False
    try:
        resp = requests.post(
            webhook_url,
            json={"msg_type": "text", "content": {"text": message}},
            timeout=10,
        )
        ok = resp.status_code == 200
        if not ok:
            print(f"[NOTIFY-FEISHU] 发送失败 HTTP {resp.status_code}")
        return ok
    except Exception as e:
        print(f"[NOTIFY-FEISHU] 发送异常: {e}")
        return False


def send_email_notification(message: str, email_address: str = ""):
    print(f"[NOTIFY-EMAIL] {message} -> {email_address or '(未配置)'}")
    return False


def send_notification(message: str, event_type: str = ""):
    s = _load_settings()
    results = []

    event_map = {
        'signal': 'notify_signal',
        'risk': 'notify_risk',
        'daily': 'notify_daily',
        'backtest': 'notify_backtest',
    }
    event_key = event_map.get(event_type, '')
    if event_key and s.get(event_key) == '0':
        return results

    if s.get('notify_wechat') == '1':
        ok = send_wechat_notification(message, s.get('wechat_webhook', ''))
        results.append(('wechat', ok))

    if s.get('notify_feishu') == '1':
        ok = send_feishu_notification(message, s.get('feishu_webhook', ''))
        results.append(('feishu', ok))

    if s.get('notify_email') == '1':
        ok = send_email_notification(message, s.get('email_address', ''))
        results.append(('email', ok))

    return results
