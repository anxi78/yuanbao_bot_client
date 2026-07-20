# AGENTS.md — 元宝 Bot 客户端

## 项目概述

**元宝 Bot 发送器**是一个纯 Python WebSocket 客户端，用于连接腾讯元宝 Bot 平台（基于 OpenClaw 插件协议），实现 QQ 群消息收发、群管理、自动回复、AI 图片生成等功能的 CLI 工具。

- **语言**: Python 3.13+
- **通信协议**: WebSocket + 自定义 Protobuf（微信 iLink 协议层）
- **认证方式**: HMAC-SHA256 签名
- **依赖**: `websockets`, `requests`, `cos-python-sdk-v5`, `prompt_toolkit`, `Pillow`
- **外部服务**: 腾讯云 COS（对象存储）

## 项目架构

| 文件 | 说明 |
|------|------|
| `sender.py` (3829 行) | 核心文件 — 包含全部逻辑 |
| `config.json` | 运行时配置 |
| `config.example.json` | 配置模板 |
| `requirements.txt` | Python 依赖 |
| `install.sh` | 一键安装脚本 |
| `bot.log` | 运行时日志（仅 debug，不输出到控制台） |

## sender.py 内部结构

sender.py 按顺序包含以下模块：

### 1. 基础设施
- **日志配置**: 日志写入 `bot.log`，不传播到控制台
- **命令自动补全**: `CommandAutoSuggest` 类，基于 `prompt_toolkit`，输入 `/` 时自动建议命令
- **快捷键**: Ctrl+Q 接受补全建议，Ctrl+D 丢弃当前行
- **ESC 中断系统**: 后台异步任务监听 stdin 的 `\x1b` 字节，用于中断刷屏操作。支持 `termios tty.setcbreak`（Unix）和 `loop.add_reader`/`run_in_executor` 两种方案

### 2. Protobuf 编解码（约 250 行）
两套实现：
- **顶层函数** (`pb_varint`, `pb_tag`, `pb_string`, `pb_bytes`, `pb_int32`, `pb_uint32`, `pb_msg`, `pb_decode_varint`, `pb_decode_delimited`, `pb_decode_msg`) — 编码和解码 protobuf 消息
- **SimpleProtobufCodec 类** — 静态方法封装，供 SpamSender 使用

消息类型结构（ConnMsg 层）：
- field 1: `head` (ConnHead) — 包含 cmdType/1, cmd/2, seqNo/3, msgId/4, module/5
- field 2: `data` (raw bytes) — 具体业务消息

### 3. 协议编码函数
- `encode_auth_bind()` / `SimpleProtobufCodec.encode_auth_bind_req()` — 鉴权绑定请求
- `encode_send_group_req()` / `SimpleProtobufCodec.encode_send_group_msg_req()` — 群消息
- `encode_send_c2c_req()` / `SimpleProtobufCodec.encode_send_c2c_msg_req()` — 私聊消息
- `encode_tim_image_elem()` — 图片元素
- `encode_tim_face_elem()` — 贴纸元素
- `encode_tim_file_elem()` — 文件元素
- `encode_get_group_member_list_req()` — 成员列表请求
- `decode_send_group_rsp()`, `decode_send_c2c_rsp()`, `decode_get_group_member_list_rsp()` — 响应解码

### 4. SpamSender 类（主要类）
核心类，管理 WebSocket 连接和消息发送。

**关键属性**:
- `appKey`, `appSecret`, `api_domain`, `ws_url` — 连接凭证
- `group_code` — 当前目标群
- `ws` — WebSocket 连接对象
- `seq_no` — 序列号（递增）
- `recent_messages` — 最近消息缓存（deque，最多 500 条）
- `msg_id_to_seq` — 消息 ID 到序号映射
- `auto_reply_text`, `auto_reply_on`, `auto_reply_only_at` — 自动回复状态
- `auto_reply_proxy_queue` — 代理模式队列 (asyncio.Queue)
- `spam_interval` — 刷屏间隔
- `user_nicknames` — 用户昵称缓存
- `nickname_to_user` — 昵称到用户 ID 的反向映射
- `connected` — 连接标志
- `_temp_app_key`, `_temp_app_secret` — 临时认证凭据（/auth 命令切换，不写 config.json）

