# -*- coding: utf-8 -*-
"""插件系统：自动扫描 plugins/ 目录下的插件仓库，加载并注册命令到主程序。

插件目录结构：
    plugins/
    └── <插件目录>/
        ├── plugin.json     # 插件元数据（必需）
        └── main.py         # 插件入口（必需，可通过 plugin.json 的 "main" 字段改名）

plugin.json 格式:
    {
        "name": "插件显示名",
        "version": "1.0.0",
        "description": "插件描述",
        "main": "main.py"
    }

插件入口 main.py 必须定义一个 setup(api) 或 register(api) 函数：
    def setup(api):
        @api.command("/hello", "发送问候")
        async def hello(args):
            await api.send_group_message(f"你好，{args or '世界'}！")

        @api.on_message
        async def on_msg(push_json, cache_entry):
            api.log(f"收到消息: {cache_entry.get('content')}")
"""

import asyncio
import importlib.util
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

PLUGINS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins")


class PluginAPI:
    """开放给插件的 API 接口，包装 SpamSender 实例并提供常用能力。

    插件可通过 `api.sender` 访问底层 SpamSender 的所有属性和方法，
    也可以通过下面封装的便捷方法直接发送消息。
    """

    def __init__(self, sender: Any, manager: "PluginManager", plugin_name: str) -> None:
        self._sender = sender
        self._manager = manager
        self.plugin_name = plugin_name

    # ── 底层访问 ──
    @property
    def sender(self) -> Any:
        """直接访问底层 SpamSender 实例（完全开放）"""
        return self._sender

    # ── 常用属性 ──
    @property
    def group_code(self) -> Optional[str]:
        return self._sender.group_code

    @group_code.setter
    def group_code(self, value: str) -> None:
        self._sender.group_code = value

    @property
    def user_db(self) -> Dict[str, str]:
        """用户数据库 {user_id: nickname}"""
        return self._sender.user_db

    @property
    def connected(self) -> bool:
        return self._sender.connected

    @property
    def bot_id(self) -> Optional[str]:
        return self._sender.bot_id

    @property
    def STICKERS(self) -> dict:
        return self._sender.STICKERS

    @property
    def msg_cache(self) -> List[dict]:
        return self._sender.msg_cache

    # ── 发送 API ──
    async def send_group_message(self, text: str, at_user: str = None, at_nickname: str = None, target_group: str = None) -> bool:
        """发送群消息，支持可选艾特"""
        return await self._sender.send_group_message(text, at_user=at_user, at_nickname=at_nickname, target_group=target_group)

    async def send_dm_message(self, to_account: str, text: str) -> bool:
        """发送私聊消息"""
        return await self._sender.send_dm_message(to_account, text)

    async def send_at_message(self, user_id: str, text: str, nickname: str = "") -> bool:
        """艾特指定用户发送消息（昵称可省略，自动从 user_db 查找）"""
        at_nick = nickname or self._sender.user_db.get(user_id, user_id)
        return await self._sender.send_group_message(text, at_user=user_id, at_nickname=at_nick)

    async def send_multi_at_message(self, text: str, at_users: list) -> bool:
        """批量艾特，at_users: [(user_id, nickname), ...]"""
        return await self._sender.send_multi_at_message(text, at_users)

    async def send_sticker_message(self, sticker_name: str, text: str = "", at_user: str = None, at_nickname: str = None, target_group: str = None) -> bool:
        """发送贴纸（纯贴纸 / 贴纸+文字 / 贴纸+艾特+文字）"""
        return await self._sender.send_sticker_message(sticker_name, text=text, at_user=at_user, at_nickname=at_nickname, target_group=target_group)

    async def send_image_message(self, image_paths: list) -> bool:
        """发送图片（本地路径列表）"""
        return await self._sender.send_images_multi(image_paths)

    async def send_file_message(self, file_path: str) -> bool:
        """发送文件"""
        return await self._sender.send_file(file_path)

    async def send_video(self, *args, **kwargs) -> bool:
        """发送视频"""
        return await self._sender.send_video(*args, **kwargs)

    # ── 群信息 API ──
    async def get_members(self) -> Optional[dict]:
        """获取群成员列表（原始响应）"""
        return await self._sender.send_get_members_request()

    async def get_group_info(self) -> Optional[dict]:
        """查询当前群信息"""
        return await self._sender.send_query_group_info_request()

    # ── 命令注册 ──
    def command(self, cmd: str, description: str) -> Callable:
        """装饰器：注册一个插件命令。

        用法:
            @api.command("/hello", "发送问候")
            async def hello(args: str): ...
        """
        def decorator(func: Callable) -> Callable:
            self._manager.register_command(cmd, func, description, self.plugin_name)
            return func
        return decorator

    # ── 消息监听 ──
    def on_message(self, callback: Callable) -> Callable:
        """注册群消息监听器（支持直接装饰器用法）。

        回调签名: async def (push_json: dict, cache_entry: dict) -> None
        其中 cache_entry 含 sender_id/sender_name/group_code/content/msg_id 等字段。
        """
        self._manager.register_message_listener(self.plugin_name, callback)
        return callback

    # ── 工具 ──
    def log(self, msg: str) -> None:
        """打印带插件前缀的日志"""
        print(f"\033[36m[插件:{self.plugin_name}]\033[0m {msg}")


