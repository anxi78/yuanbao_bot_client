# 元宝 Bot GUI（PySide6 版）

基于 PySide6 (Qt6) 的元宝 Bot 增强图形界面，支持电脑端和手机端自适应布局。

## 文件说明

| 文件 | 说明 |
|------|------|
| `main.py` | 主程序，基于 PySide6 的完整可视化界面（3059行），响应式设计 |
| `sender.py` | 核心发送器（来自核心版），包含 `SpamSender` 类和 Protobuf 编解码 |
| `client.py` | 自动回复客户端，含完整 Protobuf 编解码 |
| `config.json` | 配置文件，设置 Bot 凭证和自动回复规则 |
| `requirements.txt` | Python 依赖清单 |

## 安装

```bash
pip install -r requirements.txt
```

## 配置

编辑 `config.json`，填写 APP_KEY 和 APP_SECRET。

## 启动

```bash
python main.py
```

### 功能特性

- 响应式设计：屏幕宽度 < 768px 自动切换为手机布局
- 异步消息处理：基于 `QObject` 的 `AsyncBridge`
- 完整的消息发送、接收、自动回复功能
- 群成员管理
- 贴纸（表情）发送
