#!/usr/bin/env python3
"""
元宝 Bot Web 控制台 - 完整功能版
基于 Flask 的可视化界面，支持所有命令功能。
"""
import sys
import os
import json
import asyncio
import threading
import time
import hashlib
import hmac
import random
import string
import uuid
import struct
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Tuple, Any
from functools import wraps

import requests
from flask import Flask, jsonify, request, render_template, Response, stream_with_context

# ----- 核心发送器类 (从sender.py移植并适配) -----
import websockets

# Protobuf 编解码器 (简化版，同sender.py)
class SimpleProtobufCodec:
    @staticmethod
    def encode_varint(value: int) -> bytes:
        result = []
        while value > 127:
            result.append((value & 0x7f) | 0x80)
            value >>= 7
        result.append(value)
        return bytes(result)

    @staticmethod
    def encode_string(field_num: int, value: str) -> bytes:
        tag = (field_num << 3) | 2
        encoded = value.encode('utf-8')
        return bytes([tag]) + SimpleProtobufCodec.encode_varint(len(encoded)) + encoded

    @staticmethod
    def encode_message_field(field_num: int, encoded_msg: bytes) -> bytes:
        tag = (field_num << 3) | 2
        return bytes([tag]) + SimpleProtobufCodec.encode_varint(len(encoded_msg)) + encoded_msg

    @staticmethod
    def encode_uint32(field_num: int, value: int) -> bytes:
        tag = (field_num << 3) | 0
        return bytes([tag]) + SimpleProtobufCodec.encode_varint(value)

    @staticmethod
    def encode_head(cmd_type: int, cmd: str, seq_no: int, msg_id: str, module: str) -> bytes:
        data = b''
        data += bytes([(1 << 3) | 0]) + SimpleProtobufCodec.encode_varint(cmd_type)
        data += SimpleProtobufCodec.encode_string(2, cmd)
        data += bytes([(3 << 3) | 0]) + SimpleProtobufCodec.encode_varint(seq_no)
        data += SimpleProtobufCodec.encode_string(4, msg_id)
        data += SimpleProtobufCodec.encode_string(5, module)
        return data

    @staticmethod
    def encode_conn_msg(head: bytes, data: bytes = b'') -> bytes:
        result = SimpleProtobufCodec.encode_message_field(1, head)
        if data:
            result += SimpleProtobufCodec.encode_message_field(2, data)
        return result

    @staticmethod
    def encode_send_group_msg_req(msg_id: str, group_code: str, from_account: str, text: str, ref_msg_id: str = "") -> bytes:
        data = b''
        data += SimpleProtobufCodec.encode_string(1, msg_id)
        data += SimpleProtobufCodec.encode_string(2, group_code)
        data += SimpleProtobufCodec.encode_string(3, from_account)
        data += SimpleProtobufCodec.encode_string(5, str(random.randint(1, 999999999)))
        msg_content = SimpleProtobufCodec.encode_string(1, text)
        msg_body_elem = SimpleProtobufCodec.encode_string(1, "TIMTextElem")
        msg_body_elem += SimpleProtobufCodec.encode_message_field(2, msg_content)
        data += SimpleProtobufCodec.encode_message_field(6, msg_body_elem)
        if ref_msg_id:
            data += SimpleProtobufCodec.encode_string(7, ref_msg_id)
        return data

    @staticmethod
    def encode_send_c2c_msg_req(msg_id: str, to_account: str, from_account: str, text: str) -> bytes:
        data = b''
        data += SimpleProtobufCodec.encode_string(1, msg_id)
        data += SimpleProtobufCodec.encode_string(2, to_account)
        data += SimpleProtobufCodec.encode_string(3, from_account)
        data += bytes([(4 << 3) | 0]) + SimpleProtobufCodec.encode_varint(random.randint(1, 999999999))
        msg_content = SimpleProtobufCodec.encode_string(1, text)
        msg_body_elem = SimpleProtobufCodec.encode_string(1, "TIMTextElem")
        msg_body_elem += SimpleProtobufCodec.encode_message_field(2, msg_content)
        data += SimpleProtobufCodec.encode_message_field(5, msg_body_elem)
        return data

    @staticmethod
    def encode_get_group_member_list_req(group_code: str) -> bytes:
        data = b''
        data += SimpleProtobufCodec.encode_string(1, group_code)
        return data

    @staticmethod
    def decode_varint(data: bytes, pos: int) -> tuple:
        value = 0
        shift = 0
        while pos < len(data):
            byte = data[pos]
            pos += 1
            value |= (byte & 0x7f) << shift
            if not (byte & 0x80):
                break
            shift += 7
        return value, pos

    @staticmethod
    def decode_conn_msg(data: bytes) -> Optional[dict]:
        result = {"head": {}, "data": b""}
        i = 0
        while i < len(data):
            tag = data[i]
            i += 1
            field_num = tag >> 3
            wire_type = tag & 7
            if wire_type != 2:
                break
            length, i = SimpleProtobufCodec.decode_varint(data, i)
            field_data = data[i:i+length]
            i += length
            if field_num == 1:
                result["head"] = SimpleProtobufCodec.decode_head(field_data)
            elif field_num == 2:
                result["data"] = field_data
        return result

    @staticmethod
    def decode_head(data: bytes) -> dict:
        head = {"cmd_type": 0}
        i = 0
        while i < len(data):
            tag = data[i]
            i += 1
            field_num = tag >> 3
            wire_type = tag & 7
            if wire_type == 0:
                val, i = SimpleProtobufCodec.decode_varint(data, i)
                if field_num == 1:
                    head["cmd_type"] = val
                elif field_num == 3:
                    head["seq_no"] = val
            elif wire_type == 2:
                length, i = SimpleProtobufCodec.decode_varint(data, i)
                field_data = data[i:i+length]
                i += length
                if field_num == 2:
                    head["cmd"] = field_data.decode('utf-8', errors='replace')
                elif field_num == 4:
                    head["msg_id"] = field_data.decode('utf-8', errors='replace')
                elif field_num == 5:
                    head["module"] = field_data.decode('utf-8', errors='replace')
        return head

    @staticmethod
    def decode_get_group_member_list_rsp(data: bytes) -> dict:
        result = {"code": 0, "message": "", "member_list": []}
        i = 0
        while i < len(data):
            if i >= len(data):
                break
            tag = data[i]
            i += 1
            field_num = tag >> 3
            wire_type = tag & 7
            if wire_type == 0:
                val, i = SimpleProtobufCodec.decode_varint(data, i)
                if field_num == 1:
                    result["code"] = val
            elif wire_type == 2:
                length, i = SimpleProtobufCodec.decode_varint(data, i)
                field_data = data[i:i+length]
                i += length
                if field_num == 2:
                    result["message"] = field_data.decode('utf-8', errors='replace')
                elif field_num == 3:
                    member = SimpleProtobufCodec._decode_member(field_data)
                    if member:
                        result["member_list"].append(member)
        return result

    @staticmethod
    def _decode_member(data: bytes) -> Optional[dict]:
        member = {}
        i = 0
        while i < len(data):
            tag = data[i]
            i += 1
            field_num = tag >> 3
            wire_type = tag & 7
            if wire_type == 0:
                val, i = SimpleProtobufCodec.decode_varint(data, i)
                if field_num == 3:
                    member["user_type"] = val
            elif wire_type == 2:
                length, i = SimpleProtobufCodec.decode_varint(data, i)
                field_data = data[i:i+length]
                i += length
                if field_num == 1:
                    member["user_id"] = field_data.decode('utf-8', errors='replace')
                elif field_num == 2:
                    member["nick_name"] = field_data.decode('utf-8', errors='replace')
        return member if member else None

    @staticmethod
    def encode_tim_face_elem(sticker_id: str, package_id: str, name: str,
                              width: int = 128, height: int = 128, formats: str = "png") -> bytes:
        data_json = json.dumps({
            "sticker_id": sticker_id,
            "package_id": package_id,
            "width": width,
            "height": height,
            "formats": formats,
            "name": name,
        }, ensure_ascii=False)
        msg_content = b''
        msg_content += bytes([(9 << 3) | 0]) + SimpleProtobufCodec.encode_varint(0)
        msg_content += SimpleProtobufCodec.encode_string(4, data_json)
        elem = b''
        elem += SimpleProtobufCodec.encode_string(1, "TIMFaceElem")
        elem += SimpleProtobufCodec.encode_message_field(2, msg_content)
        return elem

    @staticmethod
    def encode_tim_image_elem(url: str, uuid: str = "", size: int = 0, width: int = 0, height: int = 0, image_format: int = 255) -> bytes:
        image_info = b''
        image_info += bytes([(1 << 3) | 0]) + SimpleProtobufCodec.encode_varint(1)
        image_info += bytes([(2 << 3) | 0]) + SimpleProtobufCodec.encode_varint(size)
        image_info += bytes([(3 << 3) | 0]) + SimpleProtobufCodec.encode_varint(width)
        image_info += bytes([(4 << 3) | 0]) + SimpleProtobufCodec.encode_varint(height)
        image_info += SimpleProtobufCodec.encode_string(5, url)
        msg_content = b''
        if uuid:
            msg_content += SimpleProtobufCodec.encode_string(1, uuid)
        msg_content += bytes([(3 << 3) | 0]) + SimpleProtobufCodec.encode_varint(image_format)
        msg_content += SimpleProtobufCodec.encode_message_field(8, image_info)
        elem = b''
        elem += SimpleProtobufCodec.encode_string(1, "TIMImageElem")
        elem += SimpleProtobufCodec.encode_message_field(2, msg_content)
        return elem

