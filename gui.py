#!/usr/bin/env python3
"""
元宝 Bot GUI 控制台
基于 customtkinter 的现代化暗色主题 GUI
样式完全复刻 index.html 的设计
"""

import customtkinter as ctk
import tkinter as tk
import asyncio
import threading
import json
import os
import sys
import time
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(__file__))

# ── 配置主题 ──
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── 颜色常量 (与 index.html CSS 变量一致) ──
COLORS = {
    "bg_primary": "#0f0f1a",
    "bg_secondary": "#1a1a2e",
    "bg_card": "#1e1e35",
    "bg_tab": "#12122a",
    "border": "#2a2a45",
    "text_primary": "#e0e0f0",
    "text_secondary": "#8888aa",
    "text_muted": "#555577",
    "accent": "#7c5cfc",
    "accent_hover": "#6a4ae8",
    "success": "#34c759",
    "warning": "#ff9500",
    "danger": "#ff3b30",
    "error": "#ff3b30",
    "input_bg": "#252540",
    "msg_self": "#2a2a60",
    "msg_other": "#252540",
    "tab_bar_bg": "#0d0d1a",
}

# ── 贴纸表情映射 ──
STICKER_EMOJI = {
    "六六六": "6️⃣", "我想开了": "🌸", "害羞": "😊", "比心": "💜", "委屈": "🥺",
    "亲亲": "😘", "酷": "😎", "睡": "😴", "发呆": "😶", "可怜": "🥹",
    "摊手": "🤷", "头大": "😵", "吓": "😱", "吐血": "🤮", "哼": "😤",
    "嘿嘿": "😏", "头秃": "🦲", "暗中观察": "👀", "我酸了": "🍋", "打call": "📞",
    "庆祝": "🎉", "奋斗": "💪", "惊讶": "😲", "疑问": "❓", "仔细分析": "🤔",
    "撅嘴": "😗", "泪奔": "😭", "尊嘟假嘟": "🤨", "略略略": "😛", "困": "😪",
    "折磨": "😫", "抠鼻": "👃", "鼓掌": "👏", "斜眼笑": "😏", "辣眼睛": "🌶️",
    "哦哟": "🤭", "吃瓜": "🍉", "狗头": "🐶", "敬礼": "🫡", "哦": "😮",
    "拿到红包": "🧧", "牛吖": "🐮", "贴贴": "🤗", "爱心": "❤️", "晚安": "🌙",
    "太阳": "☀️", "柠檬": "🍋", "大冤种": "😅", "吐了": "🤮", "怒": "😠",
    "玫瑰": "🌹", "凋谢": "🥀", "点赞": "👍", "握手": "🤝", "抱拳": "🙏",
    "ok": "👌", "拳头": "👊", "鞭炮": "🧨", "烟花": "🎆",
}


