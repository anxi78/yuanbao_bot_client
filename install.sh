#!/usr/bin/env bash
set -e

cat << 'EOF'
__  __                  ____                 ____        __
\ \/ /_  ______ _____  / __ )____ _____     / __ )____  / /_
 \  / / / / __ `/ __ \/ __  / __ `/ __ \   / __  / __ \/ __/
 / / /_/ / /_/ / / / / /_/ / /_/ / /_/ /  / /_/ / /_/ / /_
/_/\__,_/\__,_/_/ /_/_____/\__,_/\____/  /_____/\____/\__/
欢迎使用 Yuanbao_bot_client termux一键安装脚本
EOF

sed -i 's@^\(deb.*stable main\)$@#\1\ndeb https://mirrors.tuna.tsinghua.edu.cn/termux/apt/termux-main stable main@' $PREFIX/etc/apt/sources.list
apt update -y && apt -y -o Dpkg::Options::="--force-all" upgrade

pkg install git -y
pkg install python -y
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
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
read -r -p "请输入默认代理群聊: " IMAGE_GROUP_CODE
cat > "$PROJECT_DIR/config.json" << EOF
{
    "APP_KEY": "$APP_KEY",
    "APP_SECRET": "$APP_SECRET",
    "API_DOMAIN": "bot.yuanbao.tencent.com",
    "WS_URL": "wss://bot-wss.yuanbao.tencent.com/wss/connection",
    "DEFAULT_GROUP_CODE": "$GROUP_CODE",
    "SPAM_INTERVAL": $SPAM_INTERVAL,
    "AUTO_DEFAULT_TEXT": "啊对对对，你说的都对",
    "IMAGE_GROUP_CODE": "$IMAGE_GROUP_CODE"
}
EOF

echo "✅ 配置文件已写入：$PROJECT_DIR/config.json"

# 3. 安装依赖
pkg install python-pillow -y && pip install requests websockets cos-python-sdk-v5 prompt_toolkit

# 4. 生成 ybbot 启动器
BIN_DIR="/data/data/com.termux/files/usr/bin"

cat > "$BIN_DIR/ybbot" << 'SCRIPT'
#!/usr/bin/env bash
set -e
PROJECT="$HOME/yuanbao_bot_client"
SCRIPT_PY="sender.py"
cd "$PROJECT" || exit 1
exec python "$SCRIPT_PY"
SCRIPT

chmod +x "$BIN_DIR/ybbot"

echo "✅ ybbot 已安装：$BIN_DIR/ybbot"