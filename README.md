# 元宝 Bot Web 控制台

基于 Flask 的 Web 版元宝 Bot 管理界面，支持在浏览器中管理 Bot。

## 文件说明

| 文件 | 说明 |
|------|------|
| `app.py` | Flask Web 应用，包含 `EnhancedSpamSender` 类（~50个贴纸）和完整 API |
| `config.json` | 配置文件，设置 Bot 凭证和自动回复规则 |
| `requirements.txt` | Python 依赖清单 |
| `templates/index.html` | 单页 Web 前端，7 个功能标签页（消息/发送/贴纸/成员/用户/高级/设置） |

## 安装

```bash
pip install -r requirements.txt
```

## 配置

编辑 `config.json`，填写 APP_KEY 和 APP_SECRET。

## 启动

```bash
python app.py
```

服务默认运行在 `http://localhost:2570`。

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/status` | GET | 获取连接状态 |
| `/api/connect` | POST | 连接 WebSocket |
| `/api/disconnect` | POST | 断开连接 |
| `/api/send` | POST | 发送消息 |
| `/api/messages` | GET | 获取消息历史 |
| `/api/members` | POST | 获取群成员 |
| `/api/stickers` | GET | 获取贴纸列表 |
| `/api/settings` | POST | 更新设置 |

## 前端特性

- 暗色主题，响应式设计（480px 和 768px 断点）
- 7 种发送模式：普通/艾特/刷屏/艾特刷屏/多艾特/私聊/私聊刷屏
- 实时轮询获取消息状态
