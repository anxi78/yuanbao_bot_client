# -*- coding: utf-8 -*-
"""
示例插件 —— 插件系统模板

用法：
1. 将本目录（或复制本目录）放入 plugins/ 文件夹，bot 启动时自动加载。
2. 每个插件是一个独立目录，必须包含 plugin.json（元数据）和 main.py（入口）。
3. 插件入口必须定义 setup(api) 或 register(api) 函数，在函数中注册命令和消息监听。

可用 API（api 对象）：
    # 发送消息
    await api.send_group_message(text, at_user=None, at_nickname=None, target_group=None)
    await api.send_dm_message(to_account, text)
    await api.send_at_message(user_id, text, nickname="")
    await api.send_multi_at_message(text, at_users)
    await api.send_sticker_message(sticker_name, text="", ...)
    await api.send_image_message(image_paths)
    await api.send_file_message(file_path)
    await api.send_video(*args, **kwargs)

    # 群信息
    await api.get_members()      # 获取成员列表
    await api.get_group_info()   # 获取群信息

    # 属性
    api.group_code   # 当前群号（可写）
    api.user_db      # 用户 ID -> 昵称 映射
    api.connected    # 是否已连接
    api.bot_id       # 机器人自身 ID
    api.STICKERS     # 贴纸表
    api.sender       # 底层 SpamSender 实例（开放全部能力）
"""


def setup(api):
    api.log("示例插件加载成功，输入 /ping 测试")

    # ── 注册命令：@api.command(命令, 描述) ──
    @api.command("/ping", "回复 pong（插件示例）")
    async def ping(args):
        await api.send_group_message(f"pong! 参数: {args or '(无)'}")

    @api.command("/pluginhelp", "显示插件 API 用法（插件示例）")
    async def pluginhelp(args):
        await api.send_group_message(
            "插件API示例：send_group_message / send_dm_message / "
            "send_at_message / send_multi_at_message / send_sticker_message / "
            "send_image_message / send_file_message / get_members / get_group_info"
        )

    # ── 注册消息监听：@api.on_message ──
    # 回调签名: async def (push_json: dict, cache_entry: dict)
    # cache_entry 包含: time, sender_id, sender_name, group_code, content, msg_type, msg_id, msg_seq
    @api.on_message
    async def on_msg(push_json, cache_entry):
        content = cache_entry.get("content", "")
        # 只在群里、且不是机器人自己的消息时响应
        if content and cache_entry.get("group_code") and cache_entry.get("sender_id") != api.bot_id:
            if "插件测试" in content:
                api.log(f"收到关键词消息: {content}")
                await api.send_group_message(
                    f"@{cache_entry.get('sender_name', '')} 收到！",
                    at_user=cache_entry.get("sender_id"),
                    at_nickname=cache_entry.get("sender_name", ""),
                )


# 也支持 register 作为入口函数名（二选一）
# def register(api):
#     ...
