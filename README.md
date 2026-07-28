# 元宝 Bot 客户端

腾讯元宝 Bot 的纯 Python WebSocket 客户端，基于 OpenClaw 插件协议，支持消息发送、群管理、自动回复、AI 图片生成等功能。
## 项目结构

| 文件 | 说明 |
|------|------|
| `sender.py` | 核心交互式发送器，含 `SpamSender` 类、Protobuf 编解码、消息发送/刷屏/自动回复/代理转发 |
| `group_monitor.py` | 群消息监听器，监听指定群消息并入库 SQLite，支持撤回检测、自动补发被撤回的图片/贴纸/文件 |
| `config.example.json` | 配置文件示例，设置 Bot 凭证（APP_KEY / APP_SECRET）等参数 |
| `config.json` | 实际配置文件 |
| `requirements.txt` | Python 依赖清单 |

## 安装

### Termux 用户（一键安装）

```bash
curl -sSL https://raw.githubusercontent.com/anxi78/yuanbao_bot_client/main/install.sh | bash
```

安装后输入 `ybbot` 即可启动。

### 手动安装

```bash
git clone https://github.com/anxi78/yuanbao_bot_client.git
cd yuanbao_bot_client
pip install -r requirements.txt
```

## 配置

编辑 `config.json`，填写 Bot 凭证（APP_KEY 和 APP_SECRET），可在元宝 Bot 管理后台获取。

```json
{
    "APP_KEY": "你的 APP_KEY",
    "APP_SECRET": "你的 APP_SECRET",
    "API_DOMAIN": "bot.yuanbao.tencent.com",
    "WS_URL": "wss://bot-wss.yuanbao.tencent.com/wss/connection",
    "DEFAULT_GROUP_CODE": "群号（可选，留空则启动时手动输入）",
    "SPAM_INTERVAL": 1.0,
    "IMAGE_GROUP_CODE": "AI 图片生成的群号（/ai-image 命令需要）"
}
```

## 使用

```bash
python sender.py
```

连接后进入交互模式，在 `yuanbao>` 提示符下输入命令。

### 消息发送

| 命令 | 功能 |
|------|------|
| `<文字>` | 发送普通消息 |
| `/at <用户ID/昵称> <内容>` | 艾特指定用户（支持昵称反向查询） |
| `/dm <用户ID> <内容>` | 发送私聊消息 |
| `/reply <序号> <内容>` | 引用 `/recent` 列表中第 N 条消息回复 |
| `/reply <序号> @<用户ID> <内容>` | 引用 + 艾特回复 |
| `/sticker <贴纸名>` | 发送贴纸 |
| `/sticker <贴纸名> <文字>` | 发送贴纸 + 文字 |
| `/sticker <贴纸名> @<用户ID> <文字>` | 发送贴纸 + 艾特 + 文字 |
| `/image <路径1> [路径2 ...]` | 发送图片（支持多张，空格分隔） |
| `/file <路径>` | 发送文件 |
| `/big <内容> <字号>` | 发送放大 LaTeX 文本 |
| `/paste` | 多行粘贴模式，输入 `/end` 发送，`/cancel` 取消 |

### 刷屏

| 命令 | 功能 |
|------|------|
| `/spam <内容> <次数>` | 普通刷屏 |
| `/atspam <用户ID> <内容> <次数>` | 艾特 + 刷屏 |
| `/spamat <用户ID> <内容> <次数>` | 同上（/atspam 别名） |
| `/sticker_spam <贴纸名> <次数>` | 贴纸刷屏 |
| `/replyspam <序号> <内容> <次数>` | 引用刷屏 |
| `/dmspam <用户ID> <内容> <次数>` | 私聊刷屏 |
| `/interval <秒数>` | 设置刷屏间隔（默认 1.0 秒） |

**刷屏过程中可按 Ctrl+C 或 ESC 随时中断。**

### 批量艾特

| 命令 | 功能 |
|------|------|
| `/atall <内容>` | 艾特全体成员 |
| `/atall <内容> <人数>` | 艾特前 N 位成员 |
| `/athuman <内容>` | 艾特所有人类成员 |
| `/atbot <内容>` | 艾特所有 Bot 成员 |
| `/multiat <ID1,ID2,...> <内容>` | 批量艾特指定用户（逗号分隔） |

### 群管理

| 命令 | 功能 |
|------|------|
| `/group <群号>` | 切换目标群（自动缓存新群成员昵称） |
| `/groupinfo` | 查询当前群信息（群名、群主、人数等） |
| `/members` | 获取群成员列表（自动保存到用户数据库） |
| `/members echo` | 获取并发送成员列表到群 |
| `/members echo human` | 仅发送人类成员到群 |
| `/members echo bot` | 仅发送 Bot 成员到群 |
| `/myid <昵称>` | 在成员列表中搜索自己的用户 ID |

