#!/usr/bin/env python3
"""
元宝 Bot 刷屏+艾特 增强发送器
基于 interactive_sender.py 改造，支持同时刷屏和艾特
"""

import asyncio
import sys
import json
import hashlib
import hmac
import random
import string
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import requests


async def async_input(prompt: str = "") -> str:
    """异步版本的 input()，避免阻塞事件循环"""
    if prompt:
        print(prompt, end="", flush=True)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sys.stdin.readline)
import websockets
# 从配置文件导入
import json
with open("config1.json", "r", encoding="utf-8") as f:
    _config = json.load(f)
APP_KEY = _config["APP_KEY"]
APP_SECRET = _config["APP_SECRET"]
API_DOMAIN = _config["API_DOMAIN"]
WS_URL = _config["WS_URL"]

# 协议常量
CMD_TYPE_REQUEST = 0
CMD_TYPE_RESPONSE = 1
CMD_TYPE_PUSH = 2
CMD_TYPE_PUSH_ACK = 3
CMD_AUTH_BIND = "auth-bind"
CMD_PING = "ping"
MODULE_CONN_ACCESS = "conn_access"
BIZ_MODULE = "yuanbao_openclaw_proxy"
BIZ_CMD_SEND_C2C = "send_c2c_message"
BIZ_CMD_SEND_GROUP = "send_group_message"
BIZ_CMD_GET_MEMBERS = "get_group_member_list"
BIZ_CMD_QUERY_GROUP_INFO = "query_group_info"


