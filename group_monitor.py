#!/usr/bin/env python3
"""
group_monitor.py — 元宝群消息监听器
监听配置文件中的 DEFAULT_GROUP_CODE 群消息，入库 SQLite，支持撤回检测通知
"""

import asyncio
import json
import os
import sys
import hashlib
import hmac
import base64
import random
import string
import sqlite3
import logging
import uuid
import struct
from datetime import datetime, timedelta, timezone

import websockets
import requests

# ─── 配置 ─────────────────────────────────────────────
CONFIG_PATH = os.path.expanduser("~/yuanbao_bot_client/config.json")
DB_PATH = os.path.expanduser("~/yuanbao_bot_client/group_messages.db")

def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)

_config = load_config()
APP_KEY = _config["APP_KEY"]
APP_SECRET = _config["APP_SECRET"]
API_DOMAIN = _config.get("API_DOMAIN", "bot.yuanbao.tencent.com")
WS_URL = _config.get("WS_URL", "wss://bot-wss.yuanbao.tencent.com/wss/connection")
DEFAULT_GROUP_CODE = _config.get("DEFAULT_GROUP_CODE", "")

# ─── 协议常量 ──────────────────────────────────────────
CMD_TYPE_REQUEST = 0
CMD_TYPE_RESPONSE = 1
CMD_TYPE_PUSH = 2
CMD_PING = "ping"
CMD_AUTH_BIND = "auth-bind"
MODULE_CONN_ACCESS = "conn_access"
BIZ_MODULE = "yuanbao_openclaw_proxy"
BIZ_CMD_SEND_GROUP = "send_group_message"
BIZ_CMD_SYNC_INFORMATION = "sync_information"
HEARTBEAT_INTERVAL = 70
MAX_RECONNECT_ATTEMPTS = 10

# ─── 日志 ─────────────────────────────────────────────
LOG_FILE = os.path.expanduser("~/yuanbao_bot_client/group_monitor.log")
logger = logging.getLogger("group_monitor")
logger.setLevel(logging.DEBUG)
_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_fh)

# ─── Protobuf 编解码 ──────────────────────────────────

def pb_varint(value):
    """编码 varint"""
    if value < 0:
        value = (1 << 64) + value
    result = []
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)

def pb_tag(field, wire):
    return pb_varint((field << 3) | wire)

def pb_string(field, value):
    data = value.encode("utf-8")
    return pb_tag(field, 2) + pb_varint(len(data)) + data

def pb_bytes(field, value):
    return pb_tag(field, 2) + pb_varint(len(value)) + value

def pb_int32(field, value):
    return pb_tag(field, 0) + pb_varint(value)

def pb_uint32(field, value):
    return pb_tag(field, 0) + pb_varint(value)

def pb_msg(field, inner):
    return pb_tag(field, 2) + pb_varint(len(inner)) + inner

def pb_decode_varint(data, off=0):
    result = 0
    shift = 0
    while off < len(data):
        b = data[off]
        result |= (b & 0x7F) << shift
        off += 1
        if not (b & 0x80):
            break
        shift += 7
    return result, off

def pb_decode_delimited(data, off=0):
    length, off = pb_decode_varint(data, off)
    return data[off:off + length], off + length

def pb_decode_msg(data):
    result = {}
    off = 0
    while off < len(data):
        tag, off = pb_decode_varint(data, off)
        field = tag >> 3
        wire = tag & 7
        if wire == 0:
            val, off = pb_decode_varint(data, off)
            result[field] = (0, val)
        elif wire == 2:
            val, off = pb_decode_delimited(data, off)
            result[field] = (2, val)
        elif wire == 5:
            val = struct.unpack_from("<I", data, off)[0]
            off += 4
            result[field] = (5, val)
        elif wire == 1:
            val = struct.unpack_from("<Q", data, off)[0]
            off += 8
            result[field] = (1, val)
        else:
            break
    return result

def encode_conn_head(cmd_type, cmd, seq_no, msg_id, module):
    head = b""
    head += pb_int32(1, cmd_type)
    head += pb_string(2, cmd)
    head += pb_int32(3, seq_no)
    head += pb_string(4, msg_id)
    head += pb_string(5, module)
    return head

