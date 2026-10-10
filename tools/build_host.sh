#!/usr/bin/env bash
# ============================================================================
# Accessterminal_desktop 主机端真实构建脚本
#
# 室内机（smartserver）依赖 Qt5（Core/Gui/Widgets/Network/Multimedia/
# SerialPort）、CMake 与一个 C++ 编译器。这些在 Windows（MSYS2+MinGW）与
# Linux 上都齐全，因此本工程可以做**完整**的编译、链接与单元测试——
# 这是与 T113 门口机最大的不同（后者依赖 Linux 专有的 ALSA/libgpiod）。
#
# 用法
# ----
#   bash tools/build_host.sh              # 配置 + 编译 + 跑测试
#   BUILD_DIR=build-local bash tools/build_host.sh
#   ACCESSTERMINAL_BUILD_TESTS=OFF bash tools/build_host.sh
#
# 产物
# ----
#   $BUILD_DIR/bin/smartserver[.exe]
# ============================================================================
set -eu

# ---- 工具链可见性（Windows/MSYS2）----
if [ -d /mingw64/bin ]; then
    case ":$PATH:" in
        *:/mingw64/bin:*) ;;
        *) PATH="/mingw64/bin:/usr/bin:$PATH" ;;
    esac
    export PATH
fi

for _tool in cmake c++; do
    if ! command -v "$_tool" >/dev/null 2>&1; then
        echo "错误：找不到 $_tool。请安装 CMake 与带 Qt5 的 C++ 工具链。" >&2
        exit 1
    fi
done
unset _tool

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$SRC_ROOT/build-host}"
BUILD_TESTS="${ACCESSTERMINAL_BUILD_TESTS:-ON}"
BUILD_TYPE="${CMAKE_BUILD_TYPE:-RelWithDebInfo}"

echo "=== 配置 ==="
cmake -S "$SRC_ROOT" -B "$BUILD_DIR" \
      -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
      -DACCESSTERMINAL_BUILD_TESTS="$BUILD_TESTS"

echo ""
echo "=== 编译 ==="
cmake --build "$BUILD_DIR" -j "${JOBS:-4}"

echo ""
echo "=== 产物 ==="
ls -la "$BUILD_DIR/bin/" 2>/dev/null || true

if [ "$BUILD_TESTS" = "ON" ]; then
    echo ""
    echo "=== 单元测试 ==="
    (cd "$BUILD_DIR" && ctest --output-on-failure)
fi

echo ""
echo "完成。可执行文件位于: $BUILD_DIR/bin/"
