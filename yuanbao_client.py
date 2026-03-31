#!/usr/bin/env python3
"""
元宝 Bot WebSocket 客户端
基于 OpenClaw 插件逆向工程
"""

import asyncio
import json
import hashlib
import hmac
import random
import string
import struct
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional, Callable, Dict, Any
import requests
import websockets

# 配置 - 替换为你的元宝 Bot 凭证
# Token 格式: appKey:appSecret
APP_KEY = ""
APP_SECRET = ""
API_DOMAIN = "bot.yuanbao.tencent.com"
WS_URL = "wss://bot-wss.yuanbao.tencent.com/wss/connection"

# 协议常量
CMD_TYPE_REQUEST = 0
CMD_TYPE_RESPONSE = 1
CMD_TYPE_PUSH = 2
CMD_TYPE_PUSH_ACK = 3

CMD_AUTH_BIND = "auth-bind"
CMD_PING = "ping"
CMD_KICKOUT = "kickout"
MODULE_CONN_ACCESS = "conn_access"

BIZ_MODULE = "yuanbao_openclaw_proxy"
BIZ_CMD_SEND_C2C = "send_c2c_message"
BIZ_CMD_SEND_GROUP = "send_group_message"

class YuanbaoProtobufCodec:
    """简化的 Protobuf 编解码器"""
    
    @staticmethod
    def encode_varint(value: int) -> bytes:
        """编码变长整数"""
        result = []
        while value > 127:
            result.append((value & 0x7f) | 0x80)
            value >>= 7
        result.append(value)
        return bytes(result)
    
    @staticmethod
    def decode_varint(data: bytes, pos: int = 0) -> tuple:
        """解码变长整数，返回 (值, 新位置)"""
        result = 0
        shift = 0
        while True:
            byte = data[pos]
            pos += 1
            result |= (byte & 0x7f) << shift
            if not (byte & 0x80):
                break
            shift += 7
        return result, pos
    
    @staticmethod
    def encode_string(field_num: int, value: str) -> bytes:
        """编码字符串字段 (wire type 2)"""
        tag = (field_num << 3) | 2  # wire type 2 = length-delimited
        encoded = value.encode('utf-8')
        return bytes([tag]) + YuanbaoProtobufCodec.encode_varint(len(encoded)) + encoded
    
    @staticmethod
    def encode_bytes(field_num: int, value: bytes) -> bytes:
        """编码字节字段 (wire type 2)"""
        tag = (field_num << 3) | 2
        return bytes([tag]) + YuanbaoProtobufCodec.encode_varint(len(value)) + value
    
    @staticmethod
    def encode_uint32(field_num: int, value: int) -> bytes:
        """编码 uint32 字段 (wire type 0)"""
        tag = (field_num << 3) | 0  # wire type 0 = varint
        return bytes([tag]) + YuanbaoProtobufCodec.encode_varint(value)
    
    @staticmethod
    def encode_message_field(field_num: int, encoded_msg: bytes) -> bytes:
        """编码嵌套消息字段"""
        tag = (field_num << 3) | 2
        return bytes([tag]) + YuanbaoProtobufCodec.encode_varint(len(encoded_msg)) + encoded_msg
    
    @staticmethod
    def encode_head(cmd_type: int, cmd: str, seq_no: int, msg_id: str, module: str, need_ack: bool = False) -> bytes:
        """编码消息头"""
        data = b''
        data += YuanbaoProtobufCodec.encode_uint32(1, cmd_type)
        data += YuanbaoProtobufCodec.encode_string(2, cmd)
        data += YuanbaoProtobufCodec.encode_uint32(3, seq_no)
        data += YuanbaoProtobufCodec.encode_string(4, msg_id)
        data += YuanbaoProtobufCodec.encode_string(5, module)
        if need_ack:
            data += bytes([48, 1])  # field 6, bool true
        return data
    
    @staticmethod
    def encode_conn_msg(head: bytes, data: bytes = b'') -> bytes:
        """编码 ConnMsg"""
        result = b''
        # head field (1)
        result += YuanbaoProtobufCodec.encode_message_field(1, head)
        # data field (2)
        if data:
            result += YuanbaoProtobufCodec.encode_bytes(2, data)
        return result
    
    @staticmethod
    def encode_auth_bind_req(biz_id: str, uid: str, source: str, token: str,
                            app_version: str, os: str, bot_version: str, instance_id: str = "16") -> bytes:
        """编码 AuthBindReq - 只发送 bizId 和 authInfo"""
        data = b''
        # bizId (field 1)
        data += YuanbaoProtobufCodec.encode_string(1, biz_id)

        # authInfo (field 2) - 必需
        auth_info = b''
        auth_info += YuanbaoProtobufCodec.encode_string(1, uid)      # uid
        auth_info += YuanbaoProtobufCodec.encode_string(2, source)   # source
        auth_info += YuanbaoProtobufCodec.encode_string(3, token)    # token
        data += YuanbaoProtobufCodec.encode_message_field(2, auth_info)

        # 不发送 deviceInfo - 之前的测试证明这样可以避免 protobuf 编码错误

        return data
    
    @staticmethod
    def encode_ping_req() -> bytes:
        """编码 PingReq (空消息)"""
        return b''
    
    @staticmethod
    def decode_conn_msg(data: bytes) -> Dict[str, Any]:
        """解码 ConnMsg"""
        result = {'head': {}, 'data': b''}
        pos = 0
        
        while pos < len(data):
            tag = data[pos]
            pos += 1
            field_num = tag >> 3
            wire_type = tag & 0x07
            
            if field_num == 1 and wire_type == 2:  # head
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                head_data = data[pos:pos+length]
                pos += length
                result['head'] = YuanbaoProtobufCodec.decode_head(head_data)
            elif field_num == 2 and wire_type == 2:  # data
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['data'] = data[pos:pos+length]
                pos += length
            else:
                # 跳过未知字段
                if wire_type == 0:  # varint
                    _, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                elif wire_type == 2:  # length-delimited
                    length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                    pos += length
                else:
                    break
        
        return result
    
    @staticmethod
    def decode_head(data: bytes) -> Dict[str, Any]:
        """解码 Head"""
        result = {}
        pos = 0
        
        while pos < len(data):
            tag = data[pos]
            pos += 1
            field_num = tag >> 3
            wire_type = tag & 0x07
            
            if field_num == 1 and wire_type == 0:  # cmdType
                result['cmdType'], pos = YuanbaoProtobufCodec.decode_varint(data, pos)
            elif field_num == 2 and wire_type == 2:  # cmd
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['cmd'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 3 and wire_type == 0:  # seqNo
                result['seqNo'], pos = YuanbaoProtobufCodec.decode_varint(data, pos)
            elif field_num == 4 and wire_type == 2:  # msgId
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['msgId'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 5 and wire_type == 2:  # module
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['module'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 6 and wire_type == 0:  # needAck
                val, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['needAck'] = bool(val)
            elif field_num == 10 and wire_type == 0:  # status
                val, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['status'] = val
            else:
                if wire_type == 0:
                    _, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                elif wire_type == 2:
                    length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                    pos += length
                else:
                    break
        
        return result
    
    @staticmethod
    def decode_auth_bind_rsp(data: bytes) -> Dict[str, Any]:
        """解码 AuthBindRsp"""
        result = {}
        pos = 0
        
        while pos < len(data):
            tag = data[pos]
            pos += 1
            field_num = tag >> 3
            wire_type = tag & 0x07
            
            if field_num == 1 and wire_type == 0:  # code
                val, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['code'] = val
            elif field_num == 2 and wire_type == 2:  # message
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['message'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 3 and wire_type == 2:  # connectId
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['connectId'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 4 and wire_type == 0:  # timestamp
                result['timestamp'], pos = YuanbaoProtobufCodec.decode_varint(data, pos)
            elif field_num == 5 and wire_type == 2:  # clientIp
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['clientIp'] = data[pos:pos+length].decode('utf-8')
                pos += length
            else:
                if wire_type == 0:
                    _, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                elif wire_type == 2:
                    length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                    pos += length
                else:
                    break
        
        return result
    
    @staticmethod
    def decode_ping_rsp(data: bytes) -> Dict[str, Any]:
        """解码 PingRsp"""
        result = {}
        pos = 0
        
        while pos < len(data):
            tag = data[pos]
            pos += 1
            field_num = tag >> 3
            wire_type = tag & 0x07
            
            if field_num == 1 and wire_type == 0:  # heartInterval
                result['heartInterval'], pos = YuanbaoProtobufCodec.decode_varint(data, pos)
            elif field_num == 2 and wire_type == 0:  # timestamp
                result['timestamp'], pos = YuanbaoProtobufCodec.decode_varint(data, pos)
            else:
                if wire_type == 0:
                    _, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                elif wire_type == 2:
                    length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                    pos += length
                else:
                    break
        
        return result
    
    @staticmethod
    def decode_push_msg(data: bytes) -> Dict[str, Any]:
        """解码 PushMsg"""
        result = {}
        pos = 0
        
        while pos < len(data):
            tag = data[pos]
            pos += 1
            field_num = tag >> 3
            wire_type = tag & 0x07
            
            if field_num == 1 and wire_type == 2:  # cmd
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['cmd'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 2 and wire_type == 2:  # module
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['module'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 3 and wire_type == 2:  # msgId
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['msgId'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 4 and wire_type == 2:  # data
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['data'] = data[pos:pos+length]
                pos += length
            else:
                if wire_type == 0:
                    _, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                elif wire_type == 2:
                    length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                    pos += length
                else:
                    break
        
        return result

    @staticmethod
    def encode_send_c2c_message_req(msg_id: str, to_account: str, from_account: str, text: str) -> bytes:
        """编码 SendC2CMessageReq - 发送私聊消息"""
        data = b''
        # msgId (field 1)
        data += YuanbaoProtobufCodec.encode_string(1, msg_id)
        # toAccount (field 2)
        data += YuanbaoProtobufCodec.encode_string(2, to_account)
        # fromAccount (field 3)
        data += YuanbaoProtobufCodec.encode_string(3, from_account)
        # msgRandom (field 4) - 随机数
        data += YuanbaoProtobufCodec.encode_uint32(4, random.randint(1, 4294967295))
        
        # msgBody (field 5) - 消息内容数组
        # MsgBodyElement: msgType + msgContent
        msg_content = b''
        msg_content += YuanbaoProtobufCodec.encode_string(1, text)  # text
        
        msg_body_elem = b''
        msg_body_elem += YuanbaoProtobufCodec.encode_string(1, "TIMTextElem")  # msgType
        msg_body_elem += YuanbaoProtobufCodec.encode_message_field(2, msg_content)  # msgContent
        
        data += YuanbaoProtobufCodec.encode_message_field(5, msg_body_elem)
        
        return data

    @staticmethod
    def encode_send_group_message_req(msg_id: str, group_code: str, from_account: str, text: str) -> bytes:
        """编码 SendGroupMessageReq - 发送群消息"""
        data = b''
        # msgId (field 1)
        data += YuanbaoProtobufCodec.encode_string(1, msg_id)
        # groupCode (field 2)
        data += YuanbaoProtobufCodec.encode_string(2, group_code)
        # fromAccount (field 3)
        data += YuanbaoProtobufCodec.encode_string(3, from_account)
        # random (field 5) - 随机字符串
        data += YuanbaoProtobufCodec.encode_string(5, str(random.randint(1, 999999999)))
        
        # msgBody (field 6) - 消息内容数组
        msg_content = b''
        msg_content += YuanbaoProtobufCodec.encode_string(1, text)  # text
        
        msg_body_elem = b''
        msg_body_elem += YuanbaoProtobufCodec.encode_string(1, "TIMTextElem")  # msgType
        msg_body_elem += YuanbaoProtobufCodec.encode_message_field(2, msg_content)  # msgContent
        
        data += YuanbaoProtobufCodec.encode_message_field(6, msg_body_elem)
        
        return data

    @staticmethod
    def decode_inbound_message_push(data: bytes) -> Dict[str, Any]:
        """解码 InboundMessagePush - 收到的消息"""
        result = {}
        pos = 0
        
        while pos < len(data):
            tag = data[pos]
            pos += 1
            field_num = tag >> 3
            wire_type = tag & 0x07
            
            if field_num == 1 and wire_type == 2:  # callbackCommand
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['callbackCommand'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 2 and wire_type == 2:  # fromAccount
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['fromAccount'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 3 and wire_type == 2:  # toAccount
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['toAccount'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 4 and wire_type == 2:  # senderNickname
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['senderNickname'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 5 and wire_type == 2:  # groupCode
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['groupCode'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 6 and wire_type == 2:  # groupName
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['groupName'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 9 and wire_type == 0:  # msgTime
                result['msgTime'], pos = YuanbaoProtobufCodec.decode_varint(data, pos)
            elif field_num == 11 and wire_type == 2:  # msgId
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                result['msgId'] = data[pos:pos+length].decode('utf-8')
                pos += length
            elif field_num == 12 and wire_type == 2:  # msgBody
                # 简化解码，只获取文本内容
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                msg_body_data = data[pos:pos+length]
                pos += length
                # 尝试提取文本
                try:
                    text = YuanbaoProtobufCodec._extract_text_from_msg_body(msg_body_data)
                    if text:
                        result['text'] = text
                except:
                    pass
            else:
                if wire_type == 0:
                    _, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                elif wire_type == 2:
                    length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
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
            tag = data[pos]
            pos += 1
            field_num = tag >> 3
            wire_type = tag & 0x07
            
            if field_num == 2 and wire_type == 2:  # msgContent
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                content_data = data[pos:pos+length]
                pos += length
                # 从 MsgContent 中提取 text (field 1)
                cpos = 0
                while cpos < len(content_data):
                    ctag = content_data[cpos]
                    cpos += 1
                    cfield = ctag >> 3
                    cwire = ctag & 0x07
                    
                    if cfield == 1 and cwire == 2:  # text
                        tlen, cpos = YuanbaoProtobufCodec.decode_varint(content_data, cpos)
                        text = content_data[cpos:cpos+tlen].decode('utf-8')
                        cpos += tlen
                        return text
                    elif cwire == 0:
                        _, cpos = YuanbaoProtobufCodec.decode_varint(content_data, cpos)
                    elif cwire == 2:
                        tlen, cpos = YuanbaoProtobufCodec.decode_varint(content_data, cpos)
                        cpos += tlen
                    else:
                        break
            elif wire_type == 0:
                _, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
            elif wire_type == 2:
                length, pos = YuanbaoProtobufCodec.decode_varint(data, pos)
                pos += length
            else:
                break
        
        return text


class YuanbaoClient:
    """元宝 Bot WebSocket 客户端"""
    
    def __init__(self, app_key: str, app_secret: str, 
                 api_domain: str = API_DOMAIN,
                 ws_url: str = WS_URL):
        self.app_key = app_key
        self.app_secret = app_secret
        self.api_domain = api_domain
        self.ws_url = ws_url
        self.token: Optional[str] = None
        self.bot_id: Optional[str] = None
        self.ws = None
        self.connected = False
        self.seq_no = 0
        self.connect_id: Optional[str] = None
        self.heartbeat_interval = 5
        self.message_handler: Optional[Callable] = None
        self.codec = YuanbaoProtobufCodec()
    
    def _generate_msg_id(self) -> str:
        """生成消息 ID (UUID 去掉横线)"""
        return uuid.uuid4().hex
    
    def _generate_signature(self, nonce: str, timestamp: str) -> str:
        """生成 HMAC-SHA256 签名"""
        plain = f"{nonce}{timestamp}{self.app_key}{self.app_secret}"
        return hmac.new(
            self.app_secret.encode(),
            plain.encode(),
            hashlib.sha256
        ).hexdigest()
    
    def _generate_nonce(self) -> str:
        """生成 32 字符随机 nonce"""
        return ''.join(random.choices(string.hexdigits.lower(), k=32))
    
    def _get_beijing_time(self) -> str:
        """获取北京时间 ISO 格式 (去掉毫秒，与 JS 代码一致)"""
        from datetime import timezone
        utc = datetime.now(timezone.utc)
        beijing = utc + timedelta(hours=8)
        # 格式: 2026-03-29T14:30:00+08:00 (无毫秒)
        return beijing.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    
    def sign_token(self) -> Dict[str, Any]:
        """签票获取 token"""
        url = f"https://{self.api_domain}/api/v5/robotLogic/sign-token"
        
        nonce = self._generate_nonce()
        timestamp = self._get_beijing_time()
        signature = self._generate_signature(nonce, timestamp)
        
        # 使用随机 instanceId 避免与 OpenClaw 冲突
        self.instance_id = str(random.randint(1, 1000))
        
        headers = {
            "Content-Type": "application/json",
            "X-AppVersion": "1.0.11",
            "X-OperationSystem": "linux",
            "X-Instance-Id": self.instance_id,
            "X-Bot-Version": "2026.3.22"
        }
        
        body = {
            "app_key": self.app_key,
            "nonce": nonce,
            "signature": signature,
            "timestamp": timestamp
        }
        
        print(f"[签票] URL: {url}")
        print(f"[签票] 请求体: {json.dumps(body, indent=2)}")
        
        response = requests.post(url, headers=headers, json=body, timeout=30)
        result = response.json()
        
        print(f"[签票] 响应: {json.dumps(result, indent=2)}")
        
        if result.get("code") == 0:
            data = result["data"]
            self.token = data["token"]
            self.bot_id = data["bot_id"]
            return data
        else:
            raise Exception(f"签票失败: code={result.get('code')}, msg={result.get('msg')}")
    
    def _build_auth_bind_msg(self, msg_id: str) -> bytes:
        """构建鉴权消息"""
        auth_data = self.codec.encode_auth_bind_req(
            biz_id="ybBot",
            uid=self.bot_id or "",
            source="web",  # 签票返回的 source 是 "web"
            token=self.token or "",
            app_version="1.0.11",
            os="linux",
            bot_version="2026.3.22",
            instance_id=self.instance_id
        )
        
        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST,
            cmd=CMD_AUTH_BIND,
            seq_no=self.seq_no,
            msg_id=msg_id,
            module=MODULE_CONN_ACCESS
        )
        self.seq_no += 1
        
        return self.codec.encode_conn_msg(head, auth_data)

    def _build_ping_msg(self, msg_id: str) -> bytes:
        """构建心跳消息"""
        ping_data = self.codec.encode_ping_req()
        
        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST,
            cmd=CMD_PING,
            seq_no=self.seq_no,
            msg_id=msg_id,
            module=MODULE_CONN_ACCESS
        )
        self.seq_no += 1
        
        return self.codec.encode_conn_msg(head, ping_data)

    def _build_send_c2c_msg(self, msg_id: str, to_account: str, text: str) -> bytes:
        """构建发送私聊消息"""
        biz_data = self.codec.encode_send_c2c_message_req(
            msg_id=msg_id,
            to_account=to_account,
            from_account=self.bot_id or "",
            text=text
        )
        
        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST,
            cmd=BIZ_CMD_SEND_C2C,
            seq_no=self.seq_no,
            msg_id=msg_id,
            module=BIZ_MODULE
        )
        self.seq_no += 1
        
        return self.codec.encode_conn_msg(head, biz_data)

    def _build_send_group_msg(self, msg_id: str, group_code: str, text: str) -> bytes:
        """构建发送群消息"""
        biz_data = self.codec.encode_send_group_message_req(
            msg_id=msg_id,
            group_code=group_code,
            from_account=self.bot_id or "",
            text=text
        )
        
        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST,
            cmd=BIZ_CMD_SEND_GROUP,
            seq_no=self.seq_no,
            msg_id=msg_id,
            module=BIZ_MODULE
        )
        self.seq_no += 1
        
        return self.codec.encode_conn_msg(head, biz_data)

    async def send_c2c_message(self, to_account: str, text: str) -> bool:
        """发送私聊消息"""
        if not self.ws or not self.connected:
            print(f"[发送] 失败: 未连接")
            return False
        
        msg_id = self._generate_msg_id()
        msg = self._build_send_c2c_msg(msg_id, to_account, text)
        
        try:
            await self.ws.send(msg)
            print(f"[发送] 私聊消息已发送 -> {to_account}: {text}")
            return True
        except Exception as e:
            print(f"[发送] 失败: {e}")
            return False

    async def send_group_message(self, group_code: str, text: str) -> bool:
        """发送群消息"""
        if not self.ws or not self.connected:
            print(f"[发送] 失败: 未连接")
            return False
        
        msg_id = self._generate_msg_id()
        msg = self._build_send_group_msg(msg_id, group_code, text)
        
        try:
            await self.ws.send(msg)
            print(f"[发送] 群消息已发送 -> {group_code}: {text}")
            return True
        except Exception as e:
            print(f"[发送] 失败: {e}")
            return False

    def _build_push_ack(self, original_head: Dict[str, Any]) -> bytes:
        """构建推送确认消息"""
        ack_head = self.codec.encode_head(
            cmd_type=CMD_TYPE_PUSH_ACK,
            cmd=original_head.get('cmd', ''),
            seq_no=self.seq_no,
            msg_id=original_head.get('msgId', ''),
            module=original_head.get('module', '')
        )
        self.seq_no += 1
        
        return self.codec.encode_conn_msg(ack_head)
    
    def set_message_handler(self, handler: Callable[[Dict[str, Any]], None]):
        """设置消息处理器"""
        self.message_handler = handler
    
    async def connect(self):
        """连接到 WebSocket"""
        if not self.token:
            print("[连接] 先进行签票...")
            self.sign_token()
        
        print(f"[连接] 正在连接到 {self.ws_url}...")
        
        try:
            self.ws = await websockets.connect(self.ws_url)
            print("[连接] WebSocket 已连接")
            
            # 发送鉴权
            auth_msg_id = self._generate_msg_id()
            auth_msg = self._build_auth_bind_msg(auth_msg_id)
            print(f"[鉴权] 发送鉴权消息 (msg_id={auth_msg_id})")
            await self.ws.send(auth_msg)
            
            # 等待鉴权响应
            response = await self.ws.recv()
            conn_msg = self.codec.decode_conn_msg(response)
            head = conn_msg['head']
            
            print(f"[鉴权] 收到响应: cmdType={head.get('cmdType')}, cmd={head.get('cmd')}, status={head.get('status')}")
            
            if head.get('cmd') == CMD_AUTH_BIND:
                auth_rsp = self.codec.decode_auth_bind_rsp(conn_msg['data'])
                code = auth_rsp.get('code')
                # protobuf 中 code=0 时可能不编码，所以 None 也视为成功
                if code is None:
                    code = 0
                print(f"[鉴权] 结果: code={code}, message={auth_rsp.get('message')}")
                
                if code == 0 or code == 41101:  # SUCCESS 或 ALREADY_AUTH
                    self.connect_id = auth_rsp.get('connectId')
                    self.connected = True
                    print(f"[鉴权] 成功! connectId={self.connect_id}")
                    print("=" * 50)
                    print("✅ 元宝 Bot WebSocket 连接成功!")
                    print(f"   Bot ID: {self.bot_id}")
                    print(f"   Connect ID: {self.connect_id}")
                    print("=" * 50)
                    
                    # 启动心跳
                    asyncio.create_task(self._heartbeat_loop())
                    
                    # 启动消息接收循环
                    await self._receive_loop()
                else:
                    raise Exception(f"鉴权失败: {auth_rsp.get('message')}")
            else:
                raise Exception(f"意外的响应: {head}")
                
        except Exception as e:
            print(f"[错误] 连接失败: {e}")
            self.connected = False
            raise
    
    async def _heartbeat_loop(self):
        """心跳循环"""
        print("[心跳] 启动心跳循环")
        while self.connected:
            await asyncio.sleep(self.heartbeat_interval)
            if not self.connected:
                break
            
            try:
                ping_msg_id = self._generate_msg_id()
                ping_msg = self._build_ping_msg(ping_msg_id)
                await self.ws.send(ping_msg)
                print(f"[心跳] Ping 已发送 (msg_id={ping_msg_id})")
            except Exception as e:
                print(f"[心跳] 发送失败: {e}")
                self.connected = False
                break
    
    async def _receive_loop(self):
        """消息接收循环"""
        print("[接收] 启动消息接收循环")
        
        try:
            async for message in self.ws:
                if not self.connected:
                    break
                
                try:
                    print(f"[接收] 原始消息: {message.hex()[:100]}...")
                    conn_msg = self.codec.decode_conn_msg(message)
                    head = conn_msg['head']
                    
                    print(f"[接收] 消息头: cmdType={head.get('cmdType')}, cmd={head.get('cmd')}, module={head.get('module')}, seqNo={head.get('seqNo')}")
                    
                    cmd_type = head.get('cmdType')
                    cmd = head.get('cmd')
                    
                    # 发送 ACK（如果需要）
                    if head.get('needAck'):
                        ack_msg = self._build_push_ack(head)
                        await self.ws.send(ack_msg)
                        print(f"[ACK] 已发送 (cmd={cmd})")
                    
                    if cmd_type == CMD_TYPE_RESPONSE:
                        if cmd == CMD_PING:
                            ping_rsp = self.codec.decode_ping_rsp(conn_msg['data'])
                            print(f"[心跳] Pong 收到: heartInterval={ping_rsp.get('heartInterval')}s")
                        elif cmd == CMD_AUTH_BIND:
                            # 鉴权响应已在 connect 中处理
                            pass
                        else:
                            print(f"[响应] 收到业务响应: cmd={cmd}")
                    
                    elif cmd_type == CMD_TYPE_PUSH:
                        print(f"\n{'='*50}")
                        print(f"[推送] ⭐ 收到 PUSH 消息!")
                        raw_data = conn_msg['data']
                        print(f"[推送] 原始数据长度: {len(raw_data)} bytes")

                        # 尝试解析 JSON 格式的消息
                        inbound = None
                        try:
                            json_str = raw_data.decode('utf-8')
                            inbound = json.loads(json_str)
                            print(f"[推送] JSON 解析成功!")
                            print(f"[推送] 消息内容: {json.dumps(inbound, indent=2, ensure_ascii=False)[:500]}")
                        except Exception as e:
                            print(f"[推送] 解析失败: {e}")
                            inbound = None

                        # 处理消息并自动回复
                        if inbound:
                            try:
                                # JSON 格式的字段名是下划线格式
                                text = ''
                                is_at_me = False
                                msg_body = inbound.get('msg_body', [])

                                if msg_body and len(msg_body) > 0:
                                    msg_elem = msg_body[0]
                                    msg_type = msg_elem.get('msg_type', '')
                                    msg_content = msg_elem.get('msg_content', {})

                                    if msg_type == 'TIMTextElem':
                                        # 普通文本消息
                                        text = msg_content.get('text', '')
                                        is_at_me = f"@{self.bot_id}" in text
                                    elif msg_type == 'TIMCustomElem':
                                        # 自定义消息（群聊艾特是这种类型）
                                        data_str = msg_content.get('data', '{}')
                                        try:
                                            custom_data = json.loads(data_str)
                                            # elem_type=1002 表示艾特
                                            if custom_data.get('elem_type') == 1002:
                                                at_text = custom_data.get('text', '')
                                                at_user_id = custom_data.get('user_id', '')
                                                text = at_text
                                                # 检查是否艾特了本机器人
                                                is_at_me = at_user_id == self.bot_id or f"@{self.bot_id}" in at_text
                                                print(f"[艾特] 检测到艾特消息: {at_text}, 目标用户: {at_user_id}")
                                        except:
                                            pass

                                from_account = inbound.get('from_account')
                                group_code = inbound.get('group_code')
                                sender = inbound.get('sender_nickname', from_account)
                                callback_cmd = inbound.get('callback_command', '')

                                print(f"[收到] 发送者={sender}, 来自={from_account}, 群={group_code}")
                                print(f"[收到] 内容={text}")
                                print(f"[检查] 是否艾特我: {is_at_me}")

                                is_group = 'Group' in callback_cmd if callback_cmd else False

                                if is_group and group_code:
                                    # 群消息 - 只有被艾特才回复
                                    if is_at_me:
                                        print(f"[回复] 群消息被艾特，回复...")
                                        await self.send_group_message(group_code, "我是傻逼")
                                    else:
                                        print(f"[跳过] 群消息未艾特")
                                elif from_account:
                                    # 私聊消息 - 直接回复
                                    print(f"[回复] 私聊消息，回复...")
                                    await self.send_c2c_message(from_account, "我是傻逼")
                            except Exception as e:
                                print(f"[自动回复] 错误: {e}")
                                import traceback
                                traceback.print_exc()
                        else:
                            print(f"[推送] 未能解析消息")
                    elif cmd_type == CMD_TYPE_PUSH_ACK:
                        print(f"[ACK] 收到确认")
                    
                except Exception as e:
                    print(f"[接收] 消息解析错误: {e}")
                    import traceback
                    traceback.print_exc()
        
        except websockets.exceptions.ConnectionClosed as e:
            print(f"[接收] 连接已关闭: {e}")
        except Exception as e:
            print(f"[接收] 错误: {e}")
        finally:
            self.connected = False
            print("[接收] 循环结束")
    
    async def disconnect(self):
        """断开连接"""
        self.connected = False
        if self.ws:
            await self.ws.close()
            self.ws = None
        print("[断开] 已断开连接")


import argparse

async def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='元宝 Bot WebSocket 客户端')
    parser.add_argument('-a', '--active-send', nargs=2, metavar=('TARGET', 'MESSAGE'),
                        help='主动发送消息后退出 (TARGET: 群号/用户ID, MESSAGE: 消息内容)')
    parser.add_argument('-aaa', '--active-spam', nargs=3, metavar=('TARGET', 'MESSAGE', 'COUNT'),
                        help='刷屏模式: 重复发送消息 (TARGET: 群号/用户ID, MESSAGE: 消息内容, COUNT: 重复次数)')
    parser.add_argument('-t', '--type', choices=['group', 'c2c'], default='group',
                        help='发送类型: group(群聊) 或 c2c(私聊), 默认 group')
    args = parser.parse_args()

    client = YuanbaoClient(
        app_key=APP_KEY,
        app_secret=APP_SECRET
    )

    # 检查是否有主动发送参数
    is_active_mode = args.active_send or args.active_spam

    # 普通单次发送
    if args.active_send:
        target, message = args.active_send
        print(f"[主动发送] 准备发送消息到 {args.type}: {target}")
        print(f"[主动发送] 内容: {message}")

        async def send_and_exit():
            """发送消息后退出"""
            await asyncio.sleep(2)
            if args.type == 'group':
                await client.send_group_message(target, message)
            else:
                await client.send_c2c_message(target, message)
            await asyncio.sleep(2)
            print("[主动发送] 消息已发送，退出程序")
            await client.disconnect()

        client._receive_loop = send_and_exit

    # 刷屏模式（重复发送）
    elif args.active_spam:
        target, message, count = args.active_spam
        count = int(count)
        print(f"⚠️  [刷屏模式] 准备向 {args.type}: {target} 发送 {count} 次消息")
        print(f"⚠️  [刷屏内容] {message}")
        print(f"⚠️  [提示] 按 Ctrl+C 可提前停止")

        async def spam_and_exit():
            """重复发送消息后退出"""
            await asyncio.sleep(2)
            for i in range(count):
                if not client.connected:
                    print("[刷屏] 连接已断开，停止发送")
                    break
                try:
                    if args.type == 'group':
                        await client.send_group_message(target, message)
                    else:
                        await client.send_c2c_message(target, message)
                    print(f"[刷屏] 第 {i+1}/{count} 次发送成功")
                    # 间隔1秒，避免被限制
                    if i < count - 1:
                        await asyncio.sleep(1)
                except Exception as e:
                    print(f"[刷屏] 第 {i+1} 次发送失败: {e}")
                    break
            await asyncio.sleep(2)
            print("[刷屏] 发送完成，退出程序")
            await client.disconnect()

        client._receive_loop = spam_and_exit

    # 设置消息处理器（仅在被动模式下使用）
    if not is_active_mode:
        def on_message(msg):
            print(f"[回调] 收到消息: {json.dumps(msg, indent=2, default=str)}")
        client.set_message_handler(on_message)

    try:
        # 创建连接任务
        connect_task = asyncio.create_task(client.connect())
        # 设置超时
        if args.active_spam:
            timeout = 10 + int(args.active_spam[2]) * 2  # 根据次数动态设置
        elif args.active_send:
            timeout = 30
        else:
            timeout = 600
        await asyncio.wait_for(connect_task, timeout=timeout)
    except asyncio.TimeoutError:
        print("\n[主程序] 超时断开")
        await client.disconnect()
    except KeyboardInterrupt:
        print("\n[主程序] 收到中断信号，正在停止...")
        await client.disconnect()
    except Exception as e:
        print(f"[主程序] 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("=" * 50)
    print("🤖 元宝 Bot WebSocket 客户端")
    print("=" * 50)
    print("💬 自动回复模式: python yuanbao_client.py")
    print("📤 单次发送: python yuanbao_client.py -a 群号 '消息'")
    print("💥 刷屏模式: python yuanbao_client.py -aaa 群号 '消息' 10")
    print("⏱️  运行时间: 默认10分钟后自动断开")
    print("=" * 50)
    asyncio.run(main())