### 用户数据库

| 命令 | 功能 |
|------|------|
| `/users` | 查看已保存的用户列表（昵称缓存） |
| `/adduser <用户ID> <昵称>` | 手动添加常用用户 |
| `/deluser <用户ID>` | 删除用户 |

### 贴纸

| 命令 | 功能 |
|------|------|
| `/stickerlist` | 查看所有可用贴纸（60+ 个） |
| `/stickerfind <关键词>` | 搜索贴纸 |

内置贴纸包含：六六六、我想开了、害羞、比心、委屈、亲亲、酷、斜眼笑、吃瓜、狗头、爱心、晚安、点赞、玫瑰、牛吖、略略略、我酸了、尊嘟假嘟 等 60+ 个。

### 自动回复 / 代理模式

| 命令 | 功能 |
|------|------|
| `/auto` | 查看当前自动回复状态 |
| `/auto <text> on` | 开启自动回复，群聊全部消息触发 |
| `/auto <text> on at` | 开启自动回复，仅被艾特时触发 |
| `/auto yb on` | 开启代理模式：将消息转发到元宝群，将元宝回复回传（需配置 `IMAGE_GROUP_CODE`） |
| `/auto off` | 关闭自动回复 |

**代理模式** (`/auto yb on`)：将群内所有消息转发给「元宝」Bot，自动将元宝的回复引用回原消息。支持 FIFO 队列排队处理。

### 其他

| 命令 | 功能 |
|------|------|
| `/ai-image <提示词>` | AI 生成图片（需配置 `IMAGE_GROUP_CODE`） |
| `/recent [N]` | 查看最近 N 条消息（默认 10 条），序号用于 `/reply` |
| `/reconnect` | 手动重新连接 WebSocket |
| `/auth` | 临时切换 APP_KEY 和 APP_SECRET（仅本次运行生效，不写 config.json） |
| `/help` | 显示帮助 |
| `/exit` | 退出 |

### 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Q` | 接受命令自动补全建议 |
| `Ctrl+D` | 丢弃当前行输入，换到下一行 |
| `Ctrl+C` / `ESC` | 停止刷屏 / 中断操作 |

## 核心特性

- **自动重连**：WebSocket 断开后自动尝试重连（1s/2s/4s/8s/16s 退避），重建连接后恢复心跳和接收循环
- **ESC 中断**：刷屏操作中可按 ESC 随时停止，无需关闭终端
- **昵称反向查询**：`/at` 支持输入昵称自动匹配用户 ID（支持模糊匹配）
- **引用消息**：通过 `/recent` 获取消息列表，使用序号引用回复
- **贴纸 + 艾特 + 文字**：单条消息组合发送贴纸、艾特和文字
- **COS 上传**：图片/文件自动通过腾讯云 COS 上传获取直链
- **群成员缓存**：获取成员列表时自动缓存昵称，后续命令可直接使用昵称

## 协议

- 基于 HMAC-SHA256 签名认证
- 自定义 Protobuf 编解码（微信 iLink 协议层）
- COS（腾讯云对象存储）文件上传

## 撤回通知（group_monitor.py）

群消息监听器会自动检测群内撤回事件，向目标群发送撤回通知。通知包含撤回者、原发送者、发送时间和原内容。

### 原内容防渲染

原内容通过 Markdown 代码块包裹发送，防止 LaTeX / Markdown / HTML 渲染。

````
原内容:
```原内容
[测试链接](url) &copy; <sub>下标</sub>
````

**防渲染原理**：Markdown 代码块的 fence（围栏）用反引号 ` ``` ` 包裹，只要外层 fence 比内层长，内层的反引号就不会被识别为结束标记。

`````markdown
````          ← 4个反引号 (外层)
```           ← 3个反引号 (内层，原内容中的)
````          ← 4个反引号 (外层，结束)
`````

代码实现：扫描原内容中最长的连续反引号长度 `N`，外层 fence 使用 `N+1` 个反引号；若原内容无反引号则默认使用 3 个。

```python
max_backticks = 0
bcount = 0
for ch in orig_content:
    if ch == '`':
        bcount += 1
        max_backticks = max(max_backticks, bcount)
    else:
        bcount = 0
fence = '`' * (max_backticks + 1) if max_backticks >= 3 else '```'
```
##交流群

元宝派：780-533-671
点击链接加入元宝派：https://yb.tencent.com/gp/i/iHwKUladPJCi
## 许可证

MIT
