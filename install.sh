#!/usr/bin/env bash
set -e

cat << 'EOF'
__  __                  ____                 ____        __
\ \/ /_  ______ _____  / __ )____ _____     / __ )____  / /_
 \  / / / / __ `/ __ \/ __  / __ `/ __ \   / __  / __ \/ __/
 / / /_/ / /_/ / / / / /_/ / /_/ / /_/ /  / /_/ / /_/ / /_
/_/\__,_/\__,_/_/ /_/_____/\__,_/\____/  /_____/\____/\__/
欢迎使用 Yuanbao_bot_client 一键安装脚本
EOF

HOME_DIR="$HOME"
PROJECT_DIR="$HOME_DIR/yuanbao_bot_client"
VENV_DIR="$PROJECT_DIR/venv"

# 1. 克隆仓库
if [ ! -d "$PROJECT_DIR" ]; then
    git clone https://github.com/anxi78/yuanbao_bot_client.git "$PROJECT_DIR"
    echo "✅ 仓库克隆完成"
else
    echo "✅ 仓库已存在，跳过克隆"
fi

# 2. 生成 config.json
read -r -p "请输入 appKey: " APP_KEY
read -r -p "请输入 appSecret: " APP_SECRET
read -r -p "请输入默认群聊: " GROUP_CODE
read -r -p "请输入默认刷屏间隔: " SPAM_INTERVAL

cat > "$PROJECT_DIR/config.json" << EOF
{
    "APP_KEY": "$APP_KEY",
    "APP_SECRET": "$APP_SECRET",
    "API_DOMAIN": "bot.yuanbao.tencent.com",
    "WS_URL": "wss://bot-wss.yuanbao.tencent.com/wss/connection",
    "DEFAULT_GROUP_CODE": "$GROUP_CODE",
    "SPAM_INTERVAL": $SPAM_INTERVAL,
    "AUTO_DEFAULT_TEXT": "啊对对对，你说的都对"
}
EOF

echo "✅ 配置文件已写入：$PROJECT_DIR/config.json"

# 3. 创建虚拟环境并安装依赖
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

# 4. 生成 ybbot 启动器
BIN_DIR="$HOME_DIR/.local/bin"
mkdir -p "$BIN_DIR"

cat > "$BIN_DIR/ybbot" << 'SCRIPT'
#!/usr/bin/env bash
set -e
PROJECT="$HOME/yuanbao_bot_client"
PYTHON="$PROJECT/venv/bin/python"
SCRIPT_PY="sender.py"
cd "$PROJECT" || exit 1
exec "$PYTHON" "$SCRIPT_PY"
SCRIPT

chmod +x "$BIN_DIR/ybbot"

echo "✅ ybbot 已安装：$BIN_DIR/ybbot"
echo "⚠️ 如果 ybbot 命令找不到，请把下面一行加到 ~/.bashrc："
echo 'export PATH="$HOME/.local/bin:$PATH"'
