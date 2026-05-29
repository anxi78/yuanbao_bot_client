# 元宝 Bot Web 控制台（Docker 版）

基于 Flask 的 Docker 容器化元宝 Bot Web 管理界面。

## 文件说明

| 文件 | 说明 |
|------|------|
| `app.py` | Flask Web 应用，支持环境变量配置覆盖，带 `save_config()` 持久化功能 |
| `config.json` | 配置文件，支持在 Web 界面编辑后持久保存 |
| `.env` | Docker 环境变量文件（APP_KEY、APP_SECRET 等） |
| `Dockerfile` | 基于 python:3.12-slim 的 Docker 镜像构建文件 |
| `docker-compose.yml` | Docker Compose 编排文件，挂载 config.json 实现配置持久化 |
| `requirements.txt` | Python 依赖清单 |
| `templates/index.html` | 单页 Web 前端（同 Web 版），7 个功能标签页 |

## 快速启动

```bash
docker-compose up -d
```

## 配置方式

支持两种配置方式（环境变量优先于配置文件）：

1. **环境变量**：编辑 `.env` 文件设置
   ```
   APP_KEY=your_key
   APP_SECRET=your_secret
   ```

2. **配置文件**：编辑 `config.json`

## Docker 部署

```bash
# 构建镜像
docker build -t yuanbao-web .

# 运行容器
docker run -d -p 2570:2570 \
  -v $(pwd)/config.json:/app/config.json \
  -e APP_KEY=your_key \
  -e APP_SECRET=your_secret \
  yuanbao-web
```

服务默认运行在端口 2570。

## 功能

同 Web 版功能：7 个功能标签页、50+ 贴纸、多种发送模式、Web 界面配置编辑。