# 配置加载
def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_config(config_data: dict):
    """将配置保存回 config.json（仅保留 Web 设置相关字段，不覆盖敏感信息）"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    try:
        # 读取当前完整配置
        with open(config_path, 'r', encoding='utf-8') as f:
            current = json.load(f)
        # 只更新 Web 可编辑的字段
        for key in ['DEFAULT_GROUP_CODE', 'AUTO_REPLY_GROUP_TEXT', 'AUTO_REPLY_C2C_TEXT']:
            if key in config_data:
                current[key] = config_data[key]
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存配置失败: {e}")
        return False

app_config = load_config()

# 从环境变量读取配置（优先），回退到 config.json
APP_KEY = os.environ.get('APP_KEY') or app_config.get('APP_KEY', '')
APP_SECRET = os.environ.get('APP_SECRET') or app_config.get('APP_SECRET', '')
API_DOMAIN = os.environ.get('API_DOMAIN') or app_config.get('API_DOMAIN', 'bot.yuanbao.tencent.com')
WS_URL = os.environ.get('WS_URL') or app_config.get('WS_URL', 'wss://bot-wss.yuanbao.tencent.com/wss/connection')
APP_PORT = int(os.environ.get('APP_PORT', '2570'))
APP_HOST = os.environ.get('APP_HOST', '0.0.0.0')

# 协议常量
CMD_TYPE_REQUEST = 0
CMD_TYPE_RESPONSE = 1
CMD_TYPE_PUSH = 2
CMD_AUTH_BIND = "auth-bind"
CMD_PING = "ping"
MODULE_CONN_ACCESS = "conn_access"
BIZ_MODULE = "yuanbao_openclaw_proxy"
BIZ_CMD_SEND_C2C = "send_c2c_message"
BIZ_CMD_SEND_GROUP = "send_group_message"
BIZ_CMD_GET_MEMBERS = "get_group_member_list"

class EnhancedSpamSender:
    def __init__(self):
        self.token: Optional[str] = None
        self.bot_id: Optional[str] = None
        self.ws = None
        self.connected = False
        self.seq_no = 0
        self.group_code: Optional[str] = None
        self.codec = SimpleProtobufCodec()
        self.user_db: Dict[str, str] = {}
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.msg_cache: List[dict] = []
        self.heartbeat_task = None
        self.receive_task = None
        self.loop = None

        self.STICKERS = {
            "六六六": {"sticker_id": "278", "package_id": "1003", "name": "六六六"},
            "我想开了": {"sticker_id": "262", "package_id": "1003", "name": "我想开了"},
            "害羞": {"sticker_id": "130", "package_id": "1003", "name": "害羞"},
            "比心": {"sticker_id": "252", "package_id": "1003", "name": "比心"},
            "委屈": {"sticker_id": "125", "package_id": "1003", "name": "委屈"},
            "亲亲": {"sticker_id": "146", "package_id": "1003", "name": "亲亲"},
            "酷": {"sticker_id": "131", "package_id": "1003", "name": "酷"},
            "睡": {"sticker_id": "145", "package_id": "1003", "name": "睡"},
            "发呆": {"sticker_id": "152", "package_id": "1003", "name": "发呆"},
            "可怜": {"sticker_id": "157", "package_id": "1003", "name": "可怜"},
            "摊手": {"sticker_id": "200", "package_id": "1003", "name": "摊手"},
            "头大": {"sticker_id": "213", "package_id": "1003", "name": "头大"},
            "吓": {"sticker_id": "256", "package_id": "1003", "name": "吓"},
            "吐血": {"sticker_id": "203", "package_id": "1003", "name": "吐血"},
            "哼": {"sticker_id": "185", "package_id": "1003", "name": "哼"},
            "嘿嘿": {"sticker_id": "220", "package_id": "1003", "name": "嘿嘿"},
            "头秃": {"sticker_id": "218", "package_id": "1003", "name": "头秃"},
            "暗中观察": {"sticker_id": "221", "package_id": "1003", "name": "暗中观察"},
            "我酸了": {"sticker_id": "224", "package_id": "1003", "name": "我酸了"},
            "打call": {"sticker_id": "246", "package_id": "1003", "name": "打call"},
            "庆祝": {"sticker_id": "251", "package_id": "1003", "name": "庆祝"},
            "奋斗": {"sticker_id": "151", "package_id": "1003", "name": "奋斗"},
            "惊讶": {"sticker_id": "143", "package_id": "1003", "name": "惊讶"},
            "疑问": {"sticker_id": "144", "package_id": "1003", "name": "疑问"},
            "仔细分析": {"sticker_id": "248", "package_id": "1003", "name": "仔细分析"},
            "撅嘴": {"sticker_id": "184", "package_id": "1003", "name": "撅嘴"},
            "泪奔": {"sticker_id": "199", "package_id": "1003", "name": "泪奔"},
            "尊嘟假嘟": {"sticker_id": "276", "package_id": "1003", "name": "尊嘟假嘟"},
            "略略略": {"sticker_id": "113", "package_id": "1003", "name": "略略略"},
            "困": {"sticker_id": "180", "package_id": "1003", "name": "困"},
            "折磨": {"sticker_id": "181", "package_id": "1003", "name": "折磨"},
            "抠鼻": {"sticker_id": "182", "package_id": "1003", "name": "抠鼻"},
            "鼓掌": {"sticker_id": "183", "package_id": "1003", "name": "鼓掌"},
            "斜眼笑": {"sticker_id": "204", "package_id": "1003", "name": "斜眼笑"},
            "辣眼睛": {"sticker_id": "216", "package_id": "1003", "name": "辣眼睛"},
            "哦哟": {"sticker_id": "217", "package_id": "1003", "name": "哦哟"},
            "吃瓜": {"sticker_id": "222", "package_id": "1003", "name": "吃瓜"},
            "狗头": {"sticker_id": "225", "package_id": "1003", "name": "狗头"},
            "敬礼": {"sticker_id": "227", "package_id": "1003", "name": "敬礼"},
            "哦": {"sticker_id": "231", "package_id": "1003", "name": "哦"},
            "拿到红包": {"sticker_id": "236", "package_id": "1003", "name": "拿到红包"},
            "牛吖": {"sticker_id": "239", "package_id": "1003", "name": "牛吖"},
            "贴贴": {"sticker_id": "272", "package_id": "1003", "name": "贴贴"},
            "爱心": {"sticker_id": "138", "package_id": "1003", "name": "爱心"},
            "晚安": {"sticker_id": "170", "package_id": "1003", "name": "晚安"},
            "太阳": {"sticker_id": "176", "package_id": "1003", "name": "太阳"},
            "柠檬": {"sticker_id": "266", "package_id": "1003", "name": "柠檬"},
            "大冤种": {"sticker_id": "267", "package_id": "1003", "name": "大冤种"},
            "吐了": {"sticker_id": "132", "package_id": "1003", "name": "吐了"},
            "怒": {"sticker_id": "134", "package_id": "1003", "name": "怒"},
            "玫瑰": {"sticker_id": "165", "package_id": "1003", "name": "玫瑰"},
            "凋谢": {"sticker_id": "119", "package_id": "1003", "name": "凋谢"},
            "点赞": {"sticker_id": "159", "package_id": "1003", "name": "点赞"},
            "握手": {"sticker_id": "164", "package_id": "1003", "name": "握手"},
            "抱拳": {"sticker_id": "163", "package_id": "1003", "name": "抱拳"},
            "ok": {"sticker_id": "169", "package_id": "1003", "name": "ok"},
            "拳头": {"sticker_id": "174", "package_id": "1003", "name": "拳头"},
            "鞭炮": {"sticker_id": "191", "package_id": "1003", "name": "鞭炮"},
            "烟花": {"sticker_id": "258", "package_id": "1003", "name": "烟花"},
        }

    def _generate_msg_id(self) -> str:
        return uuid.uuid4().hex

    def _get_beijing_time(self) -> str:
        utc = datetime.now(timezone.utc)
        beijing = utc + timedelta(hours=8)
        return beijing.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    def sign_token(self) -> bool:
        url = f"https://{API_DOMAIN}/api/v5/robotLogic/sign-token"
        nonce = ''.join(random.choices(string.hexdigits.lower(), k=32))
        timestamp = self._get_beijing_time()
        plain = f"{nonce}{timestamp}{APP_KEY}{APP_SECRET}"
        signature = hmac.new(APP_SECRET.encode(), plain.encode(), hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-AppVersion": "1.0.11",
            "X-OperationSystem": "linux",
            "X-Instance-Id": str(random.randint(1, 1000)),
            "X-Bot-Version": "2026.3.22"
        }
        body = {"app_key": APP_KEY, "nonce": nonce, "signature": signature, "timestamp": timestamp}
        try:
            response = requests.post(url, headers=headers, json=body, timeout=30)
            result = response.json()
            if result.get("code") == 0:
                data = result["data"]
                self.token = data["token"]
                self.bot_id = data["bot_id"]
                return True
            else:
                return False
        except Exception as e:
            print(f"签票错误: {e}")
            return False

    async def connect(self) -> bool:
        if not self.token and not self.sign_token():
            return False
        try:
            self.ws = await websockets.connect(WS_URL)
            auth_msg = self._build_auth_bind_msg()
            await self.ws.send(auth_msg)
            response = await self.ws.recv()
            self.connected = True
            self.heartbeat_task = asyncio.create_task(self._heartbeat())
            self.receive_task = asyncio.create_task(self._receive_loop())
            return True
        except Exception as e:
            print(f"连接失败: {e}")
            return False

    def _build_auth_bind_msg(self) -> bytes:
        auth_info = self.codec.encode_string(1, self.bot_id) + self.codec.encode_string(2, "web") + self.codec.encode_string(3, self.token)
        device_info = (self.codec.encode_string(1, "2.0.1") + self.codec.encode_string(2, "Linux") +
                       self.codec.encode_string(3, "2026.3.23-2") + self.codec.encode_string(4, "16"))
        auth_data = self.codec.encode_string(1, "ybBot") + self.codec.encode_message_field(2, auth_info) + self.codec.encode_message_field(3, device_info)
        head = self.codec.encode_head(CMD_TYPE_REQUEST, CMD_AUTH_BIND, self.seq_no, self._generate_msg_id(), MODULE_CONN_ACCESS)
        self.seq_no += 1
        return self.codec.encode_conn_msg(head, auth_data)

    async def _heartbeat(self):
        while self.connected:
            await asyncio.sleep(70)
            if not self.connected:
                break
            try:
                head = self.codec.encode_head(CMD_TYPE_REQUEST, CMD_PING, self.seq_no, self._generate_msg_id(), MODULE_CONN_ACCESS)
                self.seq_no += 1
                ping_msg = self.codec.encode_conn_msg(head)
                await self.ws.send(ping_msg)
            except:
                break

    async def _receive_loop(self):
        try:
            while self.connected and self.ws:
                raw = await self.ws.recv()
                if isinstance(raw, bytes):
                    conn_msg = self.codec.decode_conn_msg(raw)
                    if not conn_msg:
                        continue
                    head = conn_msg.get("head", {})
                    cmd_type = head.get("cmd_type")
                    cmd = head.get("cmd", "")
                    msg_id = head.get("msg_id")
                    if cmd_type == CMD_TYPE_PUSH and cmd == "inbound_message":
                        biz_data = conn_msg.get("data", b"")
                        try:
                            push_json = json.loads(biz_data)
                            text_content = ""
                            msg_body = push_json.get("msg_body", [])
                            for elem in msg_body:
                                msg_type = elem.get("msg_type", "")
                                msg_content = elem.get("msg_content", {})
                                if msg_type == "TIMTextElem":
                                    text_content += msg_content.get("text", "")
                                elif msg_type == "TIMCustomElem":
                                    data_str = msg_content.get("data", "{}")
                                    try:
                                        custom_data = json.loads(data_str)
                                        if custom_data.get("elem_type") == 1002:
                                            text_content += custom_data.get("text", "") + " "
                                    except:
                                        pass
                            cache_entry = {
                                "time": datetime.now().strftime("%H:%M:%S"),
                                "sender_id": push_json.get("from_account", ""),
                                "sender_name": push_json.get("sender_nickname", ""),
                                "group_code": push_json.get("group_code", ""),
                                "content": text_content,
                                "msg_type": push_json.get("callback_command", ""),
                                "msg_id": push_json.get("msg_id", ""),
                            }
                            self.msg_cache.append(cache_entry)
                            if len(self.msg_cache) > 1000:
                                self.msg_cache = self.msg_cache[-1000:]
                        except Exception as e:
                            pass
                    # 新增：处理响应消息
                    elif cmd_type == CMD_TYPE_RESPONSE:
                        if msg_id in self.pending_requests:
                            future = self.pending_requests.pop(msg_id)
                            try:
                                # 根据不同的命令类型处理响应
                                if cmd == BIZ_CMD_GET_MEMBERS:
                                    # 解码获取成员列表的响应
                                    data = conn_msg.get("data", b"")
                                    if data:
                                        result = self.codec.decode_get_group_member_list_rsp(data)
                                        future.set_result(result)
                                    else:
                                        future.set_result({"code": -1, "message": "响应数据为空"})
                                elif cmd == BIZ_CMD_SEND_GROUP or cmd == BIZ_CMD_SEND_C2C:
                                    # 发送消息的响应
                                    future.set_result({"code": 0, "message": "发送成功"})
                                else:
                                    # 其他类型的响应
                                    future.set_result(conn_msg)
                            except Exception as e:
                                future.set_exception(e)
                    
        except Exception as e:
            print(f"接收循环异常: {e}")

    async def disconnect(self):
        self.connected = False
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        if self.receive_task:
            self.receive_task.cancel()
        if self.ws:
            await self.ws.close()

    async def send_group_message(self, text: str, at_user: str = None, at_nickname: str = None, ref_msg_id: str = None) -> bool:
        if not self.connected or not self.ws:
            return False
        try:
            if at_user:
                display_name = at_nickname or at_user
                at_data = json.dumps({"elem_type": 1002, "text": f"@{display_name}", "user_id": at_user})
                at_content = self.codec.encode_string(4, at_data)
                at_elem = self.codec.encode_string(1, "TIMCustomElem") + self.codec.encode_message_field(2, at_content)
                text_content = self.codec.encode_string(1, text)
                text_elem = self.codec.encode_string(1, "TIMTextElem") + self.codec.encode_message_field(2, text_content)
                data = b''
                data += self.codec.encode_string(1, self._generate_msg_id())
                data += self.codec.encode_string(2, self.group_code)
                data += self.codec.encode_string(3, self.bot_id or "")
                data += self.codec.encode_string(5, str(random.randint(1, 999999999)))
                data += self.codec.encode_message_field(6, at_elem)
                data += self.codec.encode_message_field(6, text_elem)
                if ref_msg_id:
                    data += self.codec.encode_string(7, ref_msg_id)
            else:
                data = self.codec.encode_send_group_msg_req(self._generate_msg_id(), self.group_code, self.bot_id or "", text, ref_msg_id or "")
            head = self.codec.encode_head(CMD_TYPE_REQUEST, BIZ_CMD_SEND_GROUP, self.seq_no, self._generate_msg_id(), BIZ_MODULE)
            self.seq_no += 1
            msg = self.codec.encode_conn_msg(head, data)
            await self.ws.send(msg)
            self.msg_cache.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "sender_id": self.bot_id or "",
                "sender_name": "我",
                "group_code": self.group_code or "",
                "content": text,
                "msg_type": "send_group",
                "msg_id": "",
            })
            if len(self.msg_cache) > 1000:
                self.msg_cache = self.msg_cache[-1000:]
            return True
        except Exception as e:
            print(f"发送群消息失败: {e}")
            return False

    async def send_multi_at_message(self, text: str, at_users: list) -> bool:
        if not self.connected or not self.ws:
            return False
        try:
            data = b''
            data += self.codec.encode_string(1, self._generate_msg_id())
            data += self.codec.encode_string(2, self.group_code)
            data += self.codec.encode_string(3, self.bot_id or "")
            data += self.codec.encode_string(5, str(random.randint(1, 999999999)))
            for user_id, nickname in at_users:
                display_name = nickname or user_id
                at_data = json.dumps({"elem_type": 1002, "text": f"@{display_name}", "user_id": user_id})
                at_content = self.codec.encode_string(4, at_data)
                at_elem = self.codec.encode_string(1, "TIMCustomElem") + self.codec.encode_message_field(2, at_content)
                data += self.codec.encode_message_field(6, at_elem)
            text_content = self.codec.encode_string(1, text)
            text_elem = self.codec.encode_string(1, "TIMTextElem") + self.codec.encode_message_field(2, text_content)
            data += self.codec.encode_message_field(6, text_elem)
            head = self.codec.encode_head(CMD_TYPE_REQUEST, BIZ_CMD_SEND_GROUP, self.seq_no, self._generate_msg_id(), BIZ_MODULE)
            self.seq_no += 1
            msg = self.codec.encode_conn_msg(head, data)
            await self.ws.send(msg)
            self.msg_cache.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "sender_id": self.bot_id or "",
                "sender_name": "我",
                "group_code": self.group_code or "",
                "content": f"[批量艾特 {len(at_users)}人] {text}",
                "msg_type": "send_group",
                "msg_id": "",
            })
            if len(self.msg_cache) > 1000:
                self.msg_cache = self.msg_cache[-1000:]
            return True
        except Exception as e:
            print(f"发送批量艾特失败: {e}")
            return False

    async def send_sticker(self, sticker_name: str, text: str = "", at_user: str = None, at_nickname: str = None) -> bool:
        if not self.connected or not self.ws:
            return False
        if sticker_name not in self.STICKERS:
            return False
        try:
            sticker = self.STICKERS[sticker_name]
            face_elem = self.codec.encode_tim_face_elem(sticker["sticker_id"], sticker["package_id"], sticker["name"])
            data = b''
            data += self.codec.encode_string(1, self._generate_msg_id())
            data += self.codec.encode_string(2, self.group_code)
            data += self.codec.encode_string(3, self.bot_id or "")
            data += self.codec.encode_string(5, str(random.randint(1, 999999999)))
            if at_user:
                display_name = at_nickname or at_user
                at_data = json.dumps({"elem_type": 1002, "text": f"@{display_name}", "user_id": at_user})
                at_content = self.codec.encode_string(4, at_data)
                at_elem = self.codec.encode_string(1, "TIMCustomElem") + self.codec.encode_message_field(2, at_content)
                data += self.codec.encode_message_field(6, at_elem)
            data += self.codec.encode_message_field(6, face_elem)
            if text:
                text_content = self.codec.encode_string(1, text)
                text_elem = self.codec.encode_string(1, "TIMTextElem") + self.codec.encode_message_field(2, text_content)
                data += self.codec.encode_message_field(6, text_elem)
            head = self.codec.encode_head(CMD_TYPE_REQUEST, BIZ_CMD_SEND_GROUP, self.seq_no, self._generate_msg_id(), BIZ_MODULE)
            self.seq_no += 1
            msg = self.codec.encode_conn_msg(head, data)
            await self.ws.send(msg)
            self.msg_cache.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "sender_id": self.bot_id or "",
                "sender_name": "我",
                "group_code": self.group_code or "",
                "content": f"[贴纸:{sticker_name}] {text}",
                "msg_type": "send_sticker",
                "msg_id": "",
            })
            if len(self.msg_cache) > 1000:
                self.msg_cache = self.msg_cache[-1000:]
            return True
        except Exception as e:
            print(f"发送贴纸失败: {e}")
            return False

    async def send_c2c_message(self, to_account: str, text: str) -> bool:
        if not self.connected or not self.ws:
            return False
        try:
            data = self.codec.encode_send_c2c_msg_req(self._generate_msg_id(), to_account, self.bot_id or "", text)
            head = self.codec.encode_head(CMD_TYPE_REQUEST, BIZ_CMD_SEND_C2C, self.seq_no, self._generate_msg_id(), BIZ_MODULE)
            self.seq_no += 1
            msg = self.codec.encode_conn_msg(head, data)
            await self.ws.send(msg)
            self.msg_cache.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "sender_id": self.bot_id or "",
                "sender_name": "我",
                "to_account": to_account,
                "content": text,
                "msg_type": "send_c2c",
                "msg_id": "",
            })
            if len(self.msg_cache) > 1000:
                self.msg_cache = self.msg_cache[-1000:]
            return True
        except Exception as e:
            print(f"发送私聊失败: {e}")
            return False

    async def get_group_members(self) -> Optional[dict]:
        if not self.connected or not self.ws:
            return None
        try:
            msg_id = self._generate_msg_id()
            biz_data = self.codec.encode_get_group_member_list_req(self.group_code or "")
            head = self.codec.encode_head(CMD_TYPE_REQUEST, BIZ_CMD_GET_MEMBERS, self.seq_no, msg_id, BIZ_MODULE)
            self.seq_no += 1
            msg = self.codec.encode_conn_msg(head, biz_data)
            future = asyncio.get_event_loop().create_future()
            self.pending_requests[msg_id] = future
            await self.ws.send(msg)
            try:
                result = await asyncio.wait_for(future, timeout=30)
                return result
            except asyncio.TimeoutError:
                self.pending_requests.pop(msg_id, None)
                return None
        except Exception as e:
            print(f"获取群成员失败: {e}")
            return None

    async def spam_with_at(self, text: str, count: int, at_user: str = None, at_nickname: str = None, interval: float = 1.0) -> Tuple[int, int]:
        success = 0
        fail = 0
        for i in range(count):
            ok = await self.send_group_message(text, at_user, at_nickname)
            if ok:
                success += 1
            else:
                fail += 1
            if i < count - 1:
                await asyncio.sleep(interval)
        return success, fail

    async def spam_sticker(self, sticker_name: str, count: int, text: str = "", interval: float = 1.0) -> Tuple[int, int]:
        success = 0
        fail = 0
        for i in range(count):
            ok = await self.send_sticker(sticker_name, text)
            if ok:
                success += 1
            else:
                fail += 1
            if i < count - 1:
                await asyncio.sleep(interval)
        return success, fail

    async def spam_c2c(self, to_account: str, text: str, count: int, interval: float = 1.0) -> Tuple[int, int]:
        success = 0
        fail = 0
        for i in range(count):
            ok = await self.send_c2c_message(to_account, text)
            if ok:
                success += 1
            else:
                fail += 1
            if i < count - 1:
                await asyncio.sleep(interval)
        return success, fail

# ----- Flask Web 应用 -----
app = Flask(__name__)
sender = EnhancedSpamSender()
settings = {
    'group_code': app_config.get('DEFAULT_GROUP_CODE', ''),
    'interval': 1.0,
    'auto_reply_enabled': False,
    'group_reply_text': app_config.get('AUTO_REPLY_GROUP_TEXT', '@我干啥'),
    'c2c_reply_text': app_config.get('AUTO_REPLY_C2C_TEXT', '我是Bot'),
}

# Asyncio 事件循环
_loop = None
_loop_thread = None

def _run_loop():
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _loop.run_forever()

def _ensure_loop():
    global _loop, _loop_thread
    if _loop is None or not _loop.is_running():
        _loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(target=_run_loop, daemon=True)
        _loop_thread.start()
        time.sleep(0.1)

def async_call(coro):
    _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=30)

def async_call_no_wait(coro):
    _ensure_loop()
    asyncio.run_coroutine_threadsafe(coro, _loop)

# ----- 路由 -----
@app.route('/')
def index():
    return render_template('index.html')

# API: 连接管理
@app.route('/api/connect', methods=['POST'])
def api_connect():
    try:
        sender.group_code = settings['group_code']
        ok = async_call(sender.connect())
        if ok:
            return jsonify({'ok': True, 'message': '连接成功'})
        else:
            return jsonify({'ok': False, 'message': '连接失败，请检查配置'}), 400
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500

@app.route('/api/disconnect', methods=['POST'])
def api_disconnect():
    try:
        async_call(sender.disconnect())
        return jsonify({'ok': True, 'message': '已断开连接'})
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500

@app.route('/api/status', methods=['GET'])
def api_status():
    return jsonify({
        'connected': sender.connected,
        'group_code': sender.group_code or settings['group_code'],
        'user_count': len(sender.user_db),
        'message_count': len(sender.msg_cache),
        'bot_id': sender.bot_id or '',
    })

# API: 消息
@app.route('/api/messages', methods=['GET'])
def api_messages():
    limit = request.args.get('limit', 50, type=int)
    cache = sender.msg_cache
    messages = cache[-limit:] if cache else []
    return jsonify({
        'messages': messages,
        'total': len(cache),
    })

@app.route('/api/send', methods=['POST'])
def api_send():
    if not sender.connected:
        return jsonify({'ok': False, 'message': '未连接'}), 400
    data = request.get_json(force=True)
    mode = data.get('mode', 'normal')
    text = data.get('text', '')
    target = data.get('target', '')
    count = int(data.get('count', 1))
    interval = float(data.get('interval', settings['interval']))
    ref_msg_id = data.get('ref_msg_id', '')

    try:
        if mode == 'normal':
            ok = async_call(sender.send_group_message(text, ref_msg_id=ref_msg_id))
            return jsonify({'ok': ok, 'message': '发送成功' if ok else '发送失败'})
        elif mode == 'at':
            if not target:
                return jsonify({'ok': False, 'message': '请指定目标用户'}), 400
            parts = target.split(':', 1)
            user_id = parts[0].strip()
            nickname = parts[1].strip() if len(parts) > 1 else user_id
            ok = async_call(sender.send_group_message(text, user_id, nickname, ref_msg_id))
            return jsonify({'ok': ok, 'message': '发送成功' if ok else '发送失败'})
        elif mode == 'spam':
            success, fail = async_call(sender.spam_with_at(text, count, interval=interval))
            return jsonify({
                'ok': fail == 0,
                'message': f'刷屏完成: 成功 {success}, 失败 {fail}',
                'success': success,
                'fail': fail,
            })
        elif mode == 'atspam':
            if not target:
                return jsonify({'ok': False, 'message': '请指定目标用户'}), 400
            parts = target.split(':', 1)
            user_id = parts[0].strip()
            nickname = parts[1].strip() if len(parts) > 1 else user_id
            success, fail = async_call(sender.spam_with_at(text, count, user_id, nickname, interval))
            return jsonify({
                'ok': fail == 0,
                'message': f'艾特刷屏完成: 成功 {success}, 失败 {fail}',
                'success': success,
                'fail': fail,
            })
        elif mode == 'multi-at':
            if not target:
                return jsonify({'ok': False, 'message': '请指定目标用户'}), 400
            user_ids = [u.strip() for u in target.split(',') if u.strip()]
            at_users = []
            for uid in user_ids:
                if ':' in uid:
                    uid_part, nick_part = uid.split(':', 1)
                    at_users.append((uid_part.strip(), nick_part.strip()))
                else:
                    nick = sender.user_db.get(uid, uid)
                    at_users.append((uid.strip(), nick))
            ok = async_call(sender.send_multi_at_message(text, at_users))
            return jsonify({'ok': ok, 'message': '发送成功' if ok else '发送失败'})
        elif mode == 'dm':
            if not target:
                return jsonify({'ok': False, 'message': '请指定目标用户'}), 400
            ok = async_call(sender.send_c2c_message(target, text))
            return jsonify({'ok': ok, 'message': '发送成功' if ok else '发送失败'})
        elif mode == 'dmspam':
            if not target:
                return jsonify({'ok': False, 'message': '请指定目标用户'}), 400
            success, fail = async_call(sender.spam_c2c(target, text, count, interval))
            return jsonify({
                'ok': fail == 0,
                'message': f'私聊刷屏完成: 成功 {success}, 失败 {fail}',
                'success': success,
                'fail': fail,
            })
        else:
            return jsonify({'ok': False, 'message': f'未知模式: {mode}'}), 400
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500

@app.route('/api/send-sticker', methods=['POST'])
def api_send_sticker():
    if not sender.connected:
        return jsonify({'ok': False, 'message': '未连接'}), 400
    data = request.get_json(force=True)
    name = data.get('name', '')
    text = data.get('text', '')
    at_user = data.get('at_user', '')
    count = int(data.get('count', 1))
    interval = float(data.get('interval', settings['interval']))
    if not name:
        return jsonify({'ok': False, 'message': '请选择贴纸'}), 400
    try:
        if count > 1:
            success, fail = async_call(sender.spam_sticker(name, count, text, interval))
            return jsonify({
                'ok': fail == 0,
                'message': f'贴纸刷屏完成: 成功 {success}, 失败 {fail}',
                'success': success,
                'fail': fail,
            })
        else:
            if at_user:
                nick = sender.user_db.get(at_user, at_user)
                ok = async_call(sender.send_sticker(name, text, at_user, nick))
            else:
                ok = async_call(sender.send_sticker(name, text))
            return jsonify({'ok': ok, 'message': '发送成功' if ok else '发送失败'})
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500

@app.route('/api/send-reply', methods=['POST'])
def api_send_reply():
    if not sender.connected:
        return jsonify({'ok': False, 'message': '未连接'}), 400
    data = request.get_json(force=True)
    index = int(data.get('index', -1))
    text = data.get('text', '')
    at_user = data.get('at_user', '')
    count = int(data.get('count', 1))
    interval = float(data.get('interval', settings['interval']))
    if index < 0 or index >= len(sender.msg_cache):
        return jsonify({'ok': False, 'message': '无效的消息序号'}), 400
    target_msg = sender.msg_cache[index]
    ref_msg_id = target_msg.get('msg_id', '')
    try:
        if count > 1:
            success, fail = 0, 0
            for i in range(count):
                if at_user:
                    nick = sender.user_db.get(at_user, at_user)
                    ok = async_call(sender.send_group_message(text, at_user, nick, ref_msg_id))
                else:
                    ok = async_call(sender.send_group_message(text, ref_msg_id=ref_msg_id))
                if ok:
                    success += 1
                else:
                    fail += 1
                if i < count - 1:
                    time.sleep(interval)
            return jsonify({
                'ok': fail == 0,
                'message': f'引用刷屏完成: 成功 {success}, 失败 {fail}',
                'success': success,
                'fail': fail,
            })
        else:
            if at_user:
                nick = sender.user_db.get(at_user, at_user)
                ok = async_call(sender.send_group_message(text, at_user, nick, ref_msg_id))
            else:
                ok = async_call(sender.send_group_message(text, ref_msg_id=ref_msg_id))
            return jsonify({'ok': ok, 'message': '回复成功' if ok else '回复失败'})
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500

# API: 成员
@app.route('/api/members', methods=['GET'])
def api_members():
    if not sender.connected:
        return jsonify({'ok': False, 'message': '未连接', 'members': []}), 400
    try:
        result = async_call(sender.get_group_members())
        if result and result.get('code') == 0:
            members = result.get('member_list', [])
            for m in members:
                uid = m.get('user_id', '')
                nick = m.get('nick_name', '')
                if uid:
                    sender.user_db[uid] = nick
            return jsonify({
                'ok': True,
                'members': members,
                'count': len(members),
            })
        else:
            msg = result.get('message', '获取失败') if result else '无响应'
            return jsonify({'ok': False, 'message': msg, 'members': []}), 400
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e), 'members': []}), 500

@app.route('/api/users', methods=['GET'])
def api_users():
    return jsonify({
        'users': [{'user_id': k, 'nickname': v} for k, v in sender.user_db.items()],
        'count': len(sender.user_db),
    })

@app.route('/api/users', methods=['POST'])
def api_add_user():
    data = request.get_json(force=True)
    user_id = data.get('user_id', '').strip()
    nickname = data.get('nickname', '').strip()
    if not user_id:
        return jsonify({'ok': False, 'message': '用户ID不能为空'}), 400
    sender.user_db[user_id] = nickname or user_id
    return jsonify({'ok': True, 'message': '用户添加成功'})

@app.route('/api/users/<user_id>', methods=['DELETE'])
def api_delete_user(user_id):
    if user_id in sender.user_db:
        del sender.user_db[user_id]
        return jsonify({'ok': True, 'message': '用户删除成功'})
    else:
        return jsonify({'ok': False, 'message': '用户不存在'}), 404

# API: 贴纸
@app.route('/api/stickers', methods=['GET'])
def api_stickers():
    query = request.args.get('q', '').lower()
    stickers = []
    for key, info in sender.STICKERS.items():
        if query in key.lower() or query in info.get('name', '').lower():
            stickers.append({
                'key': key,
                'name': info.get('name', key),
                'sticker_id': info.get('sticker_id', ''),
                'package_id': info.get('package_id', ''),
            })
    return jsonify({
        'stickers': stickers,
        'count': len(stickers),
    })

# API: 设置
@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    return jsonify(settings)

@app.route('/api/settings', methods=['POST'])
def api_update_settings():
    global app_config
    data = request.get_json(force=True)
    save_data = {}
    if 'group_code' in data:
        settings['group_code'] = str(data['group_code'])
        sender.group_code = settings['group_code']
        save_data['DEFAULT_GROUP_CODE'] = settings['group_code']
    if 'interval' in data:
        try:
            settings['interval'] = float(data['interval'])
        except (ValueError, TypeError):
            pass
    if 'auto_reply_enabled' in data:
        settings['auto_reply_enabled'] = bool(data['auto_reply_enabled'])
    if 'group_reply_text' in data:
        settings['group_reply_text'] = str(data['group_reply_text'])
        save_data['AUTO_REPLY_GROUP_TEXT'] = settings['group_reply_text']
    if 'c2c_reply_text' in data:
        settings['c2c_reply_text'] = str(data['c2c_reply_text'])
        save_data['AUTO_REPLY_C2C_TEXT'] = settings['c2c_reply_text']
    # 持久化到 config.json
    if save_data:
        save_config(save_data)
        app_config.update(save_data)
    return jsonify({'ok': True, 'settings': settings})

# API: SSE 事件流
@app.route('/api/events')
def api_events():
    def generate():
        last_len = len(sender.msg_cache)
        while True:
            current_len = len(sender.msg_cache)
            if current_len > last_len:
                new_messages = sender.msg_cache[last_len:]
                last_len = current_len
                for msg in new_messages:
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            elif current_len < last_len:
                last_len = current_len
            yield ": heartbeat\n\n"
            time.sleep(0.5)
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        }
    )

if __name__ == '__main__':
    import socket
    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return '127.0.0.1'
    local_ip = get_local_ip()
    print("=" * 56)
    print("  元宝 Bot Web 控制台 - 完整功能版")
    print("=" * 56)
    print()
    print(f"  本地访问:  http://127.0.0.1:{APP_PORT}")
    print(f"  手机访问:  http://{local_ip}:{APP_PORT}")
    print(f"  监听地址:  {APP_HOST}:{APP_PORT}")
    print()
    print("  按 Ctrl+C 停止服务器")
    print("=" * 56)
    app.run(host=APP_HOST, port=APP_PORT, debug=False, threaded=True)