class SimpleProtobufCodec:
    """简化版 Protobuf 编解码器"""

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
    def encode_tim_image_elem(url: str, uuid: str = "", width: int = 0, height: int = 0, image_format: int = 255) -> bytes:
        """编码 TIMImageElem 图片消息元素"""
        # image_info_array
        image_info = b''
        image_info += bytes([(1 << 3) | 0]) + SimpleProtobufCodec.encode_varint(1)  # type=1
        image_info += SimpleProtobufCodec.encode_string(2, url)  # url
        image_info += bytes([(3 << 3) | 0]) + SimpleProtobufCodec.encode_varint(width)  # width
        image_info += bytes([(4 << 3) | 0]) + SimpleProtobufCodec.encode_varint(height)  # height
        
        msg_content = b''
        if uuid:
            msg_content += SimpleProtobufCodec.encode_string(1, uuid)
        msg_content += bytes([(3 << 3) | 0]) + SimpleProtobufCodec.encode_varint(image_format)  # image_format
        msg_content += SimpleProtobufCodec.encode_message_field(8, image_info)  # image_info_array
        
        elem = b''
        elem += SimpleProtobufCodec.encode_string(1, "TIMImageElem")
        elem += SimpleProtobufCodec.encode_message_field(2, msg_content)
        return elem

    @staticmethod
    def encode_tim_face_elem(sticker_id: str, package_id: str, name: str,
                              width: int = 128, height: int = 128, formats: str = "png") -> bytes:
        """编码 TIMFaceElem 贴纸消息元素"""
        data_json = json.dumps({
            "sticker_id": sticker_id,
            "package_id": package_id,
            "width": width,
            "height": height,
            "formats": formats,
            "name": name,
        }, ensure_ascii=False)
        msg_content = b''
        msg_content += bytes([(9 << 3) | 0]) + SimpleProtobufCodec.encode_varint(0)  # index=0
        msg_content += SimpleProtobufCodec.encode_string(4, data_json)  # data=JSON
        elem = b''
        elem += SimpleProtobufCodec.encode_string(1, "TIMFaceElem")
        elem += SimpleProtobufCodec.encode_message_field(2, msg_content)
        return elem

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
    def encode_auth_bind_req(biz_id: str, uid: str, source: str, token: str) -> bytes:
        data = b''
        data += SimpleProtobufCodec.encode_string(1, biz_id)
        auth_info = b''
        auth_info += SimpleProtobufCodec.encode_string(1, uid)
        auth_info += SimpleProtobufCodec.encode_string(2, source)
        auth_info += SimpleProtobufCodec.encode_string(3, token)
        data += SimpleProtobufCodec.encode_message_field(2, auth_info)
        return data

    @staticmethod
    def encode_send_group_msg_req(msg_id: str, group_code: str, from_account: str, text: str, ref_msg_id: str = "") -> bytes:
        """编码 SendGroupMessageReq，支持消息引用 (refMsgId)"""
        data = b''
        data += SimpleProtobufCodec.encode_string(1, msg_id)
        data += SimpleProtobufCodec.encode_string(2, group_code)
        data += SimpleProtobufCodec.encode_string(3, from_account)
        data += SimpleProtobufCodec.encode_string(5, str(random.randint(1, 999999999)))

        msg_content = SimpleProtobufCodec.encode_string(1, text)
        msg_body_elem = SimpleProtobufCodec.encode_string(1, "TIMTextElem")
        msg_body_elem += SimpleProtobufCodec.encode_message_field(2, msg_content)
        data += SimpleProtobufCodec.encode_message_field(6, msg_body_elem)

        # field 7: refMsgId - 引用消息的 ID
        if ref_msg_id:
            data += SimpleProtobufCodec.encode_string(7, ref_msg_id)

        return data

    @staticmethod
    def encode_send_c2c_msg_req(msg_id: str, to_account: str, from_account: str, text: str) -> bytes:
        """编码 SendC2CMessageReq"""
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
        """编码 GetGroupMemberListReq"""
        data = b''
        data += SimpleProtobufCodec.encode_string(1, group_code)
        return data

    @staticmethod
    def decode_get_group_member_list_rsp(data: bytes) -> dict:
        """解码 GetGroupMemberListRsp"""
        result = {"code": 0, "message": "", "member_list": []}
        i = 0
        while i < len(data):
            if i >= len(data):
                break
            tag = data[i]
            i += 1
            field_num = tag >> 3
            wire_type = tag & 7

            if wire_type == 0:  # varint
                value = 0
                shift = 0
                while True:
                    if i >= len(data):
                        break
                    byte = data[i]
                    i += 1
                    value |= (byte & 0x7f) << shift
                    if not (byte & 0x80):
                        break
                    shift += 7
                if field_num == 1:
                    result["code"] = value
            elif wire_type == 2:  # length-delimited
                length = 0
                shift = 0
                while True:
                    if i >= len(data):
                        break
                    byte = data[i]
                    i += 1
                    length |= (byte & 0x7f) << shift
                    if not (byte & 0x80):
                        break
                    shift += 7
                field_data = data[i:i+length]
                i += length
                if field_num == 2:  # message
                    result["message"] = field_data.decode('utf-8', errors='replace')
                elif field_num == 3:  # memberList (repeated Member)
                    member = SimpleProtobufCodec._decode_member(field_data)
                    if member:
                        result["member_list"].append(member)
        return result

    @staticmethod
    def _decode_member(data: bytes) -> Optional[dict]:
        """解码单个 Member 消息"""
        member = {}
        i = 0
        while i < len(data):
            if i >= len(data):
                break
            tag = data[i]
            i += 1
            field_num = tag >> 3
            wire_type = tag & 7

            if wire_type == 0:  # varint
                value = 0
                shift = 0
                while True:
                    if i >= len(data):
                        break
                    byte = data[i]
                    i += 1
                    value |= (byte & 0x7f) << shift
                    if not (byte & 0x80):
                        break
                    shift += 7
                if field_num == 3:  # userType
                    member["user_type"] = value
            elif wire_type == 2:  # length-delimited
                length = 0
                shift = 0
                while True:
                    if i >= len(data):
                        break
                    byte = data[i]
                    i += 1
                    length |= (byte & 0x7f) << shift
                    if not (byte & 0x80):
                        break
                    shift += 7
                field_data = data[i:i+length]
                i += length
                if field_num == 1:  # userId
                    member["user_id"] = field_data.decode('utf-8', errors='replace')
                elif field_num == 2:  # nickName
                    member["nick_name"] = field_data.decode('utf-8', errors='replace')
        return member if member else None

    @staticmethod
    def decode_varint(data: bytes, pos: int) -> tuple:
        """解码 varint，返回 (value, new_pos)"""
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
    def decode_inbound_message_push(data: bytes) -> Optional[dict]:
        """解码 InboundMessagePush - 收到的消息"""
        result = {}
        pos = 0
        
        while pos < len(data):
            if pos >= len(data):
                break
            tag = data[pos]
            pos += 1
            field_num = tag >> 3
            wire_type = tag & 0x07
            
            if field_num == 1 and wire_type == 2:  # callbackCommand
                length, pos = SimpleProtobufCodec.decode_varint(data, pos)
                result['callbackCommand'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 2 and wire_type == 2:  # fromAccount
                length, pos = SimpleProtobufCodec.decode_varint(data, pos)
                result['fromAccount'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 3 and wire_type == 2:  # toAccount
                length, pos = SimpleProtobufCodec.decode_varint(data, pos)
                result['toAccount'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 4 and wire_type == 2:  # senderNickname
                length, pos = SimpleProtobufCodec.decode_varint(data, pos)
                result['senderNickname'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 5 and wire_type == 2:  # groupCode
                length, pos = SimpleProtobufCodec.decode_varint(data, pos)
                result['groupCode'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 6 and wire_type == 2:  # groupName
                length, pos = SimpleProtobufCodec.decode_varint(data, pos)
                result['groupName'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 9 and wire_type == 0:  # msgTime
                result['msgTime'], pos = SimpleProtobufCodec.decode_varint(data, pos)
            elif field_num == 11 and wire_type == 2:  # msgId
                length, pos = SimpleProtobufCodec.decode_varint(data, pos)
                result['msgId'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 12 and wire_type == 2:  # msgBody
                length, pos = SimpleProtobufCodec.decode_varint(data, pos)
                msg_body_data = data[pos:pos+length]
                pos += length
                try:
                    text = SimpleProtobufCodec._extract_text_from_msg_body(msg_body_data)
                    if text:
                        result['text'] = text
                except:
                    pass
            else:
                if wire_type == 0:
                    _, pos = SimpleProtobufCodec.decode_varint(data, pos)
                elif wire_type == 2:
                    length, pos = SimpleProtobufCodec.decode_varint(data, pos)
                    pos += length
                else:
                    break
        
        return result

    @staticmethod
    def _extract_text_from_msg_body(data: bytes) -> Optional[str]:
        """从 MsgBodyElement 中提取文本"""
        pos = 0
        text = None
        
        while pos < len(data):
            if pos >= len(data):
                break
            tag = data[pos]
            pos += 1
            field_num = tag >> 3
            wire_type = tag & 0x07
            
            if field_num == 2 and wire_type == 2:  # msgContent
                length, pos = SimpleProtobufCodec.decode_varint(data, pos)
                content_data = data[pos:pos+length]
                pos += length
                cpos = 0
                while cpos < len(content_data):
                    if cpos >= len(content_data):
                        break
                    ctag = content_data[cpos]
                    cpos += 1
                    cfield = ctag >> 3
                    cwire = ctag & 0x07
                    
                    if cfield == 1 and cwire == 2:  # text
                        tlen, cpos = SimpleProtobufCodec.decode_varint(content_data, cpos)
                        text = content_data[cpos:cpos+tlen].decode('utf-8')
                        cpos += tlen
                        return text
                    elif cwire == 0:
                        _, cpos = SimpleProtobufCodec.decode_varint(content_data, cpos)
                    elif cwire == 2:
                        tlen, cpos = SimpleProtobufCodec.decode_varint(content_data, cpos)
                        cpos += tlen
                    else:
                        break
            elif wire_type == 0:
                _, pos = SimpleProtobufCodec.decode_varint(data, pos)
            elif wire_type == 2:
                length, pos = SimpleProtobufCodec.decode_varint(data, pos)
                pos += length
            else:
                break
        
        return text

    @staticmethod
    def decode_conn_msg(data: bytes) -> Optional[dict]:
        """解码 ConnMsg，返回 {head: dict, data: bytes} 或 None"""
        result = {"head": {"cmd_type": 0}, "data": b""}
        i = 0
        while i < len(data):
            if i >= len(data):
                break
            tag = data[i]
            i += 1
            field_num = tag >> 3
            wire_type = tag & 7
            if wire_type != 2:
                break
            length = 0
            shift = 0
            while True:
                if i >= len(data):
                    break
                byte = data[i]
                i += 1
                length |= (byte & 0x7f) << shift
                if not (byte & 0x80):
                    break
                shift += 7
            field_data = data[i:i+length]
            i += length
            if field_num == 1:  # head
                result["head"] = SimpleProtobufCodec.decode_head(field_data)
            elif field_num == 2:  # data
                result["data"] = field_data
        return result

    @staticmethod
    def decode_head(data: bytes) -> dict:
        """解码 Head 消息，proto3 默认值不编码，cmd_type=0 可能缺失"""
        head = {"cmd_type": 0}  # proto3 默认值
        i = 0
        while i < len(data):
            if i >= len(data):
                break
            tag = data[i]
            i += 1
            field_num = tag >> 3
            wire_type = tag & 7

            if wire_type == 0:  # varint
                value = 0
                shift = 0
                while True:
                    if i >= len(data):
                        break
                    byte = data[i]
                    i += 1
                    value |= (byte & 0x7f) << shift
                    if not (byte & 0x80):
                        break
                    shift += 7
                if field_num == 1:
                    head["cmd_type"] = value
                elif field_num == 3:
                    head["seq_no"] = value
                elif field_num == 10:
                    head["status"] = value
            elif wire_type == 2:  # length-delimited
                length = 0
                shift = 0
                while True:
                    if i >= len(data):
                        break
                    byte = data[i]
                    i += 1
                    length |= (byte & 0x7f) << shift
                    if not (byte & 0x80):
                        break
                    shift += 7
                field_data = data[i:i+length]
                i += length
                if field_num == 2:  # cmd
                    head["cmd"] = field_data.decode('utf-8', errors='replace')
                elif field_num == 4:  # msgId
                    head["msg_id"] = field_data.decode('utf-8', errors='replace')
                elif field_num == 5:  # module
                    head["module"] = field_data.decode('utf-8', errors='replace')
        return head


class SpamSender:
    """刷屏+艾特 增强发送器"""

    def __init__(self):
        self.token: Optional[str] = None
        self.bot_id: Optional[str] = None
        self.ws = None
        self.connected = False
        self.seq_no = 0
        self.group_code: Optional[str] = None
        self.codec = SimpleProtobufCodec()
        # 用户数据库: {user_id: nickname}
        self.user_db: Dict[str, str] = {}
        # 待处理请求: {msg_id: asyncio.Future}
        self.pending_requests: Dict[str, asyncio.Future] = {}
        # 消息缓存: 存储收到的消息，最多保留1000条
        self.msg_cache: List[dict] = []

    # 内置贴纸数据
    STICKERS = {
        "六六六": {"sticker_id": "278", "package_id": "1003", "name": "六六六", "width": 128, "height": 128, "formats": "png"},
        "我想开了": {"sticker_id": "262", "package_id": "1003", "name": "我想开了", "width": 128, "height": 128, "formats": "png"},
        "害羞": {"sticker_id": "130", "package_id": "1003", "name": "害羞", "width": 128, "height": 128, "formats": "png"},
        "比心": {"sticker_id": "252", "package_id": "1003", "name": "比心", "width": 128, "height": 128, "formats": "png"},
        "委屈": {"sticker_id": "125", "package_id": "1003", "name": "委屈", "width": 128, "height": 128, "formats": "png"},
        "亲亲": {"sticker_id": "146", "package_id": "1003", "name": "亲亲", "width": 128, "height": 128, "formats": "png"},
        "酷": {"sticker_id": "131", "package_id": "1003", "name": "酷", "width": 128, "height": 128, "formats": "png"},
        "睡": {"sticker_id": "145", "package_id": "1003", "name": "睡", "width": 128, "height": 128, "formats": "png"},
        "发呆": {"sticker_id": "152", "package_id": "1003", "name": "发呆", "width": 128, "height": 128, "formats": "png"},
        "可怜": {"sticker_id": "157", "package_id": "1003", "name": "可怜", "width": 128, "height": 128, "formats": "png"},
        "摊手": {"sticker_id": "200", "package_id": "1003", "name": "摊手", "width": 128, "height": 128, "formats": "png"},
        "头大": {"sticker_id": "213", "package_id": "1003", "name": "头大", "width": 128, "height": 128, "formats": "png"},
        "吓": {"sticker_id": "256", "package_id": "1003", "name": "吓", "width": 128, "height": 128, "formats": "png"},
        "吐血": {"sticker_id": "203", "package_id": "1003", "name": "吐血", "width": 128, "height": 128, "formats": "png"},
        "哼": {"sticker_id": "185", "package_id": "1003", "name": "哼", "width": 128, "height": 128, "formats": "png"},
        "嘿嘿": {"sticker_id": "220", "package_id": "1003", "name": "嘿嘿", "width": 128, "height": 128, "formats": "png"},
        "头秃": {"sticker_id": "218", "package_id": "1003", "name": "头秃", "width": 128, "height": 128, "formats": "png"},
        "暗中观察": {"sticker_id": "221", "package_id": "1003", "name": "暗中观察", "width": 128, "height": 128, "formats": "png"},
        "我酸了": {"sticker_id": "224", "package_id": "1003", "name": "我酸了", "width": 128, "height": 128, "formats": "png"},
        "打call": {"sticker_id": "246", "package_id": "1003", "name": "打call", "width": 128, "height": 128, "formats": "png"},
        "庆祝": {"sticker_id": "251", "package_id": "1003", "name": "庆祝", "width": 128, "height": 128, "formats": "png"},
        "奋斗": {"sticker_id": "151", "package_id": "1003", "name": "奋斗", "width": 128, "height": 128, "formats": "png"},
        "惊讶": {"sticker_id": "143", "package_id": "1003", "name": "惊讶", "width": 128, "height": 128, "formats": "png"},
        "疑问": {"sticker_id": "144", "package_id": "1003", "name": "疑问", "width": 128, "height": 128, "formats": "png"},
        "仔细分析": {"sticker_id": "248", "package_id": "1003", "name": "仔细分析", "width": 128, "height": 128, "formats": "png"},
        "撅嘴": {"sticker_id": "184", "package_id": "1003", "name": "撅嘴", "width": 128, "height": 128, "formats": "png"},
        "泪奔": {"sticker_id": "199", "package_id": "1003", "name": "泪奔", "width": 128, "height": 128, "formats": "png"},
        "尊嘟假嘟": {"sticker_id": "276", "package_id": "1003", "name": "尊嘟假嘟", "width": 128, "height": 128, "formats": "png"},
        "略略略": {"sticker_id": "113", "package_id": "1003", "name": "略略略", "width": 128, "height": 128, "formats": "png"},
        "困": {"sticker_id": "180", "package_id": "1003", "name": "困", "width": 128, "height": 128, "formats": "png"},
        "折磨": {"sticker_id": "181", "package_id": "1003", "name": "折磨", "width": 128, "height": 128, "formats": "png"},
        "抠鼻": {"sticker_id": "182", "package_id": "1003", "name": "抠鼻", "width": 128, "height": 128, "formats": "png"},
        "鼓掌": {"sticker_id": "183", "package_id": "1003", "name": "鼓掌", "width": 128, "height": 128, "formats": "png"},
        "斜眼笑": {"sticker_id": "204", "package_id": "1003", "name": "斜眼笑", "width": 128, "height": 128, "formats": "png"},
        "辣眼睛": {"sticker_id": "216", "package_id": "1003", "name": "辣眼睛", "width": 128, "height": 128, "formats": "png"},
        "哦哟": {"sticker_id": "217", "package_id": "1003", "name": "哦哟", "width": 128, "height": 128, "formats": "png"},
        "吃瓜": {"sticker_id": "222", "package_id": "1003", "name": "吃瓜", "width": 128, "height": 128, "formats": "png"},
        "狗头": {"sticker_id": "225", "package_id": "1003", "name": "狗头", "width": 128, "height": 128, "formats": "png"},
        "敬礼": {"sticker_id": "227", "package_id": "1003", "name": "敬礼", "width": 128, "height": 128, "formats": "png"},
        "哦": {"sticker_id": "231", "package_id": "1003", "name": "哦", "width": 128, "height": 128, "formats": "png"},
        "拿到红包": {"sticker_id": "236", "package_id": "1003", "name": "拿到红包", "width": 128, "height": 128, "formats": "png"},
        "牛吖": {"sticker_id": "239", "package_id": "1003", "name": "牛吖", "width": 128, "height": 128, "formats": "png"},
        "贴贴": {"sticker_id": "272", "package_id": "1003", "name": "贴贴", "width": 128, "height": 128, "formats": "png"},
        "爱心": {"sticker_id": "138", "package_id": "1003", "name": "爱心", "width": 128, "height": 128, "formats": "png"},
        "晚安": {"sticker_id": "170", "package_id": "1003", "name": "晚安", "width": 128, "height": 128, "formats": "png"},
        "太阳": {"sticker_id": "176", "package_id": "1003", "name": "太阳", "width": 128, "height": 128, "formats": "png"},
        "柠檬": {"sticker_id": "266", "package_id": "1003", "name": "柠檬", "width": 128, "height": 128, "formats": "png"},
        "大冤种": {"sticker_id": "267", "package_id": "1003", "name": "大冤种", "width": 128, "height": 128, "formats": "png"},
        "吐了": {"sticker_id": "132", "package_id": "1003", "name": "吐了", "width": 128, "height": 128, "formats": "png"},
        "怒": {"sticker_id": "134", "package_id": "1003", "name": "怒", "width": 128, "height": 128, "formats": "png"},
        "玫瑰": {"sticker_id": "165", "package_id": "1003", "name": "玫瑰", "width": 128, "height": 128, "formats": "png"},
        "凋谢": {"sticker_id": "119", "package_id": "1003", "name": "凋谢", "width": 128, "height": 128, "formats": "png"},
        "点赞": {"sticker_id": "159", "package_id": "1003", "name": "点赞", "width": 128, "height": 128, "formats": "png"},
        "握手": {"sticker_id": "164", "package_id": "1003", "name": "握手", "width": 128, "height": 128, "formats": "png"},
        "抱拳": {"sticker_id": "163", "package_id": "1003", "name": "抱拳", "width": 128, "height": 128, "formats": "png"},
        "ok": {"sticker_id": "169", "package_id": "1003", "name": "ok", "width": 128, "height": 128, "formats": "png"},
        "拳头": {"sticker_id": "174", "package_id": "1003", "name": "拳头", "width": 128, "height": 128, "formats": "png"},
        "鞭炮": {"sticker_id": "191", "package_id": "1003", "name": "鞭炮", "width": 128, "height": 128, "formats": "png"},
        "烟花": {"sticker_id": "258", "package_id": "1003", "name": "烟花", "width": 128, "height": 128, "formats": "png"},
    }

    def _generate_msg_id(self) -> str:
        import uuid
        return uuid.uuid4().hex

    def _get_beijing_time(self) -> str:
        from datetime import timezone
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
                print(f"签票成功! Bot ID: {self.bot_id}")
                return True
            else:
                print(f"签票失败: {result}")
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
            print("WebSocket 连接成功!")
            asyncio.create_task(self._heartbeat())
            return True
        except Exception as e:
            print(f"连接失败: {e}")
            return False

    def _build_auth_bind_msg(self) -> bytes:
        auth_data = self.codec.encode_auth_bind_req(
            biz_id="ybBot", uid=self.bot_id or "", source="web", token=self.token or ""
        )
        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST, cmd=CMD_AUTH_BIND, seq_no=self.seq_no,
            msg_id=self._generate_msg_id(), module=MODULE_CONN_ACCESS
        )
        self.seq_no += 1
        return self.codec.encode_conn_msg(head, auth_data)

    def _build_sticker_msg(self, sticker_name: str) -> bytes:
        """构建贴纸群消息"""
        sticker = self.STICKERS.get(sticker_name)
        if not sticker:
            return b''
        face_elem = self.codec.encode_tim_face_elem(
            sticker["sticker_id"], sticker["package_id"], sticker["name"],
            sticker["width"], sticker["height"], sticker["formats"]
        )
        data = b''
        data += self.codec.encode_string(1, self._generate_msg_id())
        data += self.codec.encode_string(2, self.group_code)
        data += self.codec.encode_string(3, self.bot_id or "")
        data += self.codec.encode_string(5, str(random.randint(1, 999999999)))
        data += self.codec.encode_message_field(6, face_elem)

        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_SEND_GROUP, seq_no=self.seq_no,
            msg_id=self._generate_msg_id(), module=BIZ_MODULE
        )
        self.seq_no += 1
        return self.codec.encode_conn_msg(head, data)

    def _build_sticker_with_text_msg(self, sticker_name: str, text: str) -> bytes:
        """构建贴纸+文本的群消息"""
        sticker = self.STICKERS.get(sticker_name)
        if not sticker:
            return b''
        face_elem = self.codec.encode_tim_face_elem(
            sticker["sticker_id"], sticker["package_id"], sticker["name"],
            sticker["width"], sticker["height"], sticker["formats"]
        )
        text_content = self.codec.encode_string(1, text)
        text_elem = b''
        text_elem += self.codec.encode_string(1, "TIMTextElem")
        text_elem += self.codec.encode_message_field(2, text_content)

        data = b''
        data += self.codec.encode_string(1, self._generate_msg_id())
        data += self.codec.encode_string(2, self.group_code)
        data += self.codec.encode_string(3, self.bot_id or "")
        data += self.codec.encode_string(5, str(random.randint(1, 999999999)))
        data += self.codec.encode_message_field(6, face_elem)
        data += self.codec.encode_message_field(6, text_elem)

        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_SEND_GROUP, seq_no=self.seq_no,
            msg_id=self._generate_msg_id(), module=BIZ_MODULE
        )
        self.seq_no += 1
        return self.codec.encode_conn_msg(head, data)

    def _build_sticker_with_at_msg(self, sticker_name: str, text: str, at_user_id: str, at_nickname: str = "") -> bytes:
        """构建贴纸+艾特+文本的群消息"""
        sticker = self.STICKERS.get(sticker_name)
        if not sticker:
            return b''
        display_name = at_nickname or at_user_id

        # TIMCustomElem (艾特)
        at_data = json.dumps({"elem_type": 1002, "text": f"@{display_name}", "user_id": at_user_id})
        at_content = self.codec.encode_string(4, at_data)
        at_elem = b''
        at_elem += self.codec.encode_string(1, "TIMCustomElem")
        at_elem += self.codec.encode_message_field(2, at_content)

        # TIMFaceElem (贴纸)
        face_elem = self.codec.encode_tim_face_elem(
            sticker["sticker_id"], sticker["package_id"], sticker["name"],
            sticker["width"], sticker["height"], sticker["formats"]
        )

        # TIMTextElem (文本)
        text_content = self.codec.encode_string(1, text)
        text_elem = b''
        text_elem += self.codec.encode_string(1, "TIMTextElem")
        text_elem += self.codec.encode_message_field(2, text_content)

        data = b''
        data += self.codec.encode_string(1, self._generate_msg_id())
        data += self.codec.encode_string(2, self.group_code)
        data += self.codec.encode_string(3, self.bot_id or "")
        data += self.codec.encode_string(5, str(random.randint(1, 999999999)))
        data += self.codec.encode_message_field(6, at_elem)
        data += self.codec.encode_message_field(6, face_elem)
        data += self.codec.encode_message_field(6, text_elem)

        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_SEND_GROUP, seq_no=self.seq_no,
            msg_id=self._generate_msg_id(), module=BIZ_MODULE
        )
        self.seq_no += 1
        return self.codec.encode_conn_msg(head, data)

    def _build_group_msg(self, text: str) -> bytes:
        biz_data = self.codec.encode_send_group_msg_req(
            msg_id=self._generate_msg_id(), group_code=self.group_code,
            from_account=self.bot_id or "", text=text
        )
        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_SEND_GROUP, seq_no=self.seq_no,
            msg_id=self._generate_msg_id(), module=BIZ_MODULE
        )
        self.seq_no += 1
        return self.codec.encode_conn_msg(head, biz_data)

    def _build_at_message(self, text: str, at_user_id: str, at_nickname: str = "") -> bytes:
        """构建带艾特的群消息 - TIMCustomElem(艾特) + TIMTextElem(文本)"""
        display_name = at_nickname or at_user_id

        # TIMCustomElem (艾特)
        at_data = json.dumps({
            "elem_type": 1002,
            "text": f"@{display_name}",
            "user_id": at_user_id
        })
        at_content = self.codec.encode_string(4, at_data)
        at_elem = b''
        at_elem += self.codec.encode_string(1, "TIMCustomElem")
        at_elem += self.codec.encode_message_field(2, at_content)

        # TIMTextElem (消息文本)
        text_content = self.codec.encode_string(1, text)
        text_elem = b''
        text_elem += self.codec.encode_string(1, "TIMTextElem")
        text_elem += self.codec.encode_message_field(2, text_content)

        # SendGroupMessageReq
        data = b''
        data += self.codec.encode_string(1, self._generate_msg_id())
        data += self.codec.encode_string(2, self.group_code)
        data += self.codec.encode_string(3, self.bot_id or "")
        data += self.codec.encode_string(5, str(random.randint(1, 999999999)))
        data += self.codec.encode_message_field(6, at_elem)
        data += self.codec.encode_message_field(6, text_elem)

        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_SEND_GROUP, seq_no=self.seq_no,
            msg_id=self._generate_msg_id(), module=BIZ_MODULE
        )
        self.seq_no += 1
        return self.codec.encode_conn_msg(head, data)

    def _build_reply_msg(self, text: str, ref_msg_id: str, at_user_id: str = "", at_nickname: str = "") -> bytes:
        """构建带引用的群消息，可选同时艾特"""
        # 如果有艾特，先构建艾特元素
        if at_user_id:
            display_name = at_nickname or at_user_id
            at_data = json.dumps({
                "elem_type": 1002,
                "text": f"@{display_name}",
                "user_id": at_user_id
            })
            at_content = self.codec.encode_string(4, at_data)
            at_elem = b''
            at_elem += self.codec.encode_string(1, "TIMCustomElem")
            at_elem += self.codec.encode_message_field(2, at_content)

            text_content = self.codec.encode_string(1, text)
            text_elem = b''
            text_elem += self.codec.encode_string(1, "TIMTextElem")
            text_elem += self.codec.encode_message_field(2, text_content)

            data = b''
            data += self.codec.encode_string(1, self._generate_msg_id())
            data += self.codec.encode_string(2, self.group_code)
            data += self.codec.encode_string(3, self.bot_id or "")
            data += self.codec.encode_string(5, str(random.randint(1, 999999999)))
            data += self.codec.encode_message_field(6, at_elem)
            data += self.codec.encode_message_field(6, text_elem)
            data += self.codec.encode_string(7, ref_msg_id)  # 引用消息ID
        else:
            # 纯引用消息（无艾特）
            biz_data = self.codec.encode_send_group_msg_req(
                msg_id=self._generate_msg_id(), group_code=self.group_code,
                from_account=self.bot_id or "", text=text, ref_msg_id=ref_msg_id
            )
            data = biz_data

        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_SEND_GROUP, seq_no=self.seq_no,

                    msg_id=self._generate_msg_id(), module=BIZ_MODULE
        )
        self.seq_no += 1
        return self.codec.encode_conn_msg(head, data)



    def _get_upload_info(self, filename: str, file_id: str) -> Optional[dict]:
        """获取图片上传凭证"""
        url = f"https://{API_DOMAIN}/api/resource/genUploadInfo"
        headers = {
            "Content-Type": "application/json",
            "X-AppVersion": "1.0.11",
            "X-OperationSystem": "linux",
            "X-Instance-Id": str(random.randint(1, 1000)),
            "X-Bot-Version": "2026.3.22"
        }
        body = {
            "fileName": filename,
            "fileId": file_id,
            "docFrom": "localDoc",
            "docOpenId": ""
        }
        try:
            response = requests.post(url, headers=headers, json=body, timeout=30)
            result = response.json()
            if result.get("code") == 0:
                return result.get("data")
            else:
                print(f"获取上传凭证失败: {result}")
                return None
        except Exception as e:
            print(f"获取上传凭证错误: {e}")
            return None

    def _upload_to_cos(self, config: dict, data: bytes, filename: str) -> Optional[str]:
        """上传图片到腾讯云 COS"""
        import base64
        import hashlib
        import time
        from datetime import datetime
        
        # COS 签名
        secret_id = config.get("encryptTmpSecretId", "")
        secret_key = config.get("encryptTmpSecretKey", "")
        security_token = config.get("encryptToken", "")
        start_time = config.get("startTime", 0)
        expired_time = config.get("expiredTime", 0)
        
        bucket = config.get("bucketName", "")
        region = config.get("region", "")
        location = config.get("location", "")
        
        # 构建签名
        key_time = f"{start_time};{expired_time}"
        sign_key = hmac.new(secret_key.encode(), key_time.encode(), hashlib.sha1).hexdigest()
        
        http_string = f"put\n{location}\n\nhost={bucket}.cos.{region}.myqcloud.com\n"
        string_to_sign = f"sha1\n{key_time}\n{hashlib.sha1(http_string.encode()).hexdigest()}\n"
        signature = hmac.new(sign_key.encode(), string_to_sign.encode(), hashlib.sha1).hexdigest()
        
        authorization = f"q-sign-algorithm=sha1&q-ak={secret_id}&q-sign-time={key_time}&q-key-time={key_time}&q-header-list=host&q-url-param-list=&q-signature={signature}"
        
        if security_token:
            authorization += f"&x-cos-security-token={security_token}"
        
        # 上传 URL
        upload_url = f"https://{bucket}.cos.{region}.myqcloud.com{location}"
        
        headers = {
            "Host": f"{bucket}.cos.{region}.myqcloud.com",
            "Authorization": authorization,
            "Content-Type": "image/jpeg",
        }
        if security_token:
            headers["x-cos-security-token"] = security_token
        
        try:
            response = requests.put(upload_url, headers=headers, data=data, timeout=60)
            if response.status_code == 200:
                return config.get("resourceUrl", upload_url)
            else:
                print(f"上传失败: {response.status_code} {response.text[:200]}")
                return None
        except Exception as e:
            print(f"上传错误: {e}")
            return None

    def _build_image_msg(self, url: str, uuid: str = "", width: int = 0, height: int = 0) -> bytes:
        """构建图片群消息"""
        image_elem = self.codec.encode_tim_image_elem(url, uuid, width, height)
        
        data = b''
        data += self.codec.encode_string(1, self._generate_msg_id())
        data += self.codec.encode_string(2, self.group_code)
        data += self.codec.encode_string(3, self.bot_id or "")
        data += self.codec.encode_string(5, str(random.randint(1, 999999999)))
        data += self.codec.encode_message_field(6, image_elem)
        
        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_SEND_GROUP, seq_no=self.seq_no,
            msg_id=self._generate_msg_id(), module=BIZ_MODULE
        )
        self.seq_no += 1
        return self.codec.encode_conn_msg(head, data)

    async def send_image(self, image_path: str) -> bool:
        """发送图片消息"""
        if not self.connected or not self.ws:
            return False
        
        import os
        import uuid
        
        # 检查文件是否存在
        if not os.path.exists(image_path):
            print(f"图片文件不存在: {image_path}")
            return False
        
        # 读取图片
        try:
            with open(image_path, 'rb') as f:
                data = f.read()
        except Exception as e:
            print(f"读取图片失败: {e}")
            return False
        
        # 检查大小（默认最大 20MB）
        max_bytes = 20 * 1024 * 1024
        if len(data) > max_bytes:
            print(f"图片过大: {len(data) / 1024 / 1024:.1f} MB > 20 MB")
            return False
        
        # 获取上传凭证
        filename = os.path.basename(image_path)
        file_id = uuid.uuid4().hex
        config = self._get_upload_info(filename, file_id)
        if not config:
            return False
        
        # 上传图片
        url = self._upload_to_cos(config, data, filename)
        if not url:
            return False
        
        # 发送图片消息
        try:
            msg = self._build_image_msg(url, file_id)
            await self.ws.send(msg)
            print(f"图片已发送: {url}")
            return True
        except Exception as e:
            print(f"发送失败: {e}")
            return False

    def _build_multi_at_message(self, text: str, at_users: list) -> bytes:
        """构建批量艾特的群消息 - 多个 TIMCustomElem(艾特) + TIMTextElem(文本)
        at_users: [(user_id, nickname), ...]
        """
        data = b''
        data += self.codec.encode_string(1, self._generate_msg_id())
        data += self.codec.encode_string(2, self.group_code)
        data += self.codec.encode_string(3, self.bot_id or "")
        data += self.codec.encode_string(5, str(random.randint(1, 999999999)))

        # 构建多个艾特元素
        for user_id, nickname in at_users:
            display_name = nickname or user_id
            at_data = json.dumps({
                "elem_type": 1002,
                "text": f"@{display_name}",
                "user_id": user_id
            })
            at_content = self.codec.encode_string(4, at_data)
            at_elem = b''
            at_elem += self.codec.encode_string(1, "TIMCustomElem")
            at_elem += self.codec.encode_message_field(2, at_content)
            data += self.codec.encode_message_field(6, at_elem)

        # TIMTextElem (消息文本)
        text_content = self.codec.encode_string(1, text)
        text_elem = b''
        text_elem += self.codec.encode_string(1, "TIMTextElem")
        text_elem += self.codec.encode_message_field(2, text_content)
        data += self.codec.encode_message_field(6, text_elem)

        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_SEND_GROUP, seq_no=self.seq_no,
            msg_id=self._generate_msg_id(), module=BIZ_MODULE
        )
        self.seq_no += 1
        return self.codec.encode_conn_msg(head, data)

    def _build_dm_msg(self, to_account: str, text: str) -> bytes:
        """构建私聊消息 - SendC2CMessageReq"""
        biz_data = self.codec.encode_send_c2c_msg_req(
            msg_id=self._generate_msg_id(), to_account=to_account,
            from_account=self.bot_id or "", text=text
        )
        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_SEND_C2C, seq_no=self.seq_no,
            msg_id=self._generate_msg_id(), module=BIZ_MODULE
        )
        self.seq_no += 1
        return self.codec.encode_conn_msg(head, biz_data)

    def _build_get_members_msg(self) -> bytes:
        """构建获取群成员列表请求 - GetGroupMemberListReq"""
        msg_id = self._generate_msg_id()
        biz_data = self.codec.encode_get_group_member_list_req(self.group_code or "")
        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_GET_MEMBERS, seq_no=self.seq_no,
            msg_id=msg_id, module=BIZ_MODULE
        )
        self.seq_no += 1
        return msg_id, self.codec.encode_conn_msg(head, biz_data)

    async def send_get_members_request(self) -> Optional[dict]:
        """发送获取群成员列表请求，等待响应"""
        if not self.connected or not self.ws:
            return None
        try:
            msg_id, msg = self._build_get_members_msg()
            future = asyncio.get_event_loop().create_future()
            self.pending_requests[msg_id] = future
            await self.ws.send(msg)
            # 等待响应，30秒超时
            try:
                result = await asyncio.wait_for(future, timeout=30)
                return result
            except asyncio.TimeoutError:
                self.pending_requests.pop(msg_id, None)
                print("获取群成员列表超时")
                return None
        except Exception as e:
            print(f"获取群成员列表失败: {e}")
            return None

    async def send_dm_message(self, to_account: str, text: str) -> bool:
        """发送私聊消息"""
        if not self.connected or not self.ws:
            return False
        try:
            msg = self._build_dm_msg(to_account, text)
            await self.ws.send(msg)
            return True
        except Exception:
            return False

    async def send_group_message(self, text: str, at_user: str = None, at_nickname: str = None) -> bool:
        if not self.connected or not self.ws:
            return False
        try:
            if at_user:
                msg = self._build_at_message(text, at_user, at_nickname)
            else:
                msg = self._build_group_msg(text)
            await self.ws.send(msg)
            return True
        except Exception as e:
            return False


    async def send_multi_at_message(self, text: str, at_users: list) -> bool:
        """发送批量艾特消息
        at_users: [(user_id, nickname), ...]
        """
        if not self.connected or not self.ws:
            return False
        try:
            msg = self._build_multi_at_message(text, at_users)
            await self.ws.send(msg)
            return True
        except Exception:
            return False

    async def send_sticker_message(self, sticker_name: str, text: str = "",
                                    at_user: str = None, at_nickname: str = None) -> bool:
        """发送贴纸消息，支持纯贴纸、贴纸+文本、贴纸+艾特+文本"""
        if not self.connected or not self.ws:
            return False
        if sticker_name not in self.STICKERS:
            return False
        try:
            if at_user:
                msg = self._build_sticker_with_at_msg(sticker_name, text, at_user, at_nickname)
            elif text:
                msg = self._build_sticker_with_text_msg(sticker_name, text)
            else:
                msg = self._build_sticker_msg(sticker_name)
            await self.ws.send(msg)
            return True
        except Exception:
            return False

    async def spam_with_at(self, text: str, count: int, at_user: str = None, at_nickname: str = None,
                           interval: float = 1.0, progress_callback=None):
        """刷屏+艾特核心功能"""
        success_count = 0
        fail_count = 0
        for i in range(count):
            ok = await self.send_group_message(text, at_user, at_nickname)
            if ok:
                success_count += 1
            else:
                fail_count += 1
            if progress_callback:
                progress_callback(i + 1, count, ok)
            if i < count - 1:
                await asyncio.sleep(interval)
        return success_count, fail_count

    async def _heartbeat(self):
        while self.connected:
            await asyncio.sleep(70)
            if not self.connected:
                break
            try:
                head = self.codec.encode_head(
                    cmd_type=CMD_TYPE_REQUEST, cmd=CMD_PING, seq_no=self.seq_no,
                    msg_id=self._generate_msg_id(), module=MODULE_CONN_ACCESS
                )
                self.seq_no += 1
                ping_msg = self.codec.encode_conn_msg(head)
                await self.ws.send(ping_msg)
            except:
                break

    async def _receive_loop(self):
        """接收循环：处理响应消息，匹配 pending_requests"""
        print("[DEBUG] _receive_loop 已启动")
        try:
            while self.connected and self.ws:
                print("[DEBUG] _receive_loop 等待 recv...")
                raw = await self.ws.recv()
                print(f"[DEBUG] _receive_loop 收到数据: type={type(raw).__name__}, len={len(raw) if isinstance(raw, bytes) else 'N/A'}")
                if isinstance(raw, bytes):
                    print(f"[DEBUG] 收到 {len(raw)} 字节")
                    conn_msg = self.codec.decode_conn_msg(raw)
                    if not conn_msg:
                        print(f"[DEBUG] decode_conn_msg 返回 None")
                        continue
                    head = conn_msg.get("head", {})
                    cmd_type = head.get("cmd_type")
                    cmd = head.get("cmd", "")
                    msg_id = head.get("msg_id")
                    status = head.get("status", 0)
                    print(f"[DEBUG] head: cmd_type={cmd_type}, cmd={cmd}, msg_id={msg_id}, status={status}")
                    print(f"[DEBUG] pending_requests keys: {list(self.pending_requests.keys())}")
                    # 处理 Push 类型的消息（收到的消息推送）
                    if cmd_type == CMD_TYPE_PUSH:
                        biz_data = conn_msg.get("data", b"")
                        print(f"[DEBUG PUSH] cmd={cmd!r}, biz_data_len={len(biz_data)}, biz_data[:100]={biz_data[:100]!r}")
                        if cmd == "inbound_message" and biz_data:
                            try:
                                push_json = json.loads(biz_data)
                                # 从 msg_body 中提取文本内容（JSON 格式）
                                text_content = ""
                                msg_body = push_json.get("msg_body", [])
                                if msg_body and len(msg_body) > 0:
                                    for elem in msg_body:
                                        msg_type = elem.get("msg_type", "")
                                        msg_content = elem.get("msg_content", {})
                                        if msg_type == "TIMTextElem":
                                            text_content += msg_content.get("text", "")
                                        elif msg_type == "TIMCustomElem":
                                            # 艾特消息
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
                                # 只保留最近 1000 条
                                if len(self.msg_cache) > 1000:
                                    self.msg_cache = self.msg_cache[-1000:]
                            except (json.JSONDecodeError, Exception):
                                pass
                        continue
                    # 处理 Response 类型的消息
                    if cmd_type == CMD_TYPE_RESPONSE and msg_id and msg_id in self.pending_requests:
                        future = self.pending_requests.pop(msg_id)
                        biz_data = conn_msg.get("data", b"")
                        print(f"[DEBUG] 匹配到 pending request! cmd={cmd}, biz_data_len={len(biz_data)}")
                        if cmd == BIZ_CMD_GET_MEMBERS and biz_data:
                            result = self.codec.decode_get_group_member_list_rsp(biz_data)
                            if result:
                                result["msg_id"] = msg_id
                                print(f"[DEBUG] 解码成功: code={result.get('code')}, members={len(result.get('member_list', []))}")
                                future.set_result(result)
                            else:
                                print(f"[DEBUG] 解码失败")
                                future.set_result({"msg_id": msg_id, "code": -1, "message": "解码失败", "member_list": []})
                        elif status != 0:
                            print(f"[DEBUG] 响应状态异常: {status}")
                            future.set_result({"msg_id": msg_id, "code": status, "message": "FAIL", "member_list": []})
                        else:
                            print(f"[DEBUG] 未知命令或无数据: cmd={cmd}")
                            future.set_result({"msg_id": msg_id, "code": 0, "message": "", "member_list": []})
        except Exception as e:
            print(f"[DEBUG] _receive_loop 异常: {e}")

    async def disconnect(self):
        self.connected = False
        if self.ws:
            await self.ws.close()


def print_banner():
    print("=" * 56)
    print("  元宝 Bot 刷屏+艾特 增强发送器")
    print("=" * 56)
    print()


def print_help():
    print("命令列表:")
    print("  <文字>            - 发送普通消息")
    print("  /at 用户ID 内容   - 艾特指定用户发送")
    print("  /spam 内容 次数   - 普通刷屏")
    print("  /sticker_spam 贴纸名 次数 - 贴纸刷屏")
    print("  /atspam 用户ID 内容 次数  - 艾特+刷屏（核心功能）")
    print("  /multiat 用户ID1,ID2,... 内容 - 批量艾特多人")
    print("  /atall 内容      - 艾特全体成员（慎用！）")
    print("  /image 图片路径  - 发送图片（需绝对路径）")
    print("  /spamat 用户ID 内容 次数  - 同上，艾特+刷屏")
    print("  /reply 序号 内容  - 引用最近消息列表中第N条消息回复")
    print("  /reply 序号 @用户ID 内容  - 引用+艾特回复")
    print("  /replyspam 序号 内容 次数 - 引用刷屏")
    print("  /group 群号       - 切换目标群")
    print("  /interval 秒      - 设置刷屏间隔（默认1秒）")
    print("  /users            - 查看已保存的用户列表")
    print("  /adduser 用户ID 昵称 - 添加常用用户")
    print("  /deluser 用户ID   - 删除用户")
    print("  /sticker 贴纸名   - 发送贴纸")
    print("  /sticker 贴纸名 文字 - 发送贴纸+文字")
    print("  /sticker 贴纸名 @用户ID 文字 - 发送贴纸+艾特+文字")
    print("  /stickerlist      - 查看所有可用贴纸")
    print("  /stickerfind 关键词 - 搜索贴纸")
    print("  /dm 用户ID 内容   - 发送私聊消息")
    print("  /dmspam 用户ID 内容 次数 - 私聊刷屏")
    print("  /members          - 获取当前群成员列表")
    print("  /myid 昵称        - 在成员列表中搜索自己的ID（填你的群昵称）")
    print("  /recent [N]       - 查看最近 N 条消息（默认10条）")
    print("  /help             - 显示帮助")
    print("  /exit             - 退出")
    print()