def encode_conn_msg(cmd_type, cmd, seq_no, msg_id, module, data=b""):
    frame = pb_msg(1, encode_conn_head(cmd_type, cmd, seq_no, msg_id, module))
    if data:
        frame += pb_bytes(2, data)
    return frame

def decode_conn_msg(data):
    msg = pb_decode_msg(data)
    result = {}
    if 1 in msg:
        head = pb_decode_msg(msg[1][1])
        for fid, key in [(1, "cmd_type"), (2, "cmd"), (3, "seq_no"),
                         (4, "msg_id"), (5, "module")]:
            if fid in head:
                val = head[fid][1]
                result[key] = val.decode("utf-8", errors="replace") if isinstance(val, bytes) else val
    if 2 in msg:
        result["data"] = msg[2][1]
    return result

def encode_auth_bind(biz_id, uid, source, token):
    auth_info = pb_string(1, uid) + pb_string(2, source) + pb_string(3, token)
    device_info = (
        pb_string(1, "2.0.1") +
        pb_string(2, "Linux") +
        pb_string(3, "2026.3.23-2") +
        pb_int32(4, 16)
    )
    return pb_string(1, biz_id) + pb_msg(2, auth_info) + pb_msg(3, device_info)

def encode_send_group_req(group_code, text, msg_id="", from_account="", random_val=None):
    if random_val is None:
        random_val = str(random.randint(0, 2**32 - 1))
    body_elem = pb_string(1, "TIMTextElem") + pb_msg(2, pb_string(1, text))
    req = b""
    req += pb_string(1, msg_id)
    req += pb_string(2, group_code)
    req += pb_string(3, from_account)
    req += pb_string(5, random_val)
    req += pb_msg(6, body_elem)
    return req


def encode_tim_image_elem(url: str, uuid: str = "", size: int = 0,
                          width: int = 0, height: int = 0,
                          image_format: int = 255) -> bytes:
    """编码 TIMImageElem 图片消息元素"""
    img_info = (
        pb_uint32(1, 1) +
        pb_uint32(2, size) +
        pb_uint32(3, width) +
        pb_uint32(4, height) +
        pb_string(5, url)
    )
    mc = b""
    if uuid:
        mc += pb_string(2, uuid)
    mc += pb_uint32(3, image_format)
    mc += pb_msg(8, img_info)
    return pb_string(1, "TIMImageElem") + pb_msg(2, mc)


def encode_tim_file_elem(url: str, uuid: str = "", file_size: int = 0,
                         file_name: str = "") -> bytes:
    """编码 TIMFileElem 文件消息元素"""
    mc = b""
    if uuid:
        mc += pb_string(2, uuid)
    mc += pb_string(10, url)
    if file_size:
        mc += pb_uint32(11, file_size)
    if file_name:
        mc += pb_string(12, file_name)
    return pb_string(1, "TIMFileElem") + pb_msg(2, mc)


def encode_tim_face_elem(sticker_id: str, package_id: str, name: str,
                         width: int = 128, height: int = 128,
                         formats: str = "png") -> bytes:
    """编码 TIMFaceElem 贴纸消息元素"""
    import json
    data_json = json.dumps({
        "sticker_id": sticker_id,
        "package_id": package_id,
        "width": width,
        "height": height,
        "formats": formats,
        "name": name,
    }, ensure_ascii=False)
    msg_content = pb_uint32(9, 0) + pb_string(4, data_json)
    return pb_string(1, "TIMFaceElem") + pb_msg(2, msg_content)


# ─── SQLite 消息存储 ──────────────────────────────────

class MessageStore:
    """SQLite 消息数据库"""

    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_id      TEXT,
                msg_seq     INTEGER,
                content     TEXT,
                sender_name TEXT,
                sender_id   TEXT,
                group_code  TEXT,
                time        TEXT,
                media_info  TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_msg_id ON messages(msg_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_msg_seq ON messages(msg_seq)")
        self.conn.commit()

    def get_next_id(self):
        """获取下一条消息的编号（基于最后一条的 id + 1）"""
        cur = self.conn.execute("SELECT MAX(id) FROM messages")
        row = cur.fetchone()
        return (row[0] or 0) + 1

    def add_message(self, msg_id, msg_seq, content, sender_name, sender_id,
                    group_code, time_str, media_info=None):
        self.conn.execute(
            "INSERT INTO messages (msg_id, msg_seq, content, sender_name, "
            "sender_id, group_code, time, media_info) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (msg_id, msg_seq, content, sender_name, sender_id,
             group_code, time_str,
             json.dumps(media_info, ensure_ascii=False) if media_info else None)
        )
        self.conn.commit()

    def find_by_msg_id(self, msg_id):
        cur = self.conn.execute("SELECT * FROM messages WHERE msg_id = ?", (msg_id,))
        return cur.fetchone()

    def find_by_msg_seq(self, msg_seq):
        cur = self.conn.execute("SELECT * FROM messages WHERE msg_seq = ?", (msg_seq,))
        return cur.fetchone()

    def close(self):
        self.conn.close()


