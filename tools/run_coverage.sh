#!/usr/bin/env bash
# 一键产出产线代码覆盖率（桌面端 / 室内机）。
#
# 与门口机侧的差异：本仓库没有指纹/串口/ALSA 依赖；互操作工程在门口机侧
# （那边链接了本仓库的 core/net/signaling_server.cpp）。
#
# 用法：bash tools/run_coverage.sh [输出 json 路径]
# 环境变量 PYTHON 可指定解释器；未指定时自动挑一个 **Python 3**。
set -u
export PATH=/mingw64/bin:/usr/bin:$PATH

# monitor_client / call_session / widget 这三个目标会构造 QGuiApplication /
# QApplication，需要平台插件。无显示的环境（CI、纯 ssh）里若不指定，ctest 会
# 成批失败，覆盖率分母随之失真。offscreen 对这几个纯逻辑测试完全够用。
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
REPO_W="$(cd "$REPO" && pwd -W 2>/dev/null || echo "$REPO")"

# coverage_report.py 用了 glob(recursive=True) 等 Python 3 特性，而很多发行版
# 的 `python` 仍是 Python 2（本机就是 2.7.18）。原先写死 PY="${PYTHON:-python}"，
# 于是这条命令在 Linux 上**必然**以
#   TypeError: glob() got an unexpected keyword argument 'recursive'
# 收场 —— 覆盖率报告从来没在这台机器上跑出来过。这里改为自动挑 Python 3，
# 并在一个都找不到时明确报错，而不是让 TypeError 冒充别的问题。
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for _cand in python3 python; do
    if command -v "$_cand" >/dev/null 2>&1 \
       && "$_cand" -c 'import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)' >/dev/null 2>&1; then
      PY="$_cand"
      break
    fi
  done
fi
if [ -z "$PY" ]; then
  echo "找不到 Python 3 解释器（可用 PYTHON=/path/to/python3 指定）" >&2
  exit 1
fi
echo "使用解释器: $PY ($("$PY" --version 2>&1))"

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
