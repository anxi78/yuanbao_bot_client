FROM python:3.12-slim

WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY app.py .
COPY config.json .
COPY templates/ templates/

# Web 控制台端口（可通过 APP_PORT 环境变量覆盖）
EXPOSE 2570

# 启动 Web 控制台
CMD ["python", "app.py"]