async def interactive_mode():
    sender = SpamSender()
    print_banner()

    # 输入群号
    group_code = await async_input("请输入群号: ")
    group_code = group_code.strip()
    if not group_code:
        print("群号不能为空")
        return
    sender.group_code = group_code
    print(f"目标群: {group_code}")
    print("正在连接...")

    if not await sender.connect():
        print("连接失败，退出")
        return

    # 刷屏间隔（秒）
    spam_interval = 1.0

    print("\n" + "-" * 56)
    print_help()

    asyncio.create_task(sender._receive_loop())

    while sender.connected:
        try:
            raw = await async_input("> ")
            raw = raw.strip()
            if not raw:
                continue

            # 退出
            if raw == "/exit":
                print("再见!")
                break

            # 帮助
            if raw == "/help":
                print_help()
                continue

            # 切换目标群
            if raw.startswith("/group "):
                new_group = raw[7:].strip()
                if new_group:
                    sender.group_code = new_group
                    print(f"目标群已切换为: {new_group}")
                else:
                    print(f"当前目标群: {sender.group_code}")
                continue

            # 查看用户列表
            if raw == "/users":
                if sender.user_db:
                    print(f"已保存的用户 ({len(sender.user_db)}):")
                    for uid, nick in sender.user_db.items():
                        print(f"  {uid} -> {nick}")
                else:
                    print("用户列表为空，使用 /adduser 添加")
                continue

            # 添加用户
            if raw.startswith("/adduser "):
                parts = raw[9:].split(" ", 1)
                if len(parts) == 2:
                    uid, nick = parts
                    sender.user_db[uid] = nick
                    print(f"已添加: {nick} ({uid})")
                else:
                    print("格式: /adduser 用户ID 昵称")
                continue

            # 删除用户
            if raw.startswith("/deluser "):
                uid = raw[9:].strip()
                if uid in sender.user_db:
                    nick = sender.user_db.pop(uid)
                    print(f"已删除: {nick} ({uid})")
                else:
                    print(f"未找到用户: {uid}")
                continue

            # 设置刷屏间隔
            if raw.startswith("/interval "):
                try:
                    spam_interval = float(raw[10:].strip())
                    print(f"刷屏间隔已设为 {spam_interval} 秒")
                except ValueError:
                    print("格式: /interval 秒数")
                continue

            # ===== 贴纸命令 =====
            # 搜索贴纸
            if raw.startswith("/stickerfind "):
                keyword = raw[13:].strip().lower()
                results = [(k, v) for k, v in sender.STICKERS.items() if keyword in k.lower() or keyword in v["name"].lower()]
                if results:
                    print(f"找到 {len(results)} 个贴纸:")
                    for name, _ in results:
                        print(f"  {name}")
                else:
                    print(f"未找到包含 '{keyword}' 的贴纸")
                continue

            # 列出所有贴纸
            if raw == "/stickerlist":
                names = sorted(sender.STICKERS.keys(), key=lambda x: len(x))
                print(f"内置贴纸 ({len(sender.STICKERS)} 个):")
                for i, name in enumerate(names, 1):
                    print(f"  {i:2d}. {name}")
                continue

            # 发送贴纸
            # 格式1: /sticker 贴纸名
            # 格式2: /sticker 贴纸名 文字
            # 格式3: /sticker 贴纸名 @用户ID 文字
            if raw.startswith("/sticker "):
                rest = raw[9:].strip()
                if not rest:
                    print("格式: /sticker 贴纸名 或 /sticker 贴纸名 @用户ID 文字")
                    continue

                # 尝试匹配贴纸名（支持模糊匹配）
                parts = rest.split(" ", 2)
                sticker_name = parts[0]
                matched = None
                # 精确匹配
                if sticker_name in sender.STICKERS:
                    matched = sticker_name
                else:
                    # 模糊匹配
                    for name in sender.STICKERS:
                        if sticker_name in name or name in sticker_name:
                            matched = name
                            break
                if not matched:
                    print(f"未找到贴纸 '{sticker_name}'，使用 /stickerlist 查看所有贴纸")
                    continue

                if len(parts) == 1:
                    # 纯贴纸
                    if await sender.send_sticker_message(matched):
                        print(f"贴纸已发送: {matched}")
                    else:
                        print("发送失败")
                elif len(parts) == 2:
                    # 贴纸+文字
                    text = parts[1]
                    if await sender.send_sticker_message(matched, text=text):
                        print(f"贴纸+文字已发送: {matched} + {text[:30]}")
                    else:
                        print("发送失败")
                elif len(parts) == 3 and parts[1].startswith("@"):
                    # 贴纸+艾特+文字
                    at_user = parts[1][1:]
                    text = parts[2]
                    at_nick = sender.user_db.get(at_user, at_user)
                    if await sender.send_sticker_message(matched, text=text, at_user=at_user, at_nickname=at_nick):
                        print(f"贴纸+艾特已发送: {matched} @{at_nick}")
                    else:
                        print("发送失败")
                else:
                    print("格式: /sticker 贴纸名 或 /sticker 贴纸名 @用户ID 文字")
                continue

            # ===== 核心功能: 艾特+刷屏 =====
            # 格式1: /atspam 用户ID 内容 次数
            # 格式2: /spamat 用户ID 内容 次数
            if raw.startswith("/atspam ") or raw.startswith("/spamat "):
                prefix_len = 8 if raw.startswith("/atspam ") else 8
                rest = raw[prefix_len:]

                # 从右往左分割，最后一个空格后是次数
                *parts, count_str = rest.rsplit(" ", 2) if rest.count(" ") >= 2 else ["", "", ""]
                if len(parts) == 2 and count_str.isdigit():
                    at_user, content = parts
                    count = int(count_str)
                    at_nick = sender.user_db.get(at_user, at_user)

                    print(f"\n===== 艾特刷屏 =====")
                    print(f"  艾特用户: {at_nick} ({at_user})")
                    print(f"  消息内容: {content}")
                    print(f"  发送次数: {count}")
                    print(f"  发送间隔: {spam_interval}秒")
                    print(f"  按 Ctrl+C 随时停止")
                    print("=" * 22)

                    def make_progress(start_time):
                        def cb(current, total, ok):
                            elapsed = datetime.now() - start_time
                            status = "OK" if ok else "FAIL"
                            print(f"  [{current}/{total}] {status}  ({elapsed.seconds}s)")
                        return cb

                    start = datetime.now()
                    success, failed = await sender.spam_with_at(
                        text=content.replace("\\n", "\n"),
                        count=count,
                        at_user=at_user,
                        at_nickname=at_nick,
                        interval=spam_interval,
                        progress_callback=make_progress(start)
                    )
                    elapsed = (datetime.now() - start).seconds
                    print(f"\n完成! 成功={success}, 失败={failed}, 耗时={elapsed}秒")
                else:
                    print("格式: /atspam 用户ID 内容 次数")
                continue

            # 普通艾特
            if raw.startswith("/at "):
                parts = raw[4:].split(" ", 1)
                if len(parts) == 2:
                    at_user, message = parts
                    at_nick = sender.user_db.get(at_user, at_user)
                    message = message.replace("\\n", "\n")
                    if await sender.send_group_message(message, at_user, at_nick):
                        print(f"艾特消息已发送 -> @{at_nick}")
                    else:
                        print("发送失败")
                else:
                    print("格式: /at 用户ID 消息内容")
                continue

            # 普通刷屏（纯文字）
            if raw.startswith("/spam "):
                parts = raw[6:].rsplit(" ", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    content, count = parts[0], int(parts[1])
                    content = content.replace("\\n", "\n")
                    print(f"刷屏: 发送 {count} 次, 间隔 {spam_interval}秒")
                    success, failed = await sender.spam_with_at(
                        text=content, count=count, interval=spam_interval,
                        progress_callback=lambda c, t, o: print(f"  [{c}/{t}] {'OK' if o else 'FAIL'}")
                    )
                    print(f"完成! 成功={success}, 失败={failed}")
                else:
                    print("格式: /spam 内容 次数")
                continue

            # 贴纸刷屏
            if raw.startswith("/sticker_spam "):
                parts = raw[14:].rsplit(" ", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    sticker_name, count = parts[0], int(parts[1])
                    if sticker_name not in sender.STICKERS:
                        print(f"未找到贴纸 '{sticker_name}'，使用 /stickerlist 查看所有贴纸")
                        continue
                    print(f"贴纸刷屏: '{sticker_name}' {count} 次, 间隔 {spam_interval}秒")
                    success, failed = 0, 0
                    for i in range(count):
                        ok = await sender.send_sticker_message(sticker_name)
                        if ok:
                            success += 1
                        else:
                            failed += 1
                        print(f"  [{i+1}/{count}] {'OK' if ok else 'FAIL'}")
                        if i < count - 1:
                            await asyncio.sleep(spam_interval)
                    print(f"完成! 成功={success}, 失败={failed}")
                else:
                    print("格式: /sticker_spam 贴纸名 次数")
                continue

            # ===== 发送图片 =====
            # 格式: /image 图片绝对路径
            if raw.startswith("/image "):
                image_path = raw[7:].strip()
                if image_path:
                    print(f"正在发送图片: {image_path}")
                    if await sender.send_image(image_path):
                        print("图片发送成功!")
                    else:
                        print("图片发送失败")
                else:
                    print("格式: /image 图片绝对路径")
                continue

            # ===== 批量艾特 =====
            # 格式: /multiat 用户ID1,用户ID2,... 内容 或 /multiat @用户ID1,@用户ID2,... 内容
            if raw.startswith("/multiat "):
                rest = raw[9:].strip()
                parts = rest.split(" ", 1)
                if len(parts) == 2:
                    users_str, message = parts
                    # 解析用户列表（支持逗号分隔）
                    user_ids = []
                    for uid in users_str.split(","):
                        uid = uid.strip()
                        if uid.startswith("@"):
                            uid = uid[1:]
                        if uid:
                            nick = sender.user_db.get(uid, uid)
                            user_ids.append((uid, nick))
                    if user_ids:
                        message = message.replace("\n", "\n")
                        if await sender.send_multi_at_message(message, user_ids):
                            names = ", ".join([f"@{n[1]}" for n in user_ids])
                            print(f"批量艾特已发送 -> {names}")
                        else:
                            print("发送失败")
                    else:
                        print("格式: /multiat 用户ID1,用户ID2,... 消息内容")
                else:
                    print("格式: /multiat 用户ID1,用户ID2,... 消息内容")
                continue

            # ===== 艾特全体成员 =====
            # 格式: /atall 内容
            if raw.startswith("/atall "):
                message = raw[7:].strip().replace("\n", "\n")
                # 获取群成员列表
                result = await sender.send_get_members_request()
                if result and result.get("code") == 0:
                    member_list = result.get("member_list", [])
                    # 过滤掉 Bot 自己
                    at_users = []
                    for m in member_list:
                        uid = m.get("user_id", "")
                        nick = m.get("nick_name", "")
                        utype = m.get("user_type", 0)
                        if uid != sender.bot_id and utype != 3:  # 不艾特自己和其他 Bot
                            at_users.append((uid, nick))
                    if at_users:
                        print(f"正在艾特 {len(at_users)} 位成员...")
                        if await sender.send_multi_at_message(message, at_users):
                            print(f"艾特全体成员已发送!")
                        else:
                            print("发送失败")
                    else:
                        print("没有可艾特的成员")
                else:
                    print("获取成员列表失败")
                continue

            # ===== 获取群成员列表 =====
            if raw == "/members":
                print("正在获取群成员列表...")
                result = await sender.send_get_members_request()
                if result and result.get("code") == 0:
                    member_list = result.get("member_list", [])
                    print(f"\n群成员列表 (共 {len(member_list)} 人):")
                    print("-" * 56)
                    for i, m in enumerate(member_list, 1):
                        uid = m.get("user_id", "")
                        nick = m.get("nick_name", "")
                        utype = m.get("user_type", 0)
                        utype_str = {1: "成员", 2: "管理员", 3: "Bot"}.get(utype, f"未知({utype})")
                        print(f"  {i:3d}. {nick} ({uid}) [{utype_str}]")
                        # 自动保存到用户数据库
                        if uid and uid not in sender.user_db and nick:
                            sender.user_db[uid] = nick
                    print("-" * 56)
                    print(f"共 {len(member_list)} 名成员，已自动保存昵称到用户数据库")
                elif result:
                    print(f"获取失败: code={result.get('code')}, {result.get('message', '')}")
                else:
                    print("获取失败（无响应）")
                continue

            # ===== 搜索自己的ID =====
            if raw.startswith("/myid "):
                nickname = raw[6:].strip()
                if not nickname:
                    print("格式: /myid 你的群昵称")
                    continue
                print(f"正在获取群成员列表，搜索昵称 '{nickname}'...")
                result = await sender.send_get_members_request()
                if result and result.get("code") == 0:
                    member_list = result.get("member_list", [])
                    found = [m for m in member_list if nickname in m.get("nick_name", "")]
                    if found:
                        print(f"\n找到 {len(found)} 个匹配的成员:")
                        for m in found:
                            print(f"  用户ID: {m['user_id']}")
                            print(f"  昵称:   {m['nick_name']}")
                            print(f"  身份:   {['未知','成员','管理员','Bot'][m.get('user_type',0)] if m.get('user_type',0) in [1,2,3] else '未知'}")
                            print()
                    else:
                        print(f"未找到昵称包含 '{nickname}' 的成员")
                        print("提示: 可以使用 /members 查看所有成员，或输入完整的群昵称")
                elif result:
                    print(f"获取失败: code={result.get('code')}, {result.get('message', '')}")
                else:
                    print("获取失败（无响应）")
                continue

            # ===== 查看最近消息 =====
            if raw == "/recent" or raw.startswith("/recent "):
                if raw == "/recent":
                    n = 10
                else:
                    try:
                        n = int(raw[8:].strip())
                    except ValueError:
                        n = 10
                if n <= 0:
                    print("数量必须大于0")
                    continue
                cache = sender.msg_cache
                if not cache:
                    print("暂无缓存消息（连接后收到的消息才会被缓存）")
                    continue
                recent = cache[-n:]
                total = len(cache)
                print(f"\n最近 {len(recent)} 条消息 (序号用于 /reply 命令):")
                print("-" * 60)
                for i, msg in enumerate(recent):
                    # 序号从缓存末尾开始计算（最新的消息序号最大）
                    seq_num = total - len(recent) + i + 1
                    sender_name = msg.get("sender_name", "?")
                    content = msg.get("content", "")
                    msg_time = msg.get("time", "")
                    group_code = msg.get("group_code", "")
                    # 截断过长内容
                    if len(content) > 60:
                        content = content[:60] + "..."
                    print(f"  [{seq_num:3d}] [{msg_time}] {sender_name}: {content}")
                    if group_code and group_code != sender.group_code:
                        print(f"       (群: {group_code})")
                print("-" * 60)
                print(f"共缓存 {len(cache)} 条消息，使用 /reply 序号 内容 引用回复")
                continue

            # ===== 引用回复 =====
            # 格式: /reply 序号 内容 或 /reply 序号 @用户ID 内容
            if raw.startswith("/reply "):
                rest = raw[7:].strip()
                # 解析参数
                parts = rest.split(" ", 2)
                if len(parts) >= 2:
                    try:
                        idx = int(parts[0]) - 1  # 用户输入的是第N条，转为索引
                    except ValueError:
                        print("格式: /reply 序号 内容 或 /reply 序号 @用户ID 内容")
                        continue
                    
                    cache = sender.msg_cache
                    if idx < 0 or idx >= len(cache):
                        print(f"序号无效，当前缓存 {len(cache)} 条消息，使用 /recent 查看")
                        continue
                    
                    target_msg = cache[idx]
                    ref_msg_id = target_msg.get("msg_id", "")
                    if not ref_msg_id:
                        print("该消息没有 msg_id，无法引用")
                        continue
                    
                    # 判断是否有艾特
                    if len(parts) == 3 and parts[1].startswith("@"):
                        # /reply 序号 @用户ID 内容
                        at_user = parts[1][1:]
                        reply_text = parts[2].replace("\\n", "\n")
                        at_nick = sender.user_db.get(at_user, at_user)
                    elif len(parts) == 2:
                        # /reply 序号 内容
                        at_user = ""
                        reply_text = parts[1].replace("\\n", "\n")
                        at_nick = ""
                    else:
                        print("格式: /reply 序号 内容 或 /reply 序号 @用户ID 内容")
                        continue
                    
                    sender_name = target_msg.get("sender_name", "")
                    sender_id = target_msg.get("sender_id", "")
                    print(f"\n===== 引用回复 =====")
                    print(f"  引用消息: [{target_msg.get('time')}] {sender_name}: {target_msg.get('content', '')[:50]}")
                    print(f"  引用ID: {ref_msg_id}")
                    if at_user:
                        print(f"  艾特用户: {at_nick} ({at_user})")
                    print(f"  回复内容: {reply_text[:50]}")
                    print("=" * 22)
                    
                    # 构建引用消息
                    msg = sender._build_reply_msg(reply_text, ref_msg_id, at_user, at_nick)
                    try:
                        await sender.ws.send(msg)
                        print("引用消息已发送")
                    except Exception as e:
                        print(f"发送失败: {e}")
                else:
                    print("格式: /reply 序号 内容 或 /reply 序号 @用户ID 内容")
                continue

            # ===== 引用刷屏 =====
            # 格式: /replyspam 序号 内容 次数
            if raw.startswith("/replyspam "):
                rest = raw[11:].strip()
                # 从右往左分割，最后一个空格后是次数
                *parts, count_str = rest.rsplit(" ", 1)
                if len(parts) >= 2 and count_str.isdigit():
                    idx_str = parts[0]
                    reply_text = " ".join(parts[1:])
                    try:
                        idx = int(idx_str) - 1
                    except ValueError:
                        print("格式: /replyspam 序号 内容 次数")
                        continue
                    
                    count = int(count_str)
                    cache = sender.msg_cache
                    if idx < 0 or idx >= len(cache):
                        print(f"序号无效，当前缓存 {len(cache)} 条消息，使用 /recent 查看")
                        continue
                    
                    target_msg = cache[idx]
                    ref_msg_id = target_msg.get("msg_id", "")
                    if not ref_msg_id:
                        print("该消息没有 msg_id，无法引用")
                        continue
                    
                    reply_text = reply_text.replace("\\n", "\n")
                    sender_name = target_msg.get("sender_name", "")
                    
                    print(f"\n===== 引用刷屏 =====")
                    print(f"  引用消息: [{target_msg.get('time')}] {sender_name}: {target_msg.get('content', '')[:50]}")
                    print(f"  引用ID: {ref_msg_id}")
                    print(f"  回复内容: {reply_text[:50]}")
                    print(f"  发送次数: {count}")
                    print(f"  发送间隔: {spam_interval}秒")
                    print(f"  按 Ctrl+C 随时停止")
                    print("=" * 22)
                    
                    success, failed = 0, 0
                    for i in range(count):
                        msg = sender._build_reply_msg(reply_text, ref_msg_id)
                        try:
                            await sender.ws.send(msg)
                            success += 1
                            print(f"  [{i+1}/{count}] OK")
                        except Exception as e:
                            failed += 1
                            print(f"  [{i+1}/{count}] FAIL: {e}")
                        if i < count - 1:
                            await asyncio.sleep(spam_interval)
                    print(f"\n完成! 成功={success}, 失败={failed}")
                else:
                    print("格式: /replyspam 序号 内容 次数")
                continue

            # ===== 私聊刷屏 =====
            if raw.startswith("/dmspam "):
                rest = raw[8:].strip()
                *parts, count_str = rest.rsplit(" ", 2) if rest.count(" ") >= 2 else ["", "", ""]
                if len(parts) == 2 and count_str.isdigit():
                    to_user, content = parts
                    count = int(count_str)
                    content = content.replace("\\n", "\n")
                    print(f"\n===== 私聊刷屏 =====")
                    print(f"  目标用户: {to_user}")
                    print(f"  消息内容: {content}")
                    print(f"  发送次数: {count}")
                    print(f"  发送间隔: {spam_interval}秒")
                    print(f"  按 Ctrl+C 随时停止")
                    print("=" * 22)
                    success, failed = 0, 0
                    for i in range(count):
                        ok = await sender.send_dm_message(to_user, content)
                        if ok:
                            success += 1
                        else:
                            failed += 1
                        print(f"  [{i+1}/{count}] {'OK' if ok else 'FAIL'}")
                        if i < count - 1:
                            await asyncio.sleep(spam_interval)
                    print(f"\n完成! 成功={success}, 失败={failed}")
                else:
                    print("格式: /dmspam 用户ID 内容 次数")
                continue

            # 私聊消息
            if raw.startswith("/dm "):
                parts = raw[4:].strip().split(" ", 1)
                if len(parts) == 2:
                    to_user, message = parts
                    message = message.replace("\\n", "\n")
                    if await sender.send_dm_message(to_user, message):
                        print(f"私聊已发送 -> {to_user}: {message[:50]}")
                    else:
                        print("发送失败")
                else:
                    print("格式: /dm 用户ID 消息内容")
                continue

            # 普通消息
            message = raw.replace("\\n", "\n")
            if await sender.send_group_message(message):
                print(f"已发送: {message[:50]}")
            else:
                print("发送失败")

        except KeyboardInterrupt:
            print("\n已停止")
            break
        except Exception as e:
            print(f"错误: {e}")

    await sender.disconnect()


async def main():
    try:
        await interactive_mode()
    except Exception as e:
        print(f"程序错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
