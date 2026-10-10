#!/usr/bin/env bash
# 一键产出产线代码覆盖率（桌面端 / 室内机）。
#
# 与门口机侧的差异：本仓库没有指纹/串口/ALSA/GUI 依赖，测试目标仅 3 个，
# 且没有独立的互操作工程（互操作测试在门口机侧，那边链接了本仓库的
# core/net/signaling_server.cpp）。
#
# 用法：bash tools/run_coverage.sh [输出 json 路径]
set -u
export PATH=/mingw64/bin:/usr/bin:$PATH

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
REPO_W="$(cd "$REPO" && pwd -W 2>/dev/null || echo "$REPO")"
PY="${PYTHON:-python}"
JSON_OUT="${1:-}"

BUILD_TESTS="$(mktemp -d)"
echo "构建目录: $BUILD_TESTS"

echo "=== 1/3 配置（--coverage -O0 -g）==="
cmake -S "$REPO/tests" -B "$BUILD_TESTS" -G Ninja \
      -DCMAKE_BUILD_TYPE=Debug \
      -DCMAKE_CXX_FLAGS="--coverage -O0 -g" \
      -DCMAKE_EXE_LINKER_FLAGS="--coverage" > /dev/null || exit 1

echo "=== 2/3 构建 ==="
cmake --build "$BUILD_TESTS" > /dev/null || exit 1

echo "=== 3/3 运行测试 ==="
ctest --test-dir "$BUILD_TESTS" > /dev/null 2>&1

echo
if [ -n "$JSON_OUT" ]; then
  "$PY" "$REPO_W/tools/coverage_report.py" "$REPO_W" \
        --build "$BUILD_TESTS" --json "$JSON_OUT"
else
  "$PY" "$REPO_W/tools/coverage_report.py" "$REPO_W" --build "$BUILD_TESTS"
fi
RC=$?

echo
echo "构建目录保留在: $BUILD_TESTS"
exit $RC
