import sys
import asyncio

sys.path.insert(0, "/data/data/com.termux/files/home/yuanbao_bot_client")
from plugin_loader import PluginManager


class FakeSender:
    """模拟 SpamSender 的最小接口，供插件系统测试。"""

    def __init__(self):
        self.group_code = "test_group"
        self.user_db = {"u1": "小明", "u2": "小红"}
        self.connected = True
        self.bot_id = "bot123"
        self.STICKERS = {}
        self.msg_cache = []
        self.sent = []

    async def send_group_message(self, text, at_user=None, at_nickname=None, target_group=None):
        self.sent.append(("group", text, at_user, at_nickname, target_group))
        return True

    async def send_dm_message(self, to_account, text):
        self.sent.append(("dm", to_account, text))
        return True

    async def send_multi_at_message(self, text, at_users):
        self.sent.append(("multiat", text, at_users))
        return True

    async def send_sticker_message(self, *a, **k):
        self.sent.append(("sticker", a, k))
        return True

    async def send_images_multi(self, paths):
        self.sent.append(("image", paths))
        return True

    async def send_file(self, path):
        self.sent.append(("file", path))
        return True

    async def send_video(self, *a, **k):
        self.sent.append(("video", a, k))
        return True

    async def send_get_members_request(self):
        return {"members": [{"id": "u1", "name": "小明"}]}

    async def send_query_group_info_request(self):
        return {"group_info": {"name": "测试群"}}


async def main():
    # 模拟 sender.py 的全局 COMMANDS / COMMAND_DESCRIPTIONS
    COMMANDS = []
    COMMAND_DESCRIPTIONS = {}

    def on_cmd_registered(cmd, desc):
        if cmd and cmd not in COMMANDS:
            COMMANDS.append(cmd)
            COMMANDS.sort(key=len, reverse=True)
        if desc:
            COMMAND_DESCRIPTIONS[cmd] = desc

    sender = FakeSender()
    pm = PluginManager(sender, on_command_registered=on_cmd_registered)
    pm.load_all()

    assert pm.plugins, "插件应被加载"
    print("已加载插件:", [p["name"] for p in pm.plugins])
    print("注册命令:", [c for c, _ in pm.command_items])
    print("自动补全 COMMANDS:", COMMANDS)
    print("帮助项:", pm.command_help_items())

    # ── 测试命令分发 ──
    assert await pm.dispatch("/ping hello") is True, "/ping 应命中"
    assert await pm.dispatch("/pluginhelp") is True, "/pluginhelp 应命中"
    assert await pm.dispatch("/unregistered_cmd") is False, "未注册命令不应命中"
    print("命令分发测试通过")

    # ── 测试消息监听 + 原回调 hook ──
    orig_called = []

    async def orig_cb(push_json, cache_entry):
        orig_called.append(True)

    hooked = pm.hook_push_message(orig_cb)
    await hooked({}, {"content": "插件测试", "group_code": "g1",
                      "sender_id": "u1", "sender_name": "小明"})
    assert orig_called, "原回调应被调用"
    print("消息监听 hook 测试通过")

    group_sends = [s for s in sender.sent if s[0] == "group"]
    assert len(group_sends) >= 3, f"应有至少 3 次群消息发送，实际 {len(group_sends)}"
    print("发送记录数量:", len(sender.sent))
    for s in sender.sent:
        print("  发送:", s)

    print("\n=== 插件系统集成测试全部通过 ===")


asyncio.run(main())