**关键方法**:
| 方法 | 功能 |
|------|------|
| `connect()` | 建立 WebSocket 连接，发送 auth-bind 认证 |
| `disconnect()` | 断开连接 |
| `send_raw(head, data)` | 发送原始 ConnMsg |
| `send_request(cmd, data)` | 发送请求并等待响应 |
| `recv_loop()` | 持续接收消息推送循环 |
| `send_group_message(text, ref_msg_id="")` | 发送群消息（支持引用回复） |
| `send_sticker_message(sticker_id/find, ...)` | 发送贴纸消息 |
| `send_image_message(url_list)` | 发送图片消息 |
| `send_file_message(url, file_name)` | 发送文件消息 |
| `send_dm_message(to_user, text)` | 发送私聊消息 |
| `send_big_text_message(text, font_size)` | 发送放大 LaTeX 文本 |
| `format_at_message(user_id, text)` | 格式化艾特消息 |
| `send_at_message(user_id, text)` | 发送艾特消息 |
| `send_combo_sticker_at_message(sticker_name, user_id, text)` | 发送贴纸+艾特+文字组合 |
| `send_spam(text, count)` | 刷屏 |
| `send_at_spam(user_id, text, count)` | 艾特刷屏 |
| `send_sticker_spam(sticker_id, count)` | 贴纸刷屏 |
| `send_dm_spam(to_user, text, count)` | 私聊刷屏 |
| `send_reply_spam(seq, text, count)` | 引用刷屏 |
| `get_group_member_list()` | 获取成员列表 |
| `query_group_info()` | 查询群信息 |
| `handle_push(data)` | 处理推送消息（自动回复/代理转发/图片检测） |
| `handle_auto_reply(sender_id, text)` | 处理自动回复逻辑 |
| `handle_proxy_reply(sender_id, text)` | 处理代理模式转发 |
| `handle_image_push(data)` | 检测和下载 AI 生成图片 |
| `start_proxy_consumer()` | 启动代理模式消费者（FIFO 队列） |
| `trigger_ai_image(prompt)` | 触发 AI 图片生成 |
| `set_auth(app_key, app_secret)` | 临时切换认证凭据（仅本次运行生效） |

### 5. 自动重连机制
- `_reconnect_loop()` — 后台任务，WebSocket 断开时自动重连
- 退避策略：1s → 2s → 4s → 8s → 16s
- 重连后自动恢复 `recv_loop` 和心跳

### 6. 交互式循环 (main/interactive_mode)
使用 `prompt_toolkit` 提供交互式 CLI，支持 30+ 命令的解析和分发。

命令处理流程：
1. 输入内容依次匹配各命令前缀
2. 命中 `/auth` → 交互式输入 APP_KEY/APP_SECRET，调用 `set_auth()` 临时切换凭据并自动重连
3. 命中 `/auto` → 自动回复/代理模式开关
4. 命中其他命令 → 按相应逻辑处理
5. 无匹配 → 作为普通消息发送

## 协议细节

### 连接流程
1. WebSocket 连接建立
2. 发送 `auth-bind` 请求（CMD_TYPE_REQUEST），携带 biz_id + uid + token（HMAC-SHA256 签名）
3. 收到 `auth-bind` 响应（CMD_TYPE_RESPONSE），状态码 0 表示成功
4. 之后心跳定期发送 `ping`（CMD_TYPE_PUSH）

### 签名算法
```
source = f"{appKey}:{appSecret}"
token = base64(hmac_sha256(source.encode(), appKey.encode()))
```

### 心跳机制
每 30 秒发送 `ping`，约 70 秒超时断开，自动触发重连。

### 代理模式 (yb)
- 将群内所有消息转发到「元宝」Bot（用户 ID: `szUvRH8s4ekettawNjDREmAG4W7h+Lhb8Sy9tq/otZU=`）
- 元宝的回复通过引用消息回传到原群
- 使用 FIFO 队列排队处理，避免并发冲突
- 启动代理时自动初始化队列消费者

### AI 图片生成
- 向配置的 `IMAGE_GROUP_CODE` 群发送 `/ai-image <prompt>` 给元宝
- 元宝回复文字后等待 2 秒检测后续消息中是否包含图片
- 检测到图片后下载到本地 `downloads/` 目录

## 配置项

```json
{
    "APP_KEY": "appKey",
    "APP_SECRET": "appSecret",
    "API_DOMAIN": "bot.yuanbao.tencent.com",
    "WS_URL": "wss://bot-wss.yuanbao.tencent.com/wss/connection",
    "DEFAULT_GROUP_CODE": "默认群号",
    "SPAM_INTERVAL": 1.0,
    "IMAGE_GROUP_CODE": "AI图片(代理)生成群号"
}
```

## 构建与运行

### 启动
```bash
python sender.py
```

### 一键安装
```bash
curl -sSL https://raw.githubusercontent.com/anxi78/yuanbao_bot_client/main/install.sh | bash
```

安装后可直接使用 `ybbot` 命令启动（`$HOME/.local/bin/ybbot`）。

### 依赖
```txt
requests>=2.28.0
websockets>=11.0.0
cos-python-sdk-v5>=1.9.0
prompt_toolkit>=3.0.0
Pillow>=10.0.0
```

## 命令参考

所有 30+ 个命令及其用法，详见 `README.md`。

## 开发约定

- **编码风格**: `sender.py` 使用函数式 + 类混合风格，protobuf 编码有冗余（两套实现），维护时注意一致性
- **日志**: 使用 `logging.getLogger("yuanbao_bot")`，`bot.log` 记录 debug 信息，不干扰控制台输出
- **ESC 中断**: 涉及循环发送的操作（spam 系列命令）必须适配 ESC 中断机制
- **配置加载**: 硬编码路径为 `$HOME/yuanbao_bot_client/config.json`
- **版本号**: `__version__ = "1.1.0"` 定义在 sender.py 中
- **Git**: 主分支 `main`，远程仓库 `origin`（`git@github.com:anxi78/yuanbao_bot_client.git`）
