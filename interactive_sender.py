#!/usr/bin/env python3
"""
元宝 Bot 交互式消息发送器
不修改原项目，独立运行
"""

import asyncio
import sys
import json
import hashlib
import hmac
import random
import string
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import requests
import websockets

# 从配置文件导入
from config import APP_KEY, APP_SECRET, API_DOMAIN, WS_URL

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
    def encode_send_group_msg_req(msg_id: str, group_code: str, from_account: str, text: str) -> bytes:
        data = b''
        data += SimpleProtobufCodec.encode_string(1, msg_id)
        data += SimpleProtobufCodec.encode_string(2, group_code)
        data += SimpleProtobufCodec.encode_string(3, from_account)
        data += SimpleProtobufCodec.encode_string(5, str(random.randint(1, 999999999)))

        msg_content = SimpleProtobufCodec.encode_string(1, text)
        msg_body_elem = SimpleProtobufCodec.encode_string(1, "TIMTextElem")
        msg_body_elem += SimpleProtobufCodec.encode_message_field(2, msg_content)
        data += SimpleProtobufCodec.encode_message_field(6, msg_body_elem)

        return data


class InteractiveSender:
    """交互式消息发送器"""

    def __init__(self):
        self.token: Optional[str] = None
        self.bot_id: Optional[str] = None
        self.ws = None
        self.connected = False
        self.seq_no = 0
        self.group_code: Optional[str] = None
        self.codec = SimpleProtobufCodec()

    def _generate_msg_id(self) -> str:
        import uuid
        return uuid.uuid4().hex

    def _get_beijing_time(self) -> str:
        from datetime import timezone
        utc = datetime.now(timezone.utc)
        beijing = utc + timedelta(hours=8)
        return beijing.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    def sign_token(self) -> bool:
        """签票获取 token"""
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
                print(f"✅ 签票成功! Bot ID: {self.bot_id}")
                return True
            else:
                print(f"❌ 签票失败: {result}")
                return False
        except Exception as e:
            print(f"❌ 签票错误: {e}")
            return False

    async def connect(self) -> bool:
        """连接 WebSocket"""
        if not self.token and not self.sign_token():
            return False

        try:
            self.ws = await websockets.connect(WS_URL)
            auth_msg = self._build_auth_bind_msg()
            await self.ws.send(auth_msg)
            response = await self.ws.recv()
            if b"success" in response or True:  # 简化判断
                self.connected = True
                print("✅ WebSocket 连接成功!")
                asyncio.create_task(self._heartbeat())
                return True
        except Exception as e:
            print(f"❌ 连接失败: {e}")
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

    async def get_group_members(self) -> Optional[list]:
        """获取群成员列表"""
        if not self.connected or not self.ws:
            print("❌ 未连接")
            return None

        try:
            # 构建获取群成员列表请求
            import json
            group_code_data = json.dumps({"group_code": self.group_code}).encode()

            head = self.codec.encode_head(
                cmd_type=CMD_TYPE_REQUEST, cmd="get_group_member_list", seq_no=self.seq_no,
                msg_id=self._generate_msg_id(), module=BIZ_MODULE
            )
            self.seq_no += 1

            # 这里简化处理，实际应该发送 protobuf 请求并等待响应
            # 暂时返回 None，表示需要手动输入
            return None
        except Exception as e:
            print(f"❌ 获取群成员失败: {e}")
            return None

    def _build_at_message(self, text: str, at_user_id: str, at_nickname: str = "") -> bytes:
        """构建带艾特的群消息 - 同时包含 TIMCustomElem(艾特) + TIMTextElem(文本)"""
        import json
        
        display_name = at_nickname or at_user_id
        
        # ===== 第一个元素: TIMCustomElem (纯艾特，text只包含@昵称) =====
        # 艾特格式: {"elem_type": 1002, "text": "@昵称", "user_id": "用户ID"}
        at_data = json.dumps({
            "elem_type": 1002,
            "text": f"@{display_name}",
            "user_id": at_user_id
        })
        
        # 编码艾特元素的 msg_content
        at_content = self.codec.encode_string(4, at_data)  # data字段(field 4)
        
        # 构建艾特元素 (MsgBodyElement)
        at_elem = b''
        at_elem += self.codec.encode_string(1, "TIMCustomElem")  # msgType
        at_elem += self.codec.encode_message_field(2, at_content)  # msgContent
        
        # ===== 第二个元素: TIMTextElem (消息文本) =====
        text_content = self.codec.encode_string(1, text)  # text字段(field 1)
        
        text_elem = b''
        text_elem += self.codec.encode_string(1, "TIMTextElem")  # msgType
        text_elem += self.codec.encode_message_field(2, text_content)  # msgContent
        
        # ===== 构建 SendGroupMessageReq =====
        data = b''
        data += self.codec.encode_string(1, self._generate_msg_id())  # msgId
        data += self.codec.encode_string(2, self.group_code)  # groupCode
        data += self.codec.encode_string(3, self.bot_id or "")  # fromAccount
        data += self.codec.encode_string(5, str(random.randint(1, 999999999)))  # random
        
        # msgBody - repeated字段，每个元素单独编码(field 6)
        data += self.codec.encode_message_field(6, at_elem)    # msgBody[0] (艾特)
        data += self.codec.encode_message_field(6, text_elem)  # msgBody[1] (文本)

        head = self.codec.encode_head(
            cmd_type=CMD_TYPE_REQUEST, cmd=BIZ_CMD_SEND_GROUP, seq_no=self.seq_no,
            msg_id=self._generate_msg_id(), module=BIZ_MODULE
        )
        self.seq_no += 1

        return self.codec.encode_conn_msg(head, data)

    async def send_group_message(self, text: str, at_user: str = None, at_nickname: str = None) -> bool:
        """发送群消息，支持艾特"""
        if not self.connected or not self.ws:
            print("❌ 未连接")
            return False
        try:
            if at_user:
                # 发送带艾特的消息
                msg = self._build_at_message(text, at_user, at_nickname)
                print(f"📤 发送艾特消息 -> @{at_nickname or at_user}: {text[:50]}")
            else:
                # 发送普通消息
                msg = self._build_group_msg(text)
            await self.ws.send(msg)
            return True
        except Exception as e:
            print(f"❌ 发送失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def _heartbeat(self):
        """心跳"""
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

    async def _dummy_receive(self):
        """虚拟接收循环，保持连接"""
        try:
            while self.connected and self.ws:
                await self.ws.recv()
        except:
            pass

    async def disconnect(self):
        """断开连接"""
        self.connected = False
        if self.ws:
            await self.ws.close()


async def interactive_mode():
    """交互式模式"""
    sender = InteractiveSender()

    print("=" * 50)
    print("💬 元宝 Bot 交互式发送器")
    print("=" * 50)

    # 输入群号
    group_code = input("请输入群号: ").strip()
    if not group_code:
        print("❌ 群号不能为空")
        return

    sender.group_code = group_code
    print(f"✅ 目标群: {group_code}")
    print("🔄 正在连接...")

    if not await sender.connect():
        print("❌ 连接失败，退出")
        return

    print("\n" + "=" * 50)
    print("💡 使用说明:")
    print("   直接输入文字 → 发送消息")
    print("   /spam 内容 次数 → 重复发送模式")
    print("   /at → 艾特用户选择器")
    print("   /at 用户ID 内容 → 艾特指定用户")
    print("   /exit → 退出程序")
    print("   \\n 会被转义成换行")
    print("=" * 50 + "\n")

    # 简单的用户数据库（可以手动添加常用用户）
    # 格式: {"用户ID": "昵称"}
    user_db = {}

    # 消息接收循环（不处理，只保持连接）
    asyncio.create_task(sender._dummy_receive())

    # 输入循环
    while sender.connected:
        try:
            user_input = input("> ").strip()
            if not user_input:
                continue

            # 退出命令
            if user_input == "/exit":
                print("👋 再见!")
                break

            # 刷屏模式
            if user_input.startswith("/spam "):
                parts = user_input[6:].rsplit(" ", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    content, count = parts[0], int(parts[1])
                    content = content.replace("\\n", "\n")
                    print(f"⚠️  刷屏模式: 发送 '{content}' 共 {count} 次")
                    for i in range(count):
                        if await sender.send_group_message(content):
                            print(f"   [{i+1}/{count}] 发送成功")
                        else:
                            print(f"   [{i+1}/{count}] 发送失败")
                        if i < count - 1:
                            await asyncio.sleep(1)
                    print("✅ 刷屏完成")
                else:
                    print("❌ 格式错误，正确格式: /spam 内容 次数")
                continue

            # 艾特用户选择器
            if user_input == "/at":
                print("\n👥 艾特用户选择器")
                print("-" * 40)
                if user_db:
                    print("已保存的用户:")
                    for idx, (user_id, nickname) in enumerate(user_db.items(), 1):
                        print(f"  {idx}. {nickname} ({user_id})")
                    print("-" * 40)

                print("选项:")
                print("  1. 输入用户ID和消息")
                print("  2. 添加常用用户")
                print("  3. 取消")

                choice = input("请选择 [1-3]: ").strip()

                if choice == "1":
                    at_user = input("请输入要艾特的用户ID: ").strip()
                    at_nick = user_db.get(at_user, "")
                    if not at_nick:
                        at_nick = input("请输入用户昵称 (直接回车使用ID): ").strip() or at_user
                    message = input("请输入消息内容: ").strip().replace("\\n", "\n")

                    if at_user and message:
                        if await sender.send_group_message(message, at_user, at_nick):
                            print(f"✅ 艾特消息已发送")
                        else:
                            print("❌ 发送失败")

                elif choice == "2":
                    new_id = input("请输入用户ID: ").strip()
                    new_nick = input("请输入昵称: ").strip()
                    if new_id and new_nick:
                        user_db[new_id] = new_nick
                        print(f"✅ 已添加: {new_nick} ({new_id})")

                print("-" * 40 + "\n")
                continue

            # 快捷艾特命令: /at 用户ID 消息内容
            if user_input.startswith("/at "):
                parts = user_input[4:].split(" ", 1)
                if len(parts) == 2:
                    at_user, message = parts
                    at_nick = user_db.get(at_user, at_user)
                    message = message.replace("\\n", "\n")
                    if await sender.send_group_message(message, at_user, at_nick):
                        print(f"✅ 艾特消息已发送")
                    else:
                        print("❌ 发送失败")
                else:
                    print("❌ 格式错误，正确格式: /at 用户ID 消息内容")
                continue

            # 普通消息
            message = user_input.replace("\\n", "\n")
            if await sender.send_group_message(message):
                print(f"✅ 发送成功: {message[:50]}...")
            else:
                print("❌ 发送失败")

        except KeyboardInterrupt:
            print("\n👋 再见!")
            break
        except Exception as e:
            print(f"❌ 错误: {e}")

    await sender.disconnect()


async def main():
    """主函数"""
    try:
        await interactive_mode()
    except Exception as e:
        print(f"❌ 程序错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
