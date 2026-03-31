# 元宝 Bot WebSocket 客户端

元宝 Bot 的 WebSocket 客户端，支持自动回复、主动发送消息、艾特功能等。

## 安装依赖

```bash
pip install -r requirements.txt
```

依赖：
- requests >= 2.28.0
- websockets >= 11.0.0

## 配置

编辑 `config.py` 文件，设置你的 Bot 凭证：

```python
APP_KEY = "your_app_key"
APP_SECRET = "your_app_secret"
```

Token 格式为 `appKey:appSecret`，可在元宝 Bot 管理后台获取。

只需要配置一次，所有 `.py` 文件都会自动读取该配置。

## 启动

### 交互式发送器（推荐）

```bash
python interactive_sender.py
```

功能：
- 发送群消息
- 艾特用户（`/at`）
- 刷屏模式（`/spam 内容 次数`）

### 自动回复客户端

```bash
python yuanbao_client.py
```

功能：
- 自动连接 WebSocket
- 接收消息并自动回复
- 私聊直接回复
- 群聊需艾特才回复

## 命令说明

交互式发送器支持以下命令：

| 命令 | 说明 |
|------|------|
| `/at` | 艾特用户选择器 |
| `/at 用户ID 内容` | 艾特指定用户 |
| `/spam 内容 次数` | 重复发送消息 |
| `/exit` | 退出程序 |

## 文件说明

- `yuanbao_client.py` - 主客户端，含完整 Protobuf 编解码
- `interactive_sender.py` - 交互式消息发送器
- `proto/` - Protobuf 协议定义文件