class PluginManager:
    """扫描并加载 plugins/ 目录下的插件，统一管理命令注册与消息监听。

    on_command_registered: 可选回调，当插件注册新命令时被调用，用于
    同步更新主程序的 COMMANDS / COMMAND_DESCRIPTIONS（自动补全与帮助）。
    """

    def __init__(self, sender: Any, plugins_dir: str = PLUGINS_DIR,
                 on_command_registered: Optional[Callable[[str, str], None]] = None) -> None:
        self.sender = sender
        self.plugins_dir = plugins_dir
        self._on_command_registered = on_command_registered
        self.plugins: List[dict] = []
        self._handlers: Dict[str, Callable] = {}
        self._handler_plugin: Dict[str, str] = {}
        self._descriptions: Dict[str, str] = {}
        self._message_listeners: List[Tuple[str, Callable]] = []

    # ── 扫描 ──
    def scan(self) -> List[dict]:
        """扫描 plugins 目录，返回含 plugin.json 的插件目录信息"""
        if not os.path.isdir(self.plugins_dir):
            return []
        found: List[dict] = []
        for entry in sorted(os.listdir(self.plugins_dir)):
            if entry.startswith((".", "_")):
                continue
            dir_path = os.path.join(self.plugins_dir, entry)
            if not os.path.isdir(dir_path):
                continue
            meta_path = os.path.join(dir_path, "plugin.json")
            if not os.path.isfile(meta_path):
                continue
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                continue
            if not isinstance(meta, dict):
                continue
            found.append({"name": entry, "path": dir_path, "meta": meta})
        return found

    # ── 加载 ──
    def load_all(self) -> None:
        """加载所有可用的插件（单个失败不影响其他）"""
        scanned = self.scan()
        if not scanned:
            print("[插件系统] 未发现插件（将插件仓库放到 plugins/ 目录即可自动加载）")
            return
        for info in scanned:
            try:
                self._load_one(info)
            except Exception as e:
                print(f"[插件系统] 加载插件 [{info['name']}] 失败: {e}")

    def _load_one(self, info: dict) -> "PluginAPI":
        main_file = info["meta"].get("main", "main.py")
        main_path = os.path.join(info["path"], main_file)
        if not os.path.isfile(main_path):
            raise FileNotFoundError(f"缺少入口文件 {main_file}")
        module_name = f"yb_plugin_{info['name'].replace('-', '_').replace('.', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, main_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法创建插件模块: {main_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        api = PluginAPI(self.sender, self, info["name"])
        setup_fn = getattr(module, "setup", None) or getattr(module, "register", None)
        if setup_fn is None:
            raise RuntimeError("插件必须定义 setup(api) 或 register(api) 函数")
        setup_fn(api)

        self.plugins.append({
            "name": info["name"],
            "path": info["path"],
            "meta": info["meta"],
            "module": module,
            "api": api,
        })
        pname = info["meta"].get("name", info["name"])
        pver = info["meta"].get("version", "?")
        self.log(f"已加载: {pname} v{pver}")
        return api

    # ── 命令管理 ──
    def register_command(self, cmd: str, handler: Callable, description: str, plugin_name: str) -> None:
        """注册插件命令（会同步触发 on_command_registered 回调更新自动补全）"""
        if cmd in self._handlers:
            print(f"[插件系统] 命令 {cmd} 已被其他插件占用，{plugin_name} 注册失败")
            return
        self._handlers[cmd] = handler
        self._handler_plugin[cmd] = plugin_name
        self._descriptions[cmd] = description
        if self._on_command_registered:
            try:
                self._on_command_registered(cmd, description)
            except Exception:
                pass

    @property
    def command_items(self) -> List[Tuple[str, Callable]]:
        """所有插件命令，按长度降序（长命令优先匹配）"""
        return sorted(self._handlers.items(), key=lambda kv: len(kv[0]), reverse=True)

    def command_help_items(self) -> List[Tuple[str, str]]:
        """插件命令帮助条目 [(命令, 描述), ...]"""
        return [(cmd, self._descriptions.get(cmd, "")) for cmd, _ in self.command_items]

    async def dispatch(self, raw: str) -> bool:
        """尝试分发命令给插件，命中则执行并返回 True"""
        raw = raw.strip()
        for cmd, handler in self.command_items:
            if raw == cmd or raw.startswith(cmd + " "):
                args = raw[len(cmd):].strip()
                try:
                    result = handler(args)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    print(f"[插件:{self._handler_plugin.get(cmd, '?')}] 命令 {cmd} 执行出错: {e}")
                    import traceback
                    traceback.print_exc()
                return True
        return False

    # ── 消息监听 ──
    def register_message_listener(self, plugin_name: str, callback: Callable) -> None:
        self._message_listeners.append((plugin_name, callback))

    def hook_push_message(self, original_callback: Optional[Callable] = None) -> Callable:
        """包装 sender.on_push_message，把每条消息多路转发给原回调 + 所有插件监听器。

        返回的包装函数签名: async (push_json: dict, cache_entry: dict) -> None
        """
        async def _dispatch(push_json: dict, cache_entry: dict) -> None:
            if original_callback:
                try:
                    result = original_callback(push_json, cache_entry)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass
            for plugin_name, cb in list(self._message_listeners):
                try:
                    result = cb(push_json, cache_entry)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    print(f"[插件:{plugin_name}] 消息监听出错: {e}")
        return _dispatch

    # ── 工具 ──
    def log(self, msg: str) -> None:
        print(f"[插件系统] {msg}")
