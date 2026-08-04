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
    # 目录不存在，直接克隆
    git clone https://v4.gh-proxy.org/github.com/anxi78/yuanbao_bot_client.git "$PROJECT_DIR"
    echo "✅ 仓库克隆完成"

else
    echo "📂 目录 '$PROJECT_DIR' 已存在，正在进行安全检查..."

    # 1. 检查是否为 Git 仓库
    if git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        
        # 2. 检查远程地址是否匹配（兼容 https 和 git@ssh 两种协议）
        REMOTE_URL=$(git -C "$PROJECT_DIR" config --get remote.origin.url 2>/dev/null)
        if echo "$REMOTE_URL" | grep -q "anxi78/yuanbao_bot_client"; then
            
            # 3. 确认是咱们自己的仓库，开始检查更新
            echo "✅ 确认为本项目仓库，检查是否最新..."
            git -C "$PROJECT_DIR" fetch origin
            
            LOCAL=$(git -C "$PROJECT_DIR" rev-parse HEAD)
            REMOTE=$(git -C "$PROJECT_DIR" rev-parse origin/main 2>/dev/null || git -C "$PROJECT_DIR" rev-parse origin/master 2>/dev/null)
            
            if [ "$LOCAL" = "$REMOTE" ]; then
                echo "✅ 本地仓库已是最新，无需更新"
            else
                echo "⚠️ 检测到本地与云端有差异，正在更新..."
                git -C "$PROJECT_DIR" pull
                echo "✅ 更新完成"
            fi

        else
            # 是别人的 Git 仓库
            echo "❌ 该目录是一个 Git 仓库，但不属于本项目！"
            echo "   （当前远程地址: $REMOTE_URL）"
            echo "💡 请手动移除或重命名 '$PROJECT_DIR' 后重试"
            exit 1
        fi

    else
        # 不是 Git 仓库（比如你测试时手动建的空文件夹）
        echo "❌ 目录已存在，但不是 Git 仓库"
        echo "💡 为防止误删你的文件，请手动检查："
        ls -la "$PROJECT_DIR"
        exit 1
    fi
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
cd "$PROJECT" || exit 1

case "${1:-}" in
    monitor)
        exec python group_monitor.py
        ;;
    *)
        exec python sender.py
        ;;
esac
SCRIPT

chmod +x "$BIN_DIR/ybbot"

echo "✅ ybbot 已安装：$BIN_DIR/ybbot"
echo "ybbot monitor命令可以启动撤回通知"