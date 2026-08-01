# 元宝 Bot 插件 API 文档

插件系统允许在不修改 `sender.py` 的情况下扩展功能：把插件放到 `plugins/` 目录，bot 启动时自动扫描加载，插件注册的命令会自动进入自动补全和 `/help`，插件也可以监听群消息并调用发送 API。

## 插件结构

```
plugins/
└── <插件目录名>/
    ├── plugin.json     # 插件元数据（必需）
    └── main.py         # 插件入口（必需）
```

### plugin.json

```json
{
    "name": "插件显示名",
    "version": "1.0.0",
    "description": "插件描述",
    "main": "main.py",
    "author": "你的名字（可选）"
}
```

- `main` 指定入口文件，默认 `main.py`
- `version` 和 `description` 在启动时打印展示

### 入口文件

入口必须定义 `setup(api)` 或 `register(api)` 函数（二选一），bot 启动时调用并传入 `PluginAPI` 实例：

```python
def setup(api):
    @api.command("/hello", "发送问候")
    async def hello(args):
        await api.send_group_message(f"你好，{args or '世界'}！")

    @api.on_message
    async def on_msg(push_json, cache_entry):
        content = cache_entry.get("content", "")
        if "你好" in content:
            await api.send_group_message("我听到有人打招呼~")
```

---

## PluginAPI 对象

`setup` 函数收到的 `api` 是 `PluginAPI` 实例，封装了常用能力，同时可通过 `api.sender` 访问底层 `SpamSender` 的全部能力。

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `api.sender` | `SpamSender` | 底层发送器实例（完全开放） |
| `api.group_code` | `str` | 当前目标群号（可读写） |
| `api.user_db` | `dict` | 用户数据库 `{user_id: nickname}` |
| `api.connected` | `bool` | WebSocket 是否已连接 |
| `api.bot_id` | `str` | 机器人自身 ID |
| `api.STICKERS` | `dict` | 贴纸表 `{贴纸名: {sticker_id, package_id, ...}}` |
| `api.msg_cache` | `list` | 最近消息缓存（最多 1000 条 `cache_entry`） |
| `api.plugin_name` | `str` | 当前插件目录名 |

### 发送消息

```python
await api.send_group_message(text, at_user=None, at_nickname=None, target_group=None)
```
发送群消息，可选艾特。`target_group` 指定目标群号（默认当前群）。

```python
await api.send_dm_message(to_account, text)
```
发送私聊消息。

```python
await api.send_at_message(user_id, text, nickname="")
```
艾特指定用户发送。`nickname` 省略时自动从 `user_db` 查找。

```python
await api.send_multi_at_message(text, at_users)
```
批量艾特，`at_users` 为 `[(user_id, nickname), ...]` 列表，自动按每 20 人分片发送。

```python
await api.send_sticker_message(sticker_name, text="", at_user=None, at_nickname=None, target_group=None)
```
发送贴纸，支持纯贴纸 / 贴纸+文字 / 贴纸+艾特+文字。`sticker_name` 用 `api.STICKERS` 中的贴纸名。

```python
await api.send_image_message(image_paths)
```
发送图片，`image_paths` 为本地路径列表。

```python
await api.send_file_message(file_path)
```
发送文件。

```python
await api.send_video(video_path, video_second=0, video_format="", thumb_path="", thumb_width=0, thumb_height=0)
```
发送视频（自动上传 COS）。参数均可选，可只传 `video_path`。

所有发送方法返回 `bool`，表示发送是否成功。

### 查询群信息

```python
await api.get_members()
```
获取群成员列表，返回原始响应 dict。

```python
await api.get_group_info()
```
查询当前群信息（群名、群主、人数等）。

### 命令注册

```python
@api.command(cmd, description)
```
注册一个插件命令。装饰的函数必须是 `async def handler(args)`，`args` 是命令后剩余的参数字符串（已去首尾空格）。

- 注册后命令自动进入自动补全和 `/help` 插件命令区
- 最长前缀匹配：输入 `cmd` 或 `cmd 参数` 时触发
- 命令与内置命令、其他插件命令冲突时注册失败并打印提示

### 消息监听

```python
@api.on_message
async def on_msg(push_json, cache_entry):
    ...
```
注册群消息监听器。每条群消息都会触发（同时也会照常走原有自动回复逻辑）。回调收到两个参数：

**`push_json`**：原始推送数据 dict。

**`cache_entry`**：标准化后的消息字典，字段如下：

| 字段 | 类型 | 说明 |
|------|------|------|
| `time` | `str` | 消息时间（格式 `YYYY-MM-DD HH:MM:SS`） |
| `sender_id` | `str` | 发送者 ID |
| `sender_name` | `str` | 发送者昵称 |
| `group_code` | `str` | 群号 |
| `content` | `str` | 文本内容（可能为空字符串） |
| `msg_type` | `str` | 消息类型（`callback_command`） |
| `msg_id` | `str` | 消息 ID |
| `msg_seq` | `int` | 消息序号 |
| `media_info` | `dict` | 媒体信息（图片/文件等，无则为空 dict） |

监听器内抛出的异常会被捕获并打印，不会影响其他插件或主程序。

### 日志工具

```python
api.log("任意文本")
```
以 `[插件:<插件名>]` 前缀打印到控制台（青色）。

---

## 底层访问（开放全部能力）

`api.sender` 是 `SpamSender` 实例，任何插件可绕过封装直接使用：

```python
sender = api.sender
await sender.send_group_message("直接调用底层方法")
await sender.send_raw(head, data)          # 发送原始 ConnMsg
await sender.send_request(cmd, data)       # 发送请求并等待响应
await sender.send_reply_spam(seq, text, count)  # 引用刷屏
await sender.trigger_ai_image(prompt)      # 触发 AI 图片生成
```

常见底层方法与属性：
- `send_group_message(text, at_user, at_nickname, target_group)`
- `send_dm_message(to_account, text)`
- `send_multi_at_message(text, at_users)`
- `send_sticker_message(sticker_name, text, at_user, at_nickname, target_group)`
- `send_images_multi(image_paths)`
- `send_file(file_path)` / `send_video(...)`
- `send_get_members_request()` / `send_query_group_info_request()`
- `send_reply_spam(seq, text, count)` / `send_at_spam(user_id, text, count)`
- `user_db` / `msg_cache` / `bot_id` / `connected` / `group_code`

---

## 完整示例

```python
# plugins/myplugin/main.py
def setup(api):
    api.log("我的插件加载成功")

    @api.command("/gtime", "获取当前时间（示例）")
    async def gtime(args):
        import time
        await api.send_group_message(f"现在时间: {time.strftime('%H:%M:%S')}")

    @api.on_message
    async def on_msg(push_json, cache_entry):
        if cache_entry.get("sender_id") == api.bot_id:
            return  # 忽略机器人自己的消息
        content = cache_entry.get("content", "")
        if "晚安" in content:
            await api.send_at_message(
                cache_entry["sender_id"],
                "晚安好梦~",
                cache_entry.get("sender_name", ""),
            )
```

## 注意事项

- 命令处理函数必须是 **async**，否则无法被 `await`
- 插件监听器与自动回复逻辑并存：先执行原回调，再依次执行各插件监听器
- 单个插件加载失败不影响其他插件（打印错误后继续）
- 插件命令未命中时会作为普通消息发送到群里，注册命令时请确认前缀唯一