# ═══════════════════════════════════════════
# BotController: 异步机器人控制器
# ═══════════════════════════════════════════
class BotController:
    """在后台线程中管理 SpamSender 的异步操作"""

    def __init__(self):
        self.sender = None
        self.loop = None
        self._thread = None
        self._running = False
        self._last_msg_idx = 0
        self._connected = False
        self._bot_id = ""
        self._group_code = ""
        self._auto_reply_enabled = False

    # ── 生命周期 ──

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()
        for _ in range(50):
            if self.loop is not None:
                break
            time.sleep(0.02)

    def stop(self):
        self._running = False
        if self.loop:
            try:
                asyncio.run_coroutine_threadsafe(self._disconnect_async(), self.loop)
            except Exception:
                pass
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except Exception:
                pass

    def _run_event_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    @property
    def connected(self):
        return self._connected

    @property
    def bot_id(self):
        return self._bot_id

    @property
    def group_code(self):
        return self._group_code

    # ── 异步核心操作 ──

    async def _connect_async(self, group_code: str) -> str:
        from sender import SpamSender
        sender = SpamSender()
        sender.group_code = group_code
        ok = await sender.connect()
        if not ok:
            raise Exception("连接失败")
        asyncio.create_task(sender._receive_loop())
        self.sender = sender
        self._connected = True
        self._bot_id = sender.bot_id or ""
        self._group_code = group_code
        return self._bot_id

    async def _disconnect_async(self):
        self._auto_reply_enabled = False
        if self.sender:
            try:
                await self.sender.disconnect()
            except Exception:
                pass
            self.sender = None
        self._connected = False
        self._bot_id = ""

    # ── 配置读写 ──

    @staticmethod
    def _load_config() -> dict:
        cp = os.path.join(os.path.dirname(__file__), "config.json")
        try:
            with open(cp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def _save_config_file(config: dict):
        cp = os.path.join(os.path.dirname(__file__), "config.json")
        with open(cp, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

    async def _send_group_async(self, text: str, at_user: str = "", at_nickname: str = ""):
        if not self.sender or not self._connected:
            raise Exception("未连接")
        ok = await self.sender.send_group_message(text, at_user, at_nickname)
        if not ok:
            raise Exception("发送失败")
        return True

    async def _send_dm_async(self, to_account: str, text: str):
        if not self.sender or not self._connected:
            raise Exception("未连接")
        ok = await self.sender.send_dm_message(to_account, text)
        if not ok:
            raise Exception("发送失败")
        return True

    async def _send_multi_at_async(self, text: str, at_users: list):
        if not self.sender or not self._connected:
            raise Exception("未连接")
        ok = await self.sender.send_multi_at_message(text, at_users)
        if not ok:
            raise Exception("发送失败")
        return True

    async def _spam_async(self, text: str, count: int, at_user: str = "",
                          at_nickname: str = "", interval: float = 1.0,
                          progress_callback=None):
        if not self.sender or not self._connected:
            raise Exception("未连接")
        return await self.sender.spam_with_at(
            text=text, count=count, at_user=at_user,
            at_nickname=at_nickname, interval=interval,
            progress_callback=progress_callback
        )

    async def _send_sticker_async(self, name: str, text: str = "",
                                  at_user: str = "", at_nickname: str = ""):
        if not self.sender or not self._connected:
            raise Exception("未连接")
        ok = await self.sender.send_sticker_message(name, text=text,
                                                     at_user=at_user, at_nickname=at_nickname)
        if not ok:
            raise Exception("发送失败")
        return True

    async def _get_members_async(self):
        if not self.sender or not self._connected:
            raise Exception("未连接")
        return await self.sender.send_get_members_request()

    # ── 自动回复（完全复刻 client.py get_auto_reply + 消息解析逻辑）──

    def get_auto_reply(self, text: str, is_group: bool = False) -> str:
        """根据消息文本和聊天类型，按 config.json 规则匹配返回自动回复内容。
        规则优先级：AUTO_REPLY_RULES → DEFAULT_REPLY → AUTO_REPLY_GROUP/C2C_TEXT
        匹配类型：exact（精确匹配）、contains（包含匹配）、contains_any（多值任一匹配）
        group_only 标记仅在群聊生效。
        """
        config = self._load_config()
        rules = config.get("AUTO_REPLY_RULES", [])
        default_reply = config.get("DEFAULT_REPLY", "")
        group_text = config.get("AUTO_REPLY_GROUP_TEXT", "@我干啥")
        c2c_text = config.get("AUTO_REPLY_C2C_TEXT", "我是Bot")

        text = text.strip()

        # 消息为空 → 默认回复
        if not text:
            if default_reply:
                return default_reply
            return group_text if is_group else c2c_text

        # 按顺序遍历规则（先匹配先返回）
        for rule in rules:
            if rule.get("group_only", False) and not is_group:
                continue

            match_type = rule.get("match_type", "")
            if match_type == "exact":
                if text == rule.get("pattern", ""):
                    return rule.get("reply_text", "")
            elif match_type == "contains":
                pattern = rule.get("pattern", "")
                if pattern and pattern in text:
                    return rule.get("reply_text", "")
            elif match_type == "contains_any":
                for pattern in rule.get("patterns", []):
                    if pattern and pattern in text:
                        return rule.get("reply_text", "")

        # 无规则匹配 → DEFAULT_REPLY → 旧默认
        if default_reply:
            return default_reply
        return group_text if is_group else c2c_text

    async def _on_push_for_auto_reply(self, push_json: dict, cache_entry: dict):
        """推送消息回调：由 sender._receive_loop 直接调用，拿到完整原始数据。
        完全复刻 client.py._receive_loop 的消息解析 + 自动回复逻辑。
        """
        if not self._auto_reply_enabled or not self.sender:
            return

        try:
            # 跳过自己发出的消息
            from_account = push_json.get("from_account", "")
            if from_account == self._bot_id:
                return

            # ── 解析 msg_body（复刻 client.py 的逻辑）──
            text_parts = []
            is_at_me = False
            msg_body = push_json.get("msg_body", [])

            for msg_elem in msg_body:
                msg_type = msg_elem.get("msg_type", "")
                msg_content = msg_elem.get("msg_content", {})

                if msg_type == "TIMTextElem":
                    text_content = msg_content.get("text", "")
                    if text_content:
                        text_parts.append(text_content)
                    # 检测文本中是否包含 @bot_id
                    if f"@{self._bot_id}" in text_content:
                        is_at_me = True

                elif msg_type == "TIMCustomElem":
                    data_str = msg_content.get("data", "{}")
                    try:
                        custom_data = json.loads(data_str)
                        if custom_data.get("elem_type") == 1002:
                            at_text = custom_data.get("text", "")
                            at_user_id = custom_data.get("user_id", "")
                            if at_text:
                                text_parts.append(at_text)
                            # 精确检测是否艾特本机器人
                            if at_user_id == self._bot_id or f"@{self._bot_id}" in at_text:
                                is_at_me = True
                    except Exception:
                        pass

            # ── 合并文本 ──
            text = " ".join(text_parts).strip()

            # ── 清理 @前缀（复刻 client.py）──
            if text and is_at_me:
                bot_prefix = f"@{self._bot_id}"
                if text.startswith(bot_prefix):
                    text = text[len(bot_prefix):].strip()
                elif text.startswith("@"):
                    space_pos = text.find(" ")
                    if space_pos > 0:
                        text = text[space_pos:].strip()
                    else:
                        if text != "@":
                            text = "@"
            if not text and is_at_me:
                text = "@"  # 纯艾特视为 "@"

            # ── 判断聊天类型 ──
            group_code = push_json.get("group_code", "")
            callback_cmd = push_json.get("callback_command", "")
            is_group = bool(group_code and ("Group" in callback_cmd if callback_cmd else group_code))

            # ── 确定是否需要回复 ──
            need_reply = False
            if is_group and group_code:
                need_reply = is_at_me  # 群消息仅在被 @时回复
            elif from_account:
                need_reply = True      # 私聊直接回复

            if need_reply:
                reply_text = self.get_auto_reply(text, is_group)
                if reply_text:
                    if is_group:
                        await self.sender.send_group_message(group_code, reply_text)
                    else:
                        await self.sender.send_dm_message(from_account, reply_text)

        except Exception:
            pass  # 单条异常不影响后续

    def enable_auto_reply(self):
        """启用自动回复：将回调安装到 sender，消息到达时自动触发"""
        if not self._connected or not self.sender:
            return
        self._auto_reply_enabled = True
        self.sender.on_push_message = self._on_push_for_auto_reply

    def disable_auto_reply(self):
        """停用自动回复：移除回调"""
        self._auto_reply_enabled = False
        if self.sender:
            self.sender.on_push_message = None

    # ── 线程安全调度 ──

    def _run_async(self, coro):
        if not self.loop or not self.loop.is_running():
            raise Exception("事件循环未运行")
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _wrap_coro_with_callbacks(self, coro_fn, on_success, on_error, *args):
        async def task():
            try:
                result = await coro_fn(*args)
                return ("success", result)
            except Exception as e:
                return ("error", str(e))

        def callback(fut):
            try:
                status, data = fut.result()
                if status == "success":
                    on_success(data) if on_success else None
                else:
                    on_error(data) if on_error else None
            except Exception as e:
                on_error(str(e)) if on_error else None

        future = self._run_async(task())
        future.add_done_callback(callback)

    def connect(self, group_code: str, on_success=None, on_error=None):
        self._wrap_coro_with_callbacks(self._connect_async, on_success, on_error, group_code)

    def disconnect(self, on_done=None):
        async def task():
            await self._disconnect_async()
            return "done"

        def callback(fut):
            on_done() if on_done else None

        future = self._run_async(task())
        future.add_done_callback(callback)

    def send_message(self, mode: str, text: str, target: str = "",
                     count: int = 5, interval: float = 1.0,
                     on_success=None, on_error=None, on_progress=None):
        async def task():
            try:
                msg = ""
                if mode == "normal":
                    await self._send_group_async(text)
                    msg = "发送成功"
                elif mode == "at":
                    parts = target.split(":", 1)
                    uid = parts[0].strip()
                    nick = parts[1].strip() if len(parts) > 1 else uid
                    await self._send_group_async(text, uid, nick)
                    msg = "艾特消息已发送"
                elif mode == "spam":
                    s, f = await self._spam_async(
                        text, count, interval=interval,
                        progress_callback=lambda c, t, ok: (
                            on_progress(c, t, ok) if on_progress else None
                        )
                    )
                    msg = f"刷屏完成 成功:{s} 失败:{f}"
                elif mode == "multi-at":
                    users = [(u.strip(), u.strip()) for u in target.split(",") if u.strip()]
                    if not users:
                        raise Exception("未指定用户ID")
                    await self._send_multi_at_async(text, users)
                    msg = "批量艾特已发送"
                elif mode == "dm":
                    if not target:
                        raise Exception("请输入目标用户ID")
                    await self._send_dm_async(target, text)
                    msg = "私聊已发送"
                return ("success", msg)
            except Exception as e:
                return ("error", str(e))

        def callback(fut):
            try:
                status, data = fut.result()
                (on_success(data) if on_success else None) if status == "success" else (on_error(data) if on_error else None)
            except Exception as e:
                on_error(str(e)) if on_error else None

        future = self._run_async(task())
        future.add_done_callback(callback)

    def send_sticker(self, sticker_name: str, text: str = "",
                     at_user: str = "", on_success=None, on_error=None):
        self._wrap_coro_with_callbacks(
            self._send_sticker_async, on_success, on_error,
            sticker_name, text, at_user
        )

    def load_members(self, on_result=None, on_error=None):
        self._wrap_coro_with_callbacks(
            self._get_members_async, on_result, on_error
        )

    def get_new_messages(self) -> list:
        if not self.sender:
            return []
        cache = self.sender.msg_cache
        new_msgs = cache[self._last_msg_idx:]
        self._last_msg_idx = len(cache)
        return new_msgs

    def get_sticker_list(self) -> list:
        from sender import SpamSender
        return [
            {"key": name, "name": name, "emoji": STICKER_EMOJI.get(name, "😀")}
            for name in SpamSender.STICKERS.keys()
        ]


# ═══════════════════════════════════════════
# 主 GUI 类
# ═══════════════════════════════════════════
class YuanbaoGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("元宝 Bot 控制台")
        self.geometry("520x820")
        self.minsize(420, 650)
        self.configure(fg_color=COLORS["bg_primary"])

        # 状态
        self._connected = False
        self._current_tab = "messages"
        self._current_mode = "normal"
        self._selected_sticker = None
        self._message_count = 0
        self._all_members = []
        self._all_stickers = []
        self._current_rules = []  # 当前编辑中的自动回复规则
        self._toast_timer = None

        # 机器人控制器
        self.bot = BotController()
        self.bot.start()

        # 构建 UI (顺序: header → content → tab_bar → toast)
        self._create_header()
        self._create_content()
        self._create_tab_bar()
        self._create_toast()

        # 初始化数据
        self._all_stickers = self.bot.get_sticker_list()
        self._load_settings()
        self._poll_messages()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ═══════════════════════════════════════
    # Header
    # ═══════════════════════════════════════

    def _create_header(self):
        header = ctk.CTkFrame(self, fg_color=COLORS["bg_secondary"],
                              border_color=COLORS["border"], border_width=1,
                              height=48, corner_radius=0)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        ctk.CTkLabel(header, text="🤖 元宝 Bot",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=COLORS["text_primary"]
                     ).pack(side="left", padx=16, pady=10)

        status_frame = ctk.CTkFrame(header, fg_color="transparent")
        status_frame.pack(side="right", padx=16, pady=10)

        self._status_text = ctk.CTkLabel(status_frame, text="未连接",
                                         font=ctk.CTkFont(size=13),
                                         text_color=COLORS["danger"])
        self._status_text.pack(side="left", padx=(0, 8))

        self._status_dot = tk.Canvas(status_frame, width=8, height=8,
                                     bg=COLORS["bg_secondary"], highlightthickness=0)
        self._status_dot.pack(side="left")
        self._draw_status_dot(False)

    def _draw_status_dot(self, connected: bool):
        self._status_dot.delete("all")
        color = COLORS["success"] if connected else COLORS["danger"]
        self._status_dot.create_oval(0, 0, 8, 8, fill=color, outline="")

    # ═══════════════════════════════════════
    # Content Area (Tab Pages)
    # ═══════════════════════════════════════

    def _create_content(self):
        self._content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._content_frame.pack(fill="both", expand=True)

        self._tab_frames = {}
        self._create_messages_tab()
        self._create_send_tab()
        self._create_stickers_tab()
        self._create_members_tab()
        self._create_settings_tab()

        self._show_tab("messages")

    # ── 消息标签页 ──

    def _create_messages_tab(self):
        frame = ctk.CTkFrame(self._content_frame, fg_color="transparent")
        self._tab_frames["messages"] = frame

        # 按钮行
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(10, 6))

        self._btn_connect = ctk.CTkButton(
            row, text="🔗 连接", width=80, height=30,
            fg_color=COLORS["success"], hover_color="#2da84d",
            font=ctk.CTkFont(size=12), corner_radius=6,
            command=self._on_connect)
        self._btn_connect.pack(side="left", padx=(0, 5))

        self._btn_disconnect = ctk.CTkButton(
            row, text="🔌 断开", width=80, height=30,
            fg_color=COLORS["danger"], hover_color="#d93030",
            font=ctk.CTkFont(size=12), corner_radius=6,
            command=self._on_disconnect, state="disabled")
        self._btn_disconnect.pack(side="left", padx=5)

        ctk.CTkButton(row, text="🔄 刷新", width=75, height=30,
                      fg_color="transparent", border_color=COLORS["border"],
                      border_width=1, font=ctk.CTkFont(size=12), corner_radius=6,
                      text_color=COLORS["text_primary"],
                      command=self._on_refresh_messages
                      ).pack(side="left", padx=5)

        ctk.CTkButton(row, text="🗑️ 清空", width=75, height=30,
                      fg_color="transparent", border_color=COLORS["border"],
                      border_width=1, font=ctk.CTkFont(size=12), corner_radius=6,
                      text_color=COLORS["text_primary"],
                      command=self._on_clear_messages
                      ).pack(side="left", padx=5)

        # 消息日志
        self._message_log = ctk.CTkTextbox(
            frame, fg_color=COLORS["bg_primary"],
            border_color=COLORS["border"], border_width=1,
            font=ctk.CTkFont(size=13), wrap="word",
            corner_radius=8, state="disabled")
        self._message_log.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        self._show_empty_message("暂无消息\n连接后消息会自动显示在这里")

    # ── 发送标签页 ──

    def _create_send_tab(self):
        frame = ctk.CTkFrame(self._content_frame, fg_color="transparent")
        self._tab_frames["send"] = frame

        # 模式 Chips
        chips = ctk.CTkFrame(frame, fg_color="transparent")
        chips.pack(fill="x", padx=10, pady=(10, 8))

        modes = [("normal", "💬 普通"), ("at", "@ 艾特"), ("spam", "🔁 刷屏"),
                 ("multi-at", "👥 批量@"), ("dm", "✉️ 私聊")]
        self._mode_chips = {}
        for mk, ml in modes:
            btn = ctk.CTkButton(
                chips, text=ml, width=80, height=30,
                fg_color=COLORS["accent"] if mk == "normal" else "transparent",
                border_color=COLORS["border"], border_width=1,
                font=ctk.CTkFont(size=12), corner_radius=16,
                text_color="#ffffff" if mk == "normal" else COLORS["text_secondary"],
                command=lambda m=mk: self._set_mode(m))
            btn.pack(side="left", padx=3)
            self._mode_chips[mk] = btn

        # 目标用户行 (默认隐藏)
        self._target_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self._target_label = ctk.CTkLabel(
            self._target_frame, text="目标用户 ID",
            font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"])
        self._target_label.pack(anchor="w", padx=12, pady=(0, 2))
        self._target_entry = ctk.CTkEntry(
            self._target_frame, placeholder_text="输入用户ID",
            fg_color=COLORS["input_bg"], border_color=COLORS["border"],
            font=ctk.CTkFont(size=13), corner_radius=8, height=34)
        self._target_entry.pack(fill="x", padx=10)

        # 刷屏次数行 (默认隐藏)
        self._count_frame = ctk.CTkFrame(frame, fg_color="transparent")
        ctk.CTkLabel(self._count_frame, text="刷屏次数",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_secondary"]
                     ).pack(anchor="w", padx=12, pady=(0, 2))
        self._count_entry = ctk.CTkEntry(
            self._count_frame, placeholder_text="次数",
            fg_color=COLORS["input_bg"], border_color=COLORS["border"],
            font=ctk.CTkFont(size=13), corner_radius=8, height=34)
        self._count_entry.pack(fill="x", padx=10)
        self._count_entry.insert(0, "5")

        # 消息内容标签
        ctk.CTkLabel(frame, text="消息内容", font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_secondary"]
                     ).pack(anchor="w", padx=12, pady=(8, 2))

        self._msg_text = ctk.CTkTextbox(
            frame, fg_color=COLORS["input_bg"],
            border_color=COLORS["border"], border_width=1,
            font=ctk.CTkFont(size=13), wrap="word",
            corner_radius=8, height=100)
        self._msg_text.pack(fill="x", padx=10, pady=(0, 8))

        # 发送按钮
        self._btn_send = ctk.CTkButton(
            frame, text="📤 发送", height=38,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            font=ctk.CTkFont(size=14, weight="bold"), corner_radius=8,
            command=self._on_send_message)
        self._btn_send.pack(fill="x", padx=10, pady=(0, 10))

    # ── 贴纸标签页 ──

    def _create_stickers_tab(self):
        frame = ctk.CTkFrame(self._content_frame, fg_color="transparent")
        self._tab_frames["stickers"] = frame

        # 搜索
        self._sticker_search_var = tk.StringVar()
        self._sticker_search_var.trace_add("write", lambda *a: self._filter_stickers())
        ctk.CTkEntry(frame, placeholder_text="🔍 搜索贴纸...",
                     fg_color=COLORS["input_bg"], border_color=COLORS["border"],
                     font=ctk.CTkFont(size=13), corner_radius=8, height=34,
                     textvariable=self._sticker_search_var
                     ).pack(fill="x", padx=10, pady=(10, 6))

        # 贴纸网格
        self._sticker_grid = ctk.CTkScrollableFrame(
            frame, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["text_muted"])
        self._sticker_grid.pack(fill="both", expand=True, padx=10, pady=4)
        self._sticker_btns = {}

        # 文本 + 发送
        tr = ctk.CTkFrame(frame, fg_color="transparent")
        tr.pack(fill="x", padx=10, pady=4)
        self._sticker_text = ctk.CTkEntry(
            tr, placeholder_text="附加文本（可选）",
            fg_color=COLORS["input_bg"], border_color=COLORS["border"],
            font=ctk.CTkFont(size=13), corner_radius=8, height=34)
        self._sticker_text.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._btn_sticker_send = ctk.CTkButton(
            tr, text="发送", width=65, height=34,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            font=ctk.CTkFont(size=12), corner_radius=8,
            command=self._on_send_sticker)
        self._btn_sticker_send.pack(side="right")

        # @ 用户
        self._sticker_at = ctk.CTkEntry(
            frame, placeholder_text="@ 用户ID（可选）",
            fg_color=COLORS["input_bg"], border_color=COLORS["border"],
            font=ctk.CTkFont(size=13), corner_radius=8, height=34)
        self._sticker_at.pack(fill="x", padx=10, pady=(2, 10))

    # ── 成员标签页 ──

    def _create_members_tab(self):
        frame = ctk.CTkFrame(self._content_frame, fg_color="transparent")
        self._tab_frames["members"] = frame

        sr = ctk.CTkFrame(frame, fg_color="transparent")
        sr.pack(fill="x", padx=10, pady=(10, 6))

        self._member_search_var = tk.StringVar()
        self._member_search_var.trace_add("write", lambda *a: self._filter_members())
        ctk.CTkEntry(sr, placeholder_text="🔍 搜索成员...",
                     fg_color=COLORS["input_bg"], border_color=COLORS["border"],
                     font=ctk.CTkFont(size=13), corner_radius=8, height=34,
                     textvariable=self._member_search_var
                     ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        self._btn_member_refresh = ctk.CTkButton(
            sr, text="🔄 刷新", width=75, height=34,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            font=ctk.CTkFont(size=12), corner_radius=8,
            command=self._on_load_members)
        self._btn_member_refresh.pack(side="right")

        self._member_list_frame = ctk.CTkScrollableFrame(
            frame, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["text_muted"])
        self._member_list_frame.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        self._show_member_empty("点击刷新获取群成员")

    # ── 设置标签页 ──

    def _create_settings_tab(self):
        frame = ctk.CTkFrame(self._content_frame, fg_color="transparent")
        self._tab_frames["settings"] = frame

        # 用可滚动框架包裹所有设置
        scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["text_muted"])
        scroll.pack(fill="both", expand=True, padx=0, pady=0)

        # ── 连接设置 ──
        self._make_section_title(scroll, "🔗 连接设置", 0)

        self._setting_group_code = self._make_setting_row(scroll, "群号", "")
        self._setting_interval = self._make_setting_row(scroll, "刷屏间隔 (秒)", "1.0")

        # ── 自动回复 ──
        self._make_section_title(scroll, "🤖 自动回复", 1)

        switch_row = ctk.CTkFrame(scroll, fg_color="transparent")
        switch_row.pack(fill="x", padx=10, pady=(4, 6))
        ctk.CTkLabel(switch_row, text="启用自动回复",
                     font=ctk.CTkFont(size=13),
                     text_color=COLORS["text_primary"]
                     ).pack(side="left")
        self._auto_reply_var = tk.BooleanVar(value=False)
        self._auto_reply_var.trace_add("write", self._on_auto_reply_toggle)
        ctk.CTkSwitch(switch_row, text="",
                      variable=self._auto_reply_var,
                      progress_color=COLORS["accent"],
                      button_color=COLORS["text_primary"],
                      button_hover_color=COLORS["text_secondary"]
                      ).pack(side="right")

        self._setting_group_reply = self._make_setting_row(scroll, "群聊默认回复", "")
        self._setting_c2c_reply = self._make_setting_row(scroll, "私聊默认回复", "")

        # ── 回复规则编辑 ──
        self._make_section_title(scroll, "📋 回复规则", 2)

        self._rules_list_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._rules_list_frame.pack(fill="x", padx=10, pady=(4, 6))

        # 添加规则按钮
        btn_row = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkButton(btn_row, text="＋ 添加规则", width=110, height=30,
                      fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                      font=ctk.CTkFont(size=12), corner_radius=8,
                      command=self._on_add_rule).pack(side="right")

        # 保存按钮
        ctk.CTkButton(scroll, text="💾 保存设置", height=38,
                      fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                      font=ctk.CTkFont(size=14, weight="bold"), corner_radius=8,
                      command=self._on_save_settings
                      ).pack(fill="x", padx=10, pady=(12, 16))

    def _make_section_title(self, parent, title: str, idx: int):
        sep = ctk.CTkFrame(parent, fg_color=COLORS["border"], height=1)
        sep.pack(fill="x", padx=10, pady=(14 if idx > 0 else 8, 0))
        ctk.CTkLabel(parent, text=title,
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=COLORS["text_secondary"]
                     ).pack(anchor="w", padx=12, pady=(6, 4))

    def _make_setting_row(self, parent, label: str, default: str):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=13),
                     text_color=COLORS["text_primary"],
                     width=100, anchor="w").pack(side="left", padx=(2, 8))
        entry = ctk.CTkEntry(row, placeholder_text="",
                             fg_color=COLORS["input_bg"], border_color=COLORS["border"],
                             font=ctk.CTkFont(size=13), corner_radius=8, height=32)
        entry.pack(side="right", fill="x", expand=True)
        if default:
            entry.insert(0, default)
        return entry

    # ═══════════════════════════════════════
    # Bottom Tab Bar
    # ═══════════════════════════════════════

    def _create_tab_bar(self):
        bar = ctk.CTkFrame(self, fg_color=COLORS["tab_bar_bg"],
                           border_color=COLORS["border"], border_width=1,
                           height=56, corner_radius=0)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        tabs = [
            ("messages", "💬", "消息"),
            ("send", "📤", "发送"),
            ("stickers", "😀", "贴纸"),
            ("members", "👥", "成员"),
            ("settings", "⚙️", "设置"),
        ]
        self._tab_buttons = {}
        for tid, icon, label in tabs:
            btn_frame = ctk.CTkFrame(bar, fg_color="transparent")
            btn_frame.pack(side="left", fill="both", expand=True)

            icon_lbl = ctk.CTkLabel(btn_frame, text=icon,
                                    font=ctk.CTkFont(size=22),
                                    text_color=COLORS["text_muted"])
            icon_lbl.pack(pady=(8, 0))
            text_lbl = ctk.CTkLabel(btn_frame, text=label,
                                    font=ctk.CTkFont(size=10),
                                    text_color=COLORS["text_muted"])
            text_lbl.pack(pady=(0, 4))

            # 点击事件绑定到整个 frame
            for w in (btn_frame, icon_lbl, text_lbl):
                w.bind("<Button-1>", lambda e, t=tid: self._switch_tab(t))

            self._tab_buttons[tid] = {"icon": icon_lbl, "text": text_lbl}

        self._update_tab_bar_style("messages")

    def _update_tab_bar_style(self, active: str):
        for tid, w in self._tab_buttons.items():
            c = COLORS["accent"] if tid == active else COLORS["text_muted"]
            w["icon"].configure(text_color=c)
            w["text"].configure(text_color=c)
        self._current_tab = active

    def _switch_tab(self, tab_id: str):
        if tab_id == self._current_tab:
            return
        self._update_tab_bar_style(tab_id)
        self._show_tab(tab_id)

        if tab_id == "stickers" and not self._sticker_btns:
            self._render_stickers(self._all_stickers)
        if tab_id == "settings":
            self._load_settings()

    def _show_tab(self, tab_id: str):
        for tid, frame in self._tab_frames.items():
            frame.pack(fill="both", expand=True) if tid == tab_id else frame.pack_forget()

    # ═══════════════════════════════════════
    # Toast 提示
    # ═══════════════════════════════════════

    def _create_toast(self):
        self._toast_frame = ctk.CTkFrame(self, fg_color=COLORS["bg_card"],
                                         border_color=COLORS["border"],
                                         border_width=1, corner_radius=10)
        self._toast_label = ctk.CTkLabel(self._toast_frame, text="",
                                         font=ctk.CTkFont(size=13),
                                         text_color=COLORS["text_primary"],
                                         wraplength=400)
        self._toast_label.pack(padx=16, pady=8)

    def _show_toast(self, message: str, ttype: str = "info", duration: int = 3000):
        colors = {"success": COLORS["success"], "error": COLORS["danger"],
                  "warning": COLORS["warning"], "info": COLORS["border"]}
        self._toast_frame.configure(border_color=colors.get(ttype, COLORS["border"]))
        self._toast_label.configure(text=message)
        self._toast_frame.place(relx=0.5, y=70, anchor="n")
        self._toast_frame.lift()

        if self._toast_timer:
            self.after_cancel(self._toast_timer)
        self._toast_timer = self.after(duration, self._toast_frame.place_forget)

    # ═══════════════════════════════════════
    # 连接管理
    # ═══════════════════════════════════════

    def _on_connect(self):
        gc = self._setting_group_code.get().strip()
        if not gc:
            gc = self._load_config().get("DEFAULT_GROUP_CODE", "")
        if not gc:
            self._show_toast("⚠️ 请先在设置中填写群号", "warning")
            return

        self._btn_connect.configure(state="disabled", text="⏳ 连接中...")
        self._show_toast("正在连接...", "info", 10000)

        def ok(bot_id):
            self._connected = True
            self._update_status(True, bot_id)
            self._show_toast("✅ 连接成功！", "success")
            self._btn_connect.configure(state="disabled", text="🔗 连接")
            self._on_refresh_messages()
            # 连接成功后，如果自动回复开关已打开则启用
            if self._auto_reply_var.get():
                self.bot.enable_auto_reply()
                self._show_toast("🤖 自动回复已启用", "info", 2000)

        def err(msg):
            self._connected = False
            self._update_status(False, "")
            self._show_toast(f"❌ {msg}", "error")
            self._btn_connect.configure(state="normal", text="🔗 连接")

        self.bot.connect(gc, on_success=ok, on_error=err)

    def _on_disconnect(self):
        self._btn_disconnect.configure(state="disabled", text="⏳ 断开中...")

        def done():
            self._connected = False
            self.bot.disable_auto_reply()
            self._update_status(False, "")
            self._show_toast("已断开连接", "warning")
            self._btn_disconnect.configure(state="disabled", text="🔌 断开")

        self.bot.disconnect(on_done=done)

    def _update_status(self, connected: bool, bot_id: str = ""):
        if connected:
            self._status_text.configure(text=f"已连接 ({bot_id})",
                                        text_color=COLORS["success"])
            self._btn_connect.configure(state="disabled")
            self._btn_disconnect.configure(state="normal")
        else:
            self._status_text.configure(text="未连接",
                                        text_color=COLORS["danger"])
            self._btn_connect.configure(state="normal")
            self._btn_disconnect.configure(state="disabled")
        self._draw_status_dot(connected)

    # ═══════════════════════════════════════
    # 消息管理
    # ═══════════════════════════════════════

    def _poll_messages(self):
        try:
            for msg in self.bot.get_new_messages():
                self._append_message(msg)
        except Exception:
            pass
        self.after(800, self._poll_messages)

    def _append_message(self, msg: dict):
        self._message_log.configure(state="normal")
        sid = msg.get("sender_id", "")
        sname = msg.get("sender_name", "未知")
        content = msg.get("content", "")
        mtime = msg.get("time", "")
        is_self = (sid == self.bot.bot_id)

        tag = f"[{'我' if is_self else sname}] #{self._message_count} {mtime}\n"
        self._message_log.insert("end", tag)
        self._message_log.insert("end", f"{content}\n\n")
        self._message_log.configure(state="disabled")
        self._message_log.see("end")
        self._message_count += 1

        # 限制行数
        try:
            lines = int(self._message_log.index("end-1c").split(".")[0])
            if lines > 500:
                self._message_log.configure(state="normal")
                self._message_log.delete("1.0", "100.0")
                self._message_log.configure(state="disabled")
        except Exception:
            pass

    def _on_refresh_messages(self):
        self._message_log.configure(state="normal")
        self._message_log.delete("1.0", "end")
        self._message_log.configure(state="disabled")
        self._message_count = 0
        self.bot._last_msg_idx = 0
        self._show_empty_message("消息已刷新\n等待新消息...")

    def _on_clear_messages(self):
        self._message_log.configure(state="normal")
        self._message_log.delete("1.0", "end")
        self._message_log.configure(state="disabled")
        self._message_count = 0
        self._show_empty_message("消息已清空")

    def _show_empty_message(self, text: str):
        self._message_log.configure(state="normal")
        self._message_log.delete("1.0", "end")
        self._message_log.insert("1.0", text)
        self._message_log.configure(state="disabled")

    # ═══════════════════════════════════════
    # 发送消息
    # ═══════════════════════════════════════

    def _set_mode(self, mode: str):
        self._current_mode = mode
        for m, btn in self._mode_chips.items():
            btn.configure(
                fg_color=COLORS["accent"] if m == mode else "transparent",
                text_color="#ffffff" if m == mode else COLORS["text_secondary"]
            )

        # 切换目标/次数行显隐
        show_target = mode in ("at", "multi-at", "dm")
        show_count = mode == "spam"

        if show_target:
            self._target_frame.pack(after=self._mode_chips["normal"].master,
                                    fill="x", padx=0, pady=(4, 0))
            labels = {"at": "用户ID (格式: ID:昵称)", "multi-at": "用户ID (逗号分隔)",
                      "dm": "目标用户 ID"}
            self._target_label.configure(text=labels.get(mode, "目标用户 ID"))
        else:
            self._target_frame.pack_forget()

        if show_count:
            self._count_frame.pack(after=self._mode_chips["normal"].master,
                                   fill="x", padx=0, pady=(4, 0))
            if self._current_mode == "at":
                self._count_frame.pack(after=self._target_frame, fill="x", padx=0, pady=(4, 0))
        else:
            self._count_frame.pack_forget()

    def _on_send_message(self):
        if not self._connected:
            self._show_toast("⚠️ 请先连接", "warning")
            return
        text = self._msg_text.get("1.0", "end-1c").strip()
        if not text and self._current_mode != "spam":
            self._show_toast("请输入消息内容", "warning")
            return

        target = self._target_entry.get().strip()
        try:
            count = int(self._count_entry.get().strip() or "5")
        except ValueError:
            count = 5

        self._btn_send.configure(state="disabled", text="⏳ 发送中...")

        def ok(msg):
            self._btn_send.configure(state="normal", text="📤 发送")
            self._show_toast(f"✅ {msg}", "success")
            if self._current_mode == "normal":
                self._msg_text.delete("1.0", "end")

        def err(msg):
            self._btn_send.configure(state="normal", text="📤 发送")
            self._show_toast(f"❌ {msg}", "error")

        self.bot.send_message(self._current_mode, text, target, count, 1.0,
                              on_success=ok, on_error=err)

    # ═══════════════════════════════════════
    # 贴纸操作
    # ═══════════════════════════════════════

    def _render_stickers(self, stickers: list):
        for btn in self._sticker_btns.values():
            btn.destroy()
        self._sticker_btns.clear()

        if not stickers:
            ctk.CTkLabel(self._sticker_grid, text="无匹配贴纸",
                         font=ctk.CTkFont(size=13),
                         text_color=COLORS["text_muted"]
                         ).grid(row=0, column=0, columnspan=4, pady=40)
            return

        for i, s in enumerate(stickers):
            r, c = divmod(i, 4)
            btn = ctk.CTkButton(
                self._sticker_grid, text=f"{s['emoji']} {s['name']}",
                width=105, height=70,
                fg_color=COLORS["bg_card"],
                border_color="transparent", border_width=2,
                font=ctk.CTkFont(size=12), corner_radius=10,
                text_color=COLORS["text_primary"],
                hover_color=COLORS["msg_self"],
                command=lambda k=s["key"]: self._select_sticker(k))
            btn.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")
            self._sticker_btns[s["key"]] = btn

        for col in range(4):
            self._sticker_grid.grid_columnconfigure(col, weight=1)

    def _select_sticker(self, key: str):
        self._selected_sticker = key
        for k, btn in self._sticker_btns.items():
            is_sel = (k == key)
            btn.configure(
                border_color=COLORS["accent"] if is_sel else "transparent",
                fg_color=COLORS["msg_self"] if is_sel else COLORS["bg_card"]
            )

    def _filter_stickers(self):
        q = self._sticker_search_var.get().lower()
        self._render_stickers(
            self._all_stickers if not q else
            [s for s in self._all_stickers if q in s["name"].lower() or q in s["key"].lower()]
        )

    def _on_send_sticker(self):
        if not self._connected:
            self._show_toast("⚠️ 请先连接", "warning")
            return
        if not self._selected_sticker:
            self._show_toast("请先选择一个贴纸", "warning")
            return

        text = self._sticker_text.get().strip()
        at_user = self._sticker_at.get().strip()
        self._btn_sticker_send.configure(state="disabled", text="⏳")

        def ok(msg):
            self._btn_sticker_send.configure(state="normal", text="发送")
            self._show_toast(f"✅ {msg}", "success")
            self._sticker_text.delete(0, "end")
            self._sticker_at.delete(0, "end")

        def err(msg):
            self._btn_sticker_send.configure(state="normal", text="发送")
            self._show_toast(f"❌ {msg}", "error")

        self.bot.send_sticker(self._selected_sticker, text=text, at_user=at_user,
                              on_success=ok, on_error=err)

    # ═══════════════════════════════════════
    # 成员操作
    # ═══════════════════════════════════════

    def _on_load_members(self):
        if not self._connected:
            self._show_toast("⚠️ 请先连接", "warning")
            return
        self._btn_member_refresh.configure(state="disabled", text="⏳")

        def ok(data):
            self._btn_member_refresh.configure(state="normal", text="🔄 刷新")
            if data and data.get("code") == 0:
                members = data.get("member_list", [])
                self._all_members = members
                self._render_members(members)
                self._show_toast(f"✅ 获取到 {len(members)} 个成员", "success")
            else:
                err_msg = (data or {}).get("message", "获取失败")
                self._show_toast(f"❌ {err_msg}", "error")

        def err(msg):
            self._btn_member_refresh.configure(state="normal", text="🔄 刷新")
            self._show_toast(f"❌ {msg}", "error")

        self.bot.load_members(on_result=ok, on_error=err)

    def _render_members(self, members: list):
        for w in self._member_list_frame.winfo_children():
            w.destroy()

        if not members:
            self._show_member_empty("暂无成员数据")
            return

        for m in members:
            uid = m.get("user_id", "")
            nick = m.get("nick_name", "未知")
            av = nick[0] if nick else "?"

            item = ctk.CTkFrame(self._member_list_frame, fg_color=COLORS["bg_card"],
                                corner_radius=8, height=44)
            item.pack(fill="x", padx=0, pady=1)
            item.pack_propagate(False)

            av_frame = ctk.CTkFrame(item, width=32, height=32,
                                    fg_color=COLORS["accent"], corner_radius=16)
            av_frame.pack(side="left", padx=10, pady=6)
            av_frame.pack_propagate(False)
            ctk.CTkLabel(av_frame, text=av, font=ctk.CTkFont(size=14, weight="bold"),
                         text_color="#ffffff").place(relx=0.5, rely=0.5, anchor="center")

            info = ctk.CTkFrame(item, fg_color="transparent")
            info.pack(side="left", fill="both", expand=True, padx=4, pady=4)
            ctk.CTkLabel(info, text=nick, font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=COLORS["text_primary"], anchor="w").pack(fill="x")
            ctk.CTkLabel(info, text=uid, font=ctk.CTkFont(size=11),
                         text_color=COLORS["text_muted"], anchor="w").pack(fill="x")

            # 点击复制
            def make_copy(u, n):
                return lambda e: self._copy_uid(u, n)

            for w in [item] + item.winfo_children():
                w.bind("<Button-1>", make_copy(uid, nick))
                if hasattr(w, 'winfo_children'):
                    for sub in w.winfo_children():
                        sub.bind("<Button-1>", make_copy(uid, nick))

    def _show_member_empty(self, text: str):
        for w in self._member_list_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(self._member_list_frame, text=text,
                     font=ctk.CTkFont(size=13),
                     text_color=COLORS["text_muted"]).pack(pady=20)

    def _filter_members(self):
        q = self._member_search_var.get().lower()
        self._render_members(
            self._all_members if not q else
            [m for m in self._all_members
             if q in (m.get("nick_name", "") + m.get("user_id", "")).lower()]
        )

    def _copy_uid(self, uid: str, nick: str):
        self.clipboard_clear()
        self.clipboard_append(uid)
        self._show_toast(f"已复制 {nick} 的ID", "success", 2000)

    def _on_auto_reply_toggle(self, *args):
        """自动回复开关切换时即时生效"""
        enabled = self._auto_reply_var.get()
        if enabled and self._connected:
            self.bot.enable_auto_reply()
            self._show_toast("🤖 自动回复已开启", "info", 2000)
        elif not enabled:
            self.bot.disable_auto_reply()
            if self._connected:
                self._show_toast("🔇 自动回复已关闭", "info", 2000)

    # ═══════════════════════════════════════
    # 设置操作
    # ═══════════════════════════════════════

    # ── 规则编辑器弹窗 ──

    def _open_rule_editor(self, rule: dict = None, index: int = None):
        """弹出规则编辑对话框。rule=None 表示新增，否则编辑已有规则。"""
        is_new = rule is None
        dialog = ctk.CTkToplevel(self)
        dialog.title("添加规则" if is_new else "编辑规则")
        dialog.geometry("440x400")
        dialog.configure(fg_color=COLORS["bg_secondary"])
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        inner = ctk.CTkFrame(dialog, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=16)

        # ── 匹配类型 ──
        ctk.CTkLabel(inner, text="匹配类型", font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 2))
        match_var = tk.StringVar(value=rule.get("match_type", "contains") if rule else "contains")
        match_menu = ctk.CTkOptionMenu(
            inner, values=["contains", "contains_any", "exact"],
            variable=match_var,
            fg_color=COLORS["input_bg"], button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            font=ctk.CTkFont(size=13), corner_radius=8, height=34)
        match_menu.pack(fill="x", pady=(0, 10))

        # ── 匹配文本 ──
        ctk.CTkLabel(inner, text="匹配文本 (contains_any 每行一个)",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 2))
        if rule and rule.get("match_type") == "contains_any":
            default_text = "\n".join(rule.get("patterns", []))
        elif rule:
            default_text = rule.get("pattern", "")
        else:
            default_text = ""
        pattern_text = ctk.CTkTextbox(inner, fg_color=COLORS["input_bg"],
                                      border_color=COLORS["border"], border_width=1,
                                      font=ctk.CTkFont(size=13), wrap="word",
                                      corner_radius=8, height=70)
        pattern_text.pack(fill="x", pady=(0, 10))
        pattern_text.insert("1.0", default_text)

        # ── 回复文本 ──
        ctk.CTkLabel(inner, text="回复文本", font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 2))
        reply_entry = ctk.CTkEntry(inner, fg_color=COLORS["input_bg"],
                                   border_color=COLORS["border"],
                                   font=ctk.CTkFont(size=13), corner_radius=8, height=34)
        reply_entry.pack(fill="x", pady=(0, 10))
        if rule:
            reply_entry.insert(0, rule.get("reply_text", ""))

        # ── 仅群聊 ──
        group_var = tk.BooleanVar(value=rule.get("group_only", False) if rule else False)
        ctk.CTkCheckBox(inner, text="仅群聊生效 (group_only)",
                        variable=group_var,
                        font=ctk.CTkFont(size=12),
                        text_color=COLORS["text_primary"],
                        fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                        border_color=COLORS["border"], checkmark_color="#fff"
                        ).pack(anchor="w", pady=(0, 12))

        # ── 按钮 ──
        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x")

        def save():
            mt = match_var.get()
            raw = pattern_text.get("1.0", "end-1c").strip()
            reply = reply_entry.get().strip()
            if not raw or not reply:
                self._show_toast("匹配文本和回复文本不能为空", "warning")
                return

            new_rule = {"match_type": mt, "reply_text": reply,
                        "group_only": group_var.get()}
            if mt == "contains_any":
                new_rule["patterns"] = [s.strip() for s in raw.split("\n") if s.strip()]
            else:
                new_rule["pattern"] = raw

            if is_new:
                self._current_rules.append(new_rule)
            else:
                self._current_rules[index] = new_rule

            self._render_rules()
            dialog.destroy()

        ctk.CTkButton(btn_row, text="保存", width=80, height=32,
                      fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                      font=ctk.CTkFont(size=12), corner_radius=8,
                      command=save).pack(side="right", padx=(6, 0))
        ctk.CTkButton(btn_row, text="取消", width=80, height=32,
                      fg_color="transparent", border_color=COLORS["border"], border_width=1,
                      font=ctk.CTkFont(size=12), corner_radius=8,
                      text_color=COLORS["text_primary"],
                      command=dialog.destroy).pack(side="right")

    def _render_rules(self):
        """刷新规则列表显示"""
        for w in self._rules_list_frame.winfo_children():
            w.destroy()

        if not self._current_rules:
            ctk.CTkLabel(self._rules_list_frame, text="暂无规则，点击「添加规则」创建",
                         font=ctk.CTkFont(size=12),
                         text_color=COLORS["text_muted"]
                         ).pack(pady=10)
            return

        for i, rule in enumerate(self._current_rules):
            card = ctk.CTkFrame(self._rules_list_frame, fg_color=COLORS["bg_card"],
                                corner_radius=8, border_color=COLORS["border"], border_width=1)
            card.pack(fill="x", pady=3)

            # 第一行：类型标签 + 匹配内容
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=10, pady=(8, 2))

            mt = rule.get("match_type", "contains")
            type_colors = {"contains": COLORS["success"], "contains_any": COLORS["warning"],
                           "exact": COLORS["accent"]}
            badge = ctk.CTkFrame(top, fg_color=type_colors.get(mt, COLORS["accent"]),
                                 corner_radius=4, width=60, height=20)
            badge.pack(side="left", padx=(0, 8))
            badge.pack_propagate(False)
            ctk.CTkLabel(badge, text=mt, font=ctk.CTkFont(size=10, weight="bold"),
                         text_color="#fff").place(relx=0.5, rely=0.5, anchor="center")

            # 匹配内容
            if mt == "contains_any":
                patterns = ", ".join(rule.get("patterns", []))
                if len(patterns) > 50:
                    patterns = patterns[:50] + "..."
            else:
                patterns = rule.get("pattern", "")
                if len(patterns) > 50:
                    patterns = patterns[:50] + "..."
            ctk.CTkLabel(top, text=patterns, font=ctk.CTkFont(size=12),
                         text_color=COLORS["text_primary"], anchor="w"
                         ).pack(side="left")

            # 标签
            if rule.get("group_only"):
                gb = ctk.CTkFrame(top, fg_color=COLORS["msg_self"], corner_radius=4)
                gb.pack(side="right", padx=(4, 0))
                ctk.CTkLabel(gb, text="仅群", font=ctk.CTkFont(size=9),
                             text_color=COLORS["accent"]).pack(padx=4, pady=1)

            # 第二行：回复文本 + 操作按钮
            bot = ctk.CTkFrame(card, fg_color="transparent")
            bot.pack(fill="x", padx=10, pady=(2, 8))

            reply = rule.get("reply_text", "")
            if len(reply) > 40:
                reply = reply[:40] + "..."
            ctk.CTkLabel(bot, text=f"→ {reply}", font=ctk.CTkFont(size=11),
                         text_color=COLORS["text_secondary"], anchor="w"
                         ).pack(side="left")

            # 编辑 / 删除
            ctk.CTkButton(bot, text="✎", width=28, height=22,
                          fg_color="transparent", border_color=COLORS["border"], border_width=1,
                          font=ctk.CTkFont(size=10), corner_radius=4,
                          text_color=COLORS["text_secondary"],
                          hover_color=COLORS["accent"],
                          command=lambda idx=i: self._open_rule_editor(
                              self._current_rules[idx], idx)
                          ).pack(side="right", padx=(4, 0))
            ctk.CTkButton(bot, text="✕", width=28, height=22,
                          fg_color="transparent", border_color=COLORS["border"], border_width=1,
                          font=ctk.CTkFont(size=10), corner_radius=4,
                          text_color=COLORS["danger"],
                          hover_color=COLORS["danger"],
                          command=lambda idx=i: self._on_delete_rule(idx)
                          ).pack(side="right", padx=4)

    def _on_add_rule(self):
        self._open_rule_editor()

    def _on_delete_rule(self, index: int):
        if 0 <= index < len(self._current_rules):
            del self._current_rules[index]
            self._render_rules()

    def _load_settings(self):
        try:
            c = self._load_config()
            self._setting_group_code.delete(0, "end")
            self._setting_group_code.insert(0, c.get("DEFAULT_GROUP_CODE", ""))
            self._setting_interval.delete(0, "end")
            self._setting_interval.insert(0, str(c.get("SPAM_INTERVAL", 1.0)))

            # 自动回复开关
            auto_enabled = c.get("AUTO_REPLY_ENABLED", False)
            self._auto_reply_var.set(auto_enabled)
            if auto_enabled and self._connected:
                self.bot.enable_auto_reply()
            else:
                self.bot.disable_auto_reply()

            self._setting_group_reply.delete(0, "end")
            self._setting_group_reply.insert(0, c.get("AUTO_REPLY_GROUP_TEXT", ""))
            self._setting_c2c_reply.delete(0, "end")
            self._setting_c2c_reply.insert(0, c.get("AUTO_REPLY_C2C_TEXT", ""))

            # 加载自动回复规则
            self._current_rules = [dict(r) for r in c.get("AUTO_REPLY_RULES", [])]
            self._render_rules()
        except Exception:
            pass

    def _on_save_settings(self):
        try:
            c = self._load_config()
            c["DEFAULT_GROUP_CODE"] = self._setting_group_code.get().strip()
            try:
                c["SPAM_INTERVAL"] = float(self._setting_interval.get().strip() or "1.0")
            except ValueError:
                c["SPAM_INTERVAL"] = 1.0
            c["AUTO_REPLY_GROUP_TEXT"] = self._setting_group_reply.get()
            c["AUTO_REPLY_C2C_TEXT"] = self._setting_c2c_reply.get()
            # 保存自动回复规则
            c["AUTO_REPLY_RULES"] = self._current_rules
            # 保存启用状态
            auto_enabled = self._auto_reply_var.get()
            c["AUTO_REPLY_ENABLED"] = auto_enabled
            # 同步到 BotController
            if auto_enabled and self._connected:
                self.bot.enable_auto_reply()
            else:
                self.bot.disable_auto_reply()
            self._save_config(c)
            self._show_toast("✅ 设置已保存", "success")
        except Exception as e:
            self._show_toast(f"❌ 保存失败: {e}", "error")

    def _load_config(self) -> dict:
        cp = os.path.join(os.path.dirname(__file__), "config.json")
        try:
            with open(cp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_config(self, config: dict):
        cp = os.path.join(os.path.dirname(__file__), "config.json")
        with open(cp, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

    # ═══════════════════════════════════════
    # 关闭
    # ═══════════════════════════════════════

    def _on_close(self):
        self.bot.stop()
        self.destroy()


# ═══════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════
def main():
    app = YuanbaoGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
