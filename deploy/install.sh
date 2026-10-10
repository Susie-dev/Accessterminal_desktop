#!/bin/sh
#
# Accessterminal_desktop 部署脚本（Linux 室内机）
#
# 用法：
#   sudo ./install.sh                       # 安装到 /opt/smartserver
#   PREFIX=$HOME/smartserver ./install.sh   # 自定义前缀
#
set -e

PREFIX="${PREFIX:-/opt/smartserver}"
BIN_DIR="$PREFIX/bin"
ETC_DIR="/etc/accessterminal"

echo "=== Accessterminal 室内机部署 ==="
echo "安装前缀: $PREFIX"

if [ ! -f "./smartserver" ]; then
    echo "错误: 当前目录下找不到 smartserver，请先编译" >&2
    exit 1
fi

mkdir -p "$BIN_DIR"
cp -f ./smartserver "$BIN_DIR/smartserver"
chmod 755 "$BIN_DIR/smartserver"
echo "[1/3] 已安装可执行文件: $BIN_DIR/smartserver"

mkdir -p "$ETC_DIR"
if [ -f "./appconfig.json" ]; then
    if [ -f "$ETC_DIR/appconfig.json" ]; then
        cp -f "$ETC_DIR/appconfig.json" "$ETC_DIR/appconfig.json.bak"
        echo "      已备份原有配置到 appconfig.json.bak"
    fi
    cp -f ./appconfig.json "$ETC_DIR/appconfig.json"
    echo "[2/3] 已安装配置: $ETC_DIR/appconfig.json"
else
    echo "[2/3] 未提供 appconfig.json，将使用内置默认值"
fi

# 灯控串口权限：原实现使用 Windows 的 COM24，Linux 下需可写 /dev/ttyUSBx
echo "[3/3] 检查串口权限"
if [ -d /etc/udev/rules.d ]; then
    echo '     提示: 若串口权限不足，可添加 udev 规则（见 deploy/99-accessterminal.rules）'
fi

echo ""
echo "=== 部署完成 ==="
echo "运行: $BIN_DIR/smartserver"
echo "配置: $ETC_DIR/appconfig.json"
echo ""
echo "注意: 请确认配置中的 hardware.serial_port 指向实际灯控串口设备，"
echo "      默认值 /dev/ttyUSB0 在多数 Linux 发行版上可直接使用。"
