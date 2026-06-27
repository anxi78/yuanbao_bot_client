# 元宝 Bot 客户端

腾讯元宝 Bot 的纯 Python WebSocket 客户端，基于 OpenClaw 插件协议，支持消息发送、群管理、自动回复等功能。

## 项目结构

| 文件 | 说明 |
|------|------|
| `sender.py` | 核心交互式发送器，含 `SpamSender` 类、Protobuf 编解码、消息发送/刷屏/自动回复 |
| `config.json` | 配置文件，设置 Bot 凭证（APP_KEY / APP_SECRET）等参数 |
| `requirements.txt` | Python 依赖清单 |

## 安装

```bash
pip install -r requirements.txt
```

## 配置

编辑 `config.json`，填写 Bot 凭证（APP_KEY 和 APP_SECRET），可在元宝 Bot 管理后台获取。

## 使用

### 交互式发送器

```bash
python sender.py
```

输入群号连接 WebSocket 后进入交互模式，支持：

| 命令 | 功能 |
|------|------|
| `<文字>` | 发送普通消息 |
| `/at 用户ID 内容` | 艾特指定用户 |
| `/spam 内容 次数` | 普通刷屏 |
| `/atspam 用户ID 内容 次数` | 艾特+刷屏 |
| `/atall 内容` | 艾特全体成员 |
| `/image 路径` | 发送图片 |
| `/file 路径` | 发送文件 |
| `/group 群号` | 切换目标群 |
| `/members` | 获取群成员列表 |
| `/recent [N]` | 查看最近 N 条消息 |
| `/paste` | 多行粘贴模式 |
| `/big 内容 字号` | 发送放大 LaTeX 文本 |
| `/auto on [文本]` | 开启自动回复 |
| `/reconnect` | 手动重连 WebSocket |
| `/help` | 显示帮助 |

### 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Q` | 接受命令自动补全建议 |
| `Ctrl+D` | 丢弃当前行输入，换到下一行 |
| `Ctrl+C` / `ESC` | 停止刷屏 |

## 协议

- 基于 HMAC-SHA256 签名认证
- 自定义 Protobuf 编解码（微信 iLink 协议层）
- COS（腾讯云对象存储）文件上传

## 许可证

MIT