# ─── 时间工具 ─────────────────────────────────────────

def _get_beijing_time():
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%S+08:00")

def _fmt_time():
    return datetime.now().strftime("%H:%M:%S")


# ─── 核心客户端 ────────────────────────────────────────

class MonitorClient:

    def __init__(self, store: MessageStore):
        self.store = store
        self.token = None
        self.bot_id = None
        self.ws = None
        self.connected = False
        self.seq_no = 1
        self.running = True
        self._reconnecting = False
        self.instance_id = str(random.randint(1, 1000))

    def _next_seq(self):
        self.seq_no += 1
        return self.seq_no

    # ── 签名 ──────────────────────────────────────────

    def sign_token(self) -> bool:
        url = f"https://{API_DOMAIN}/api/v5/robotLogic/sign-token"
        nonce = "".join(random.choices(string.hexdigits.lower(), k=32))
        timestamp = _get_beijing_time()
        plain = f"{nonce}{timestamp}{APP_KEY}{APP_SECRET}"
        signature = hmac.new(APP_SECRET.encode(), plain.encode(), hashlib.sha256).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-AppVersion": "1.0.11",
            "X-OperationSystem": "linux",
            "X-Instance-Id": self.instance_id,
            "X-Bot-Version": "2026.3.22",
        }
        body = {"app_key": APP_KEY, "nonce": nonce, "signature": signature, "timestamp": timestamp}
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=30)
            result = resp.json()
            if result.get("code") == 0:
                data = result["data"]
                self.token = data["token"]
                self.bot_id = data["bot_id"]
                logger.info(f"sign_token 成功, Bot ID: {self.bot_id}")
                print(f"签票成功! Bot ID: {self.bot_id}")
                return True
            logger.error(f"sign_token 失败: {result}")
        except Exception as e:
            logger.error(f"sign_token 异常: {e}")
        return False

    # ── 构建鉴权消息 ──────────────────────────────────

    def _build_auth_bind_msg(self) -> bytes:
        biz_id = "ybBot"
        uid = self.bot_id or ""
        source = "web"
        token = self.token or ""
        inner = encode_auth_bind(biz_id, uid, source, token)
        frame = encode_conn_msg(
            cmd_type=CMD_TYPE_REQUEST, cmd=CMD_AUTH_BIND,
            seq_no=self.seq_no, msg_id=uuid.uuid4().hex,
            module=MODULE_CONN_ACCESS, data=inner,
        )
        self.seq_no += 1
        return frame

    def _build_sync_information_req(self) -> bytes:
        """构建命令同步请求（同步命令列表和版本信息）"""
        data = b""
        # field 1: syncType = 1 (SYNC_INFORMATION_TYPE_COMMANDS)
        data += bytes([(1 << 3) | 0]) + pb_varint(1)
        # field 2: botVersion
        data += pb_string(2, "1.1.0")
        # field 3: pluginVersion
        data += pb_string(3, "1.0.0")
        # field 11: commandData (SyncCommandsData, 只同步 /help)
        sync_cmds = pb_string(1, "/help") + pb_string(2, "显示帮助信息")
        data += pb_msg(11, sync_cmds)

        frame = encode_conn_msg(
            cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_SYNC_INFORMATION,
            seq_no=self.seq_no, msg_id=uuid.uuid4().hex,
            module=BIZ_MODULE, data=data,
        )
        self.seq_no += 1
        return frame

    # ── 连接 ──────────────────────────────────────────

    async def connect(self) -> bool:
        if not self.token and not self.sign_token():
            return False
        try:
            self.ws = await websockets.connect(WS_URL)
            auth_msg = self._build_auth_bind_msg()
            await self.ws.send(auth_msg)
            resp = await asyncio.wait_for(self.ws.recv(), timeout=10)
            # sender.py 不检查 auth-bind 响应，收到就算成功
            self.connected = True
            print(f"[{_fmt_time()}] ✅ 已连接到元宝网关")
            # 发送同步信息（fire-and-forget）
            try:
                sync_msg = self._build_sync_information_req()
                await self.ws.send(sync_msg)
            except Exception:
                pass
            # 启动心跳
            asyncio.create_task(self._heartbeat())
            return True
        except asyncio.TimeoutError:
            print(f"[{_fmt_time()}] ❌ 连接超时")
        except Exception as e:
            print(f"[{_fmt_time()}] ❌ 连接异常: {e}")
        return False

    # ── 心跳 ──────────────────────────────────────────

    async def _heartbeat(self):
        while self.connected and self.running:
            try:
                self.seq_no += 1
                ping_msg = encode_conn_msg(
                    cmd_type=CMD_TYPE_REQUEST, cmd=CMD_PING,
                    seq_no=self.seq_no, msg_id=uuid.uuid4().hex,
                    module=MODULE_CONN_ACCESS,
                )
                await self.ws.send(ping_msg)
                await asyncio.sleep(HEARTBEAT_INTERVAL)
            except Exception:
                break

    # ── 从 msg_body 提取文本 ─────────────────────────

    def _extract_text(self, msg_body) -> str:
        """从 msg_body（JSON 格式）提取文本内容"""
        if not isinstance(msg_body, list):
            return ""
        parts = []
        for elem in msg_body:
            elem_type = elem.get("msg_type", "")
            mc = elem.get("msg_content", {})
            if not isinstance(mc, dict):
                mc = {}
            if elem_type == "TIMTextElem":
                parts.append(mc.get("text", ""))
            elif elem_type == "TIMCustomElem":
                data_str = mc.get("data", "")
                if isinstance(data_str, str) and data_str:
                    try:
                        cd = json.loads(data_str)
                        if isinstance(cd, dict):
                            if cd.get("elem_type") == 1002:
                                parts.append(cd.get("text", ""))
                            else:
                                parts.append(cd.get("text", cd.get("content", cd.get("tips", ""))))
                    except (json.JSONDecodeError, TypeError):
                        parts.append(data_str)
            elif elem_type == "TIMFaceElem":
                data_str = mc.get("data", "")
                name = ""
                if isinstance(data_str, str) and data_str:
                    try:
                        fd = json.loads(data_str)
                        name = fd.get("name", "")
                    except (json.JSONDecodeError, TypeError):
                        pass
                if not name:
                    name = mc.get("name", "")
                parts.append(f"[贴纸: {name}]" if name else "[贴纸]")
            elif elem_type == "TIMImageElem":
                parts.append("📷 [图片]")
            elif elem_type == "TIMFileElem":
                fname = mc.get("file_name", "")
                parts.append(f"📎 [文件: {fname}]" if fname else "📎 [文件]")
            elif elem_type == "TIMVideoFileElem":
                vname = mc.get("file_name", "")
                parts.append(f"🎬 [视频: {vname}]" if vname else "🎬 [视频]")
        return " ".join(p for p in parts if p).strip()

    # ── 从 msg_body 提取媒体信息 ─────────────────────

    def _extract_media_info(self, msg_body) -> dict:
        """从 msg_body 提取图片/文件/贴纸等媒体信息，返回 media_info dict"""
        if not isinstance(msg_body, list):
            return {}
        media_info = {}
        for elem in msg_body:
            msg_type = elem.get("msg_type", "")
            mc = elem.get("msg_content", {})
            if not isinstance(mc, dict):
                mc = {}
            if msg_type == "TIMImageElem":
                img_array = mc.get("image_info_array", [])
                img_urls = []
                last_info = {}
                for img_info in img_array:
                    if isinstance(img_info, dict) and img_info.get("url"):
                        last_info = img_info
                        img_urls.append(last_info["url"])
                media_info["type"] = "image"
                media_info["image_urls"] = img_urls
                media_info["image_uuid"] = mc.get("uuid", "")
                media_info["image_width"] = last_info.get("width", 0)
                media_info["image_height"] = last_info.get("height", 0)
                media_info["image_size"] = last_info.get("size", 0)
            elif msg_type == "TIMFileElem":
                file_url = mc.get("url", "")
                file_name = mc.get("file_name", "")
                file_uuid = mc.get("uuid", "")
                file_size = mc.get("file_size", 0)
                media_info["type"] = "file"
                media_info["file_url"] = file_url
                media_info["file_name"] = file_name
                media_info["file_uuid"] = file_uuid
                media_info["file_size"] = file_size
            elif msg_type == "TIMVideoFileElem":
                media_info["type"] = "video"
                media_info["url"] = mc.get("url", "")
                media_info["uuid"] = mc.get("uuid", "")
                media_info["size"] = mc.get("file_size", 0)
                media_info["name"] = mc.get("file_name", "")
            elif msg_type == "TIMFaceElem":
                data_str = mc.get("data", "")
                if isinstance(data_str, str) and data_str:
                    try:
                        fd = json.loads(data_str)
                        media_info["type"] = "sticker"
                        media_info["sticker_id"] = fd.get("sticker_id", "")
                        media_info["sticker_name"] = fd.get("name", "")
                        media_info["package_id"] = fd.get("package_id", "")
                    except (json.JSONDecodeError, TypeError):
                        pass
        return media_info

    # ── 构建发送消息请求 ─────────────────────────────

    async def send_group_message(self, group_code: str, text: str) -> bool:
        if not self.connected or not self.ws:
            print(f"[{_fmt_time()}] ⚠️ 发送失败：未连接")
            return False
        try:
            self.seq_no += 1
            req_data = encode_send_group_req(
                group_code, text,
                msg_id=str(self.seq_no),
                from_account=self.bot_id or "",
            )
            msg_id = uuid.uuid4().hex
            frame = encode_conn_msg(
                cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_SEND_GROUP,
                seq_no=self.seq_no, msg_id=msg_id,
                module=BIZ_MODULE, data=req_data,
            )
            await self.ws.send(frame)
            return True
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            print(f"[{_fmt_time()}] ❌ 发送消息异常: {e}")
            return False

    # ── 发送图片消息 ───────────────────────────────

    async def send_group_image_message(self, group_code: str, url: str,
                                        media_uuid: str = "", size: int = 0,
                                        width: int = 0, height: int = 0) -> bool:
        if not self.connected or not self.ws:
            print(f"[{_fmt_time()}] ⚠️ 图片发送失败：未连接")
            return False
        try:
            self.seq_no += 1
            image_elem = encode_tim_image_elem(url, media_uuid, size, width, height)
            req = b""
            req += pb_string(1, str(self.seq_no))     # msg_id
            req += pb_string(2, group_code)           # group_code
            req += pb_string(3, self.bot_id or "")    # from_account
            req += pb_string(4, "")                   # to_account（空）
            req += pb_string(5, str(random.randint(0, 2**32 - 1)))  # random
            req += pb_msg(6, image_elem)              # msgBody
            req += pb_string(7, "")                   # refMsgId（空）
            msg_id = uuid.uuid4().hex
            frame = encode_conn_msg(
                cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_SEND_GROUP,
                seq_no=self.seq_no, msg_id=msg_id,
                module=BIZ_MODULE, data=req,
            )
            await self.ws.send(frame)
            return True
        except Exception as e:
            logger.error(f"发送图片消息失败: {e}")
            print(f"[{_fmt_time()}] ❌ 发送图片消息异常: {e}")
            return False

    # ── 发送文件消息 ───────────────────────────────

    async def send_group_file_message(self, group_code: str, url: str,
                                       file_name: str = "",
                                       media_uuid: str = "", file_size: int = 0) -> bool:
        if not self.connected or not self.ws:
            print(f"[{_fmt_time()}] ⚠️ 文件发送失败：未连接")
            return False
        try:
            self.seq_no += 1
            file_elem = encode_tim_file_elem(url, media_uuid, file_size, file_name)
            req = b""
            req += pb_string(1, str(self.seq_no))     # msg_id
            req += pb_string(2, group_code)           # group_code
            req += pb_string(3, self.bot_id or "")    # from_account
            req += pb_string(4, "")                   # to_account（空）
            req += pb_string(5, str(random.randint(0, 2**32 - 1)))  # random
            req += pb_msg(6, file_elem)               # msgBody
            req += pb_string(7, "")                   # refMsgId（空）
            msg_id = uuid.uuid4().hex
            frame = encode_conn_msg(
                cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_SEND_GROUP,
                seq_no=self.seq_no, msg_id=msg_id,
                module=BIZ_MODULE, data=req,
            )
            await self.ws.send(frame)
            return True
        except Exception as e:
            logger.error(f"发送文件消息失败: {e}")
            print(f"[{_fmt_time()}] ❌ 发送文件消息异常: {e}")
            return False

    # ── 发送贴纸消息 ───────────────────────────────

    async def send_group_sticker_message(self, group_code: str,
                                          sticker_id: str, package_id: str,
                                          name: str = "",
                                          width: int = 128, height: int = 128,
                                          formats: str = "png") -> bool:
        """发送贴纸消息到群"""
        if not self.connected or not self.ws:
            print(f"[{_fmt_time()}] ⚠️ 贴纸发送失败：未连接")
            return False
        try:
            self.seq_no += 1
            face_elem = encode_tim_face_elem(sticker_id, package_id, name,
                                             width, height, formats)
            req = b""
            req += pb_string(1, str(self.seq_no))     # msg_id
            req += pb_string(2, group_code)           # group_code
            req += pb_string(3, self.bot_id or "")    # from_account
            req += pb_string(4, "")                   # to_account（空）
            req += pb_string(5, str(random.randint(0, 2**32 - 1)))  # random
            req += pb_msg(6, face_elem)               # msgBody
            req += pb_string(7, "")                   # refMsgId（空）
            msg_id = uuid.uuid4().hex
            frame = encode_conn_msg(
                cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_SEND_GROUP,
                seq_no=self.seq_no, msg_id=msg_id,
                module=BIZ_MODULE, data=req,
            )
            await self.ws.send(frame)
            return True
        except Exception as e:
            logger.error(f"发送贴纸消息失败: {e}")
            print(f"[{_fmt_time()}] ❌ 发送贴纸消息异常: {e}")
            return False

    # ── 发送撤回通知 ─────────────────────────────────

    @staticmethod
    def _fmt_msg_time(ts) -> str:
        """将 Unix 时间戳（秒或毫秒）格式化为 HH:MM:SS"""
        if isinstance(ts, (int, float)):
            ts_sec = ts if ts < 1e12 else ts / 1000  # 兼容毫秒
            try:
                return datetime.fromtimestamp(ts_sec).strftime("%H:%M:%S")
            except (OSError, ValueError):
                return str(ts)
        if isinstance(ts, str):
            # 字符串数字
            if ts.isdigit():
                return MonitorClient._fmt_msg_time(int(ts))
            return ts  # 已经是格式化字符串
        return str(ts)

    async def _send_recall_notification(self, push_data: dict, seq: int):
        """向群内发送撤回通知（终端显示 + 发到群）
        
        如果撤回的消息是图片/贴纸/文件，尝试重新发送原内容；
        否则发送文字通知。
        """
        group_code = push_data.get("group_code", "")

        if group_code != DEFAULT_GROUP_CODE:
            return

        # 获取撤回的消息列表
        recall_list = push_data.get("recall_msg_seq_list", [])
        if not recall_list:
            return

        for item in recall_list:
            recalled_msg_id = item.get("msg_id", "")
            recalled_msg_seq = item.get("msg_seq", 0)

            row = None
            if recalled_msg_id:
                row = self.store.find_by_msg_id(recalled_msg_id)
            if row is None and recalled_msg_seq:
                row = self.store.find_by_msg_seq(recalled_msg_seq)

            if row:
                orig_content = row["content"] or ""
                orig_time = self._fmt_msg_time(row["time"] or 0)
                orig_sender = row["sender_name"] or "未知"
                print(f"[{_fmt_time()}] {orig_sender}: 撤回了一条消息")
                print(f"  └─ 原内容: {orig_content}")

                # 检查是否有媒体信息（图片/文件）
                media_raw = row["media_info"]
                media_info = json.loads(media_raw) if media_raw and media_raw != "null" else {}

                notif = (
                    f"—— 撤回通知 ——\n"
                    f"撤回者: {orig_sender}\n"
                    f"原发送者: {orig_sender}\n"
                    f"发送时间: {orig_time}"
                )

                if media_info.get("type") == "image":
                    # 发送图片 + 文字通知
                    urls = media_info.get("image_urls", [])
                    if urls and urls[0]:
                        print(f"  └─ 📷 重新发送图片...")
                        ok = await self.send_group_image_message(
                            group_code, urls[0],
                            media_uuid=media_info.get("image_uuid", ""),
                            size=media_info.get("image_size", 0),
                            width=media_info.get("image_width", 0),
                            height=media_info.get("image_height", 0),
                        )
                        if ok:
                            print(f"  └─ ✅ 图片已重新发送")
                            # 再发一条文字通知
                            ok2 = await self.send_group_message(group_code, notif)
                            continue
                        else:
                            print(f"  └─ ❌ 图片重新发送失败，回退到文字通知")
                    # 图片发送失败，继续往下走文字通知

                elif media_info.get("type") == "sticker":
                    # 发送贴纸 + 文字通知
                    sticker_id = media_info.get("sticker_id", "")
                    package_id = media_info.get("package_id", "")
                    sticker_name = media_info.get("sticker_name", "")
                    if sticker_id and package_id:
                        print(f"  └─ 🎨 重新发送贴纸 [{sticker_name}]...")
                        ok = await self.send_group_sticker_message(
                            group_code,
                            sticker_id=sticker_id,
                            package_id=package_id,
                            name=sticker_name,
                        )
                        if ok:
                            print(f"  └─ ✅ 贴纸已重新发送")
                            ok2 = await self.send_group_message(group_code, notif)
                            continue
                        else:
                            print(f"  └─ ❌ 贴纸重新发送失败，回退到文字通知")
                    # 贴纸发送失败，继续往下走文字通知

                elif media_info.get("type") == "file":
                    file_url = media_info.get("file_url", "")
                    if file_url:
                        print(f"  └─ 📎 重新发送文件...")
                        ok = await self.send_group_file_message(
                            group_code, file_url,
                            file_name=media_info.get("file_name", ""),
                            media_uuid=media_info.get("file_uuid", ""),
                            file_size=media_info.get("file_size", 0),
                        )
                        if ok:
                            print(f"  └─ ✅ 文件已重新发送")
                            ok2 = await self.send_group_message(group_code, notif)
                            continue
                        else:
                            print(f"  └─ ❌ 文件重新发送失败，回退到文字通知")

                # 文字通知（默认/回退）
                # 转义反斜杠（避免 LaTeX 命令被渲染，\\ 显示为原始 \）
                # 再转义 $（避免 LaTeX 数学模式，\$ 显示为原始 $）
                # [] 不转义为 \[ \]（会触发 LaTeX 数学模式），改用零宽空格插入打断 Markdown 链接语法
                display_content = (
                    orig_content
                    .replace("\\", "\\\\")
                    .replace("$", "\\$")
                    .replace("<", "\\<")
                    .replace(">", "\\>")
                    .replace("[", "[\u200b")
                    .replace("]", "\u200b]")
                )
                notif += f"\n原内容: {display_content}"
                ok = await self.send_group_message(group_code, notif)
                if ok:
                    print(f"  └─ ✅ 已发送撤回通知到群")
                else:
                    print(f"  └─ ❌ 撤回通知发送失败")
            else:
                notif = f"—— 撤回通知 ——\n撤回了消息\n原内容: [未找到已缓存的消息]"
                print(f"[{_fmt_time()}] 未知: 撤回了一条消息")
                print(f"  └─ {notif}")
                ok = await self.send_group_message(group_code, notif)
                if ok:
                    print(f"  └─ ✅ 已发送撤回通知到群")
                else:
                    print(f"  └─ ❌ 撤回通知发送失败")

    # ── 接收循环 ─────────────────────────────────────

    async def _receive_loop(self):
        while self.connected and self.running:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=HEARTBEAT_INTERVAL + 10)
            except asyncio.TimeoutError:
                logger.warning("接收超时，触发重连")
                break
            except Exception as e:
                logger.error(f"接收异常: {e}")
                print(f"[{_fmt_time()}] ❌ 接收异常: {e}")
                break

            try:
                decoded = decode_conn_msg(raw)
            except Exception as e:
                logger.warning(f"decode_conn_msg 失败: {e}")
                continue

            cmd_type = decoded.get("cmd_type")
            cmd = decoded.get("cmd")

            # ── 只处理推送消息 ──
            if cmd_type != CMD_TYPE_PUSH:
                continue
            if cmd != "inbound_message":
                continue

            biz_data = decoded.get("data", b"")
            if not biz_data:
                continue

            try:
                # biz_data 可能是 JSON 或 protobuf；先尝试 JSON
                push_json = json.loads(biz_data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            group_code = push_json.get("group_code", "")
            callback_command = push_json.get("callback_command", "")

            # 过滤群号
            if group_code and group_code != DEFAULT_GROUP_CODE:
                continue

            # ── 检测撤回 ──
            if callback_command == "Group.CallbackAfterRecallMsg":
                await self._send_recall_notification(push_json, self.seq_no)
                continue

            # ── 普通消息 ──
            sender_id = push_json.get("from_account", "")
            sender_name = push_json.get("sender_nickname", sender_id)
            msg_seq = push_json.get("msg_seq", 0)
            msg_id = push_json.get("msg_id", "")
            msg_time = self._fmt_msg_time(push_json.get("msg_time", ""))
            msg_body = push_json.get("msg_body", [])

            text = self._extract_text(msg_body)
            media_info = self._extract_media_info(msg_body)

            # 没有文本内容的显示类型占位
            if not text:
                # 检查是否有媒体
                if msg_body:
                    types = [e.get("msg_type", "?") for e in msg_body]
                    text = f"[{' + '.join(types)}]"
                else:
                    text = "[无文本]"

            # 入库（time_str 存原始值供撤回查找用）
            self.store.add_message(
                msg_id=msg_id, msg_seq=msg_seq, content=text,
                sender_name=sender_name, sender_id=sender_id,
                group_code=group_code, time_str=str(push_json.get("msg_time", "")),
                media_info=media_info,
            )

            # 获取编号并输出
            mid = self.store.get_next_id() - 1
            print(f"[{_fmt_time()}] #{mid} {sender_name}: {text}")


# ─── 入口 ─────────────────────────────────────────────

async def main():
    store = MessageStore(DB_PATH)

    # 显示启动信息
    total = (store.conn.execute("SELECT MAX(id) FROM messages").fetchone()[0] or 0)
    print(f"📡 元宝群消息监听器")
    print(f"📋 群号: {DEFAULT_GROUP_CODE}")
    print(f"💾 数据库已有 {total} 条记录")
    print(f"🔄 最大重连次数: {MAX_RECONNECT_ATTEMPTS}")
    print()

    client = MonitorClient(store)
    attempt = 0

    try:
        while client.running:
            attempt += 1
            if attempt > MAX_RECONNECT_ATTEMPTS:
                print(f"[{_fmt_time()}] ❌ 重连已达上限 ({MAX_RECONNECT_ATTEMPTS} 次)，退出程序。")
                break

            if attempt > 1:
                delay = min(2 ** min(attempt - 1, 5), 30)
                print(f"[{_fmt_time()}] 🔄 第 {attempt}/{MAX_RECONNECT_ATTEMPTS} 次重连，等待 {delay}s...")
                await asyncio.sleep(delay)

            # 重新签票（每次重连都重新签名，token 可能过期）
            client.token = None
            if not client.sign_token():
                print(f"[{_fmt_time()}] ❌ 签票失败")
                continue

            if not await client.connect():
                print(f"[{_fmt_time()}] ❌ 连接失败")
                continue

            # 进入接收循环（阻塞直到断开）
            await client._receive_loop()

            # 走到这里说明连接已断开
            client.connected = False
            if client.ws:
                try:
                    await asyncio.wait_for(client.ws.close(), timeout=1)
                except Exception:
                    pass
                client.ws = None

            if client.running:
                print(f"[{_fmt_time()}] 🔌 连接已断开，准备重连...")
    except (KeyboardInterrupt, asyncio.CancelledError):
        client.running = False
        client.connected = False
        if client.ws:
            try:
                await asyncio.wait_for(client.ws.close(), timeout=1)
            except Exception:
                pass
            client.ws = None
        print(f"\n[{_fmt_time()}] 👋 用户退出")

    store.close()
    print(f"[{_fmt_time()}] 程序已退出。")


if __name__ == "__main__":
    asyncio.run(main())
