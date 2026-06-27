#!/usr/bin/env python3
"""监控 config.json，被修改后自动恢复为指定内容"""
import json
import os
import time
import hashlib

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

TARGET_CONTENT = {
    "APP_KEY": "ZEUyUkKGDB9fmgkjRv0qXIuY5yTrc05X",
    "APP_SECRET": "gLRHKndHxPoVIn6V1WcYb7wpUxAckRLC",
    "API_DOMAIN": "bot.yuanbao.tencent.com",
    "WS_URL": "wss://bot-wss.yuanbao.tencent.com/wss/connection",
    "DEFAULT_GROUP_CODE": "528352302",
    "SPAM_INTERVAL": 1e-44,
    "AUTO_DEFAULT_TEXT": "啊对对对，你说的都对"
}

TARGET_JSON = json.dumps(TARGET_CONTENT, indent=4, ensure_ascii=False) + "\n"
TARGET_HASH = hashlib.sha256(TARGET_JSON.encode()).hexdigest()

def get_current_hash():
    try:
        with open(CONFIG_PATH, "r") as f:
            return hashlib.sha256(f.read().encode()).hexdigest()
    except:
        return ""

def restore():
    try:
        with open(CONFIG_PATH, "w") as f:
            f.write(TARGET_JSON)
        os.chmod(CONFIG_PATH, 0o400)
        print(f"[{time.strftime('%H:%M:%S')}] config.json 已恢复")
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] 恢复失败: {e}")

print(f"config_guard 已启动，监控: {CONFIG_PATH}")
restore()  # 启动时先恢复一次

while True:
    try:
        if get_current_hash() != TARGET_HASH:
            restore()
    except:
        pass
    time.sleep(2)
