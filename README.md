# 元宝 Bot 客户端（核心版）

腾讯元宝 Bot 的纯 Python WebSocket 客户端，支持消息发送、自动回复、群管理等功能。

## 文件说明

| 文件 | 说明 |
|------|------|
| `sender.py` | 核心发送器，包含 `SpamSender` 类和自定义 Protobuf 编解码器 |
| `client.py` | 自动回复客户端，含 `YuanbaoClient` 类和完整 Protobuf 编解码 |
| `gui.py` | CustomTkinter 图形界面，5 个功能标签页（消息/发送/贴纸/成员/设置） |
| `config.json` | 配置文件，设置 APP_KEY / APP_SECRET 等参数 |
| `requirements.txt` | Python 依赖清单 |
| `bot.log` | 运行日志文件 |

## 安装

```bash
pip install -r requirements.txt
```

## 配置

编辑 `config.json`，填写你的 Bot 凭证（APP_KEY 和 APP_SECRET），可在元宝 Bot 管理后台获取。

## 使用方法

### 交互式发送器
```bash
python sender.py
```
支持发送群消息、艾特用户、刷屏模式等。

### 自动回复客户端
```bash
python client.py
```
自动连接 WebSocket，接收消息并自动回复。

### 图形界面
```bash
python gui.py
```
基于 CustomTkinter 的完整 GUI，支持手机/电脑端使用。
