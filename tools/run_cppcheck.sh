#!/usr/bin/env bash
#
# 用 cppcheck 做静态分析。这是 verify.py 之外的补充：verify.py 只做
# 自定义的结构性检查，cppcheck 会做数据流、越界、空指针、初始化顺序等
# 真正的静态分析。
#
# 与 check_host_compile.sh 的区别：
#   - check_host_compile.sh 需要完整 Qt/OpenCV 头文件才能做类型检查；
#   - 本脚本不需要编译器、不需要链接、不需要 Qt 已安装，
#     纯语法+数据流分析，能跑在任何装了 cppcheck 的机器上。
#
# 用法：
#   bash tools/run_cppcheck.sh                 # 默认查当前工程
#   CPPCHECK=/path/to/cppcheck bash tools/run_cppcheck.sh
#
# 退出码：0 = 没有 `warning`/`error` 级别问题；1 = 有。
# style/performance 只打印，不影响退出码（避免历史代码风格把提交卡死）。

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CPPCHECK="${CPPCHECK:-}"

if [ -z "$CPPCHECK" ]; then
    for cand in \
        "$(command -v cppcheck 2>/dev/null || true)" \
        "/mingw64/bin/cppcheck.exe" \
        "/c/Users/user/.dsh/toolchains/msys64/mingw64/bin/cppcheck.exe"
    do
        if [ -n "$cand" ] && [ -x "$cand" ]; then
            CPPCHECK="$cand"
            break
        fi
    done
fi

if [ -z "$CPPCHECK" ] || [ ! -x "$CPPCHECK" ]; then
    echo "找不到 cppcheck。"
    echo "  MSYS2 安装： pacman -S mingw-w64-x86_64-cppcheck"
    echo "  或指定路径： CPPCHECK=/path/to/cppcheck bash tools/run_cppcheck.sh"
    exit 2
fi

echo "cppcheck : $CPPCHECK"
"$CPPCHECK" --version
echo "工程     : $ROOT"
echo "======================================================================"

# Qt 的 signals/slots/emit 是宏。不告诉 cppcheck 的话它会在每个含
# `signals:` 的头文件上报 error/unknownMacro 并停止解析该文件，
# 后面的真实发现就全丢了。
QT_MACROS=(
    "-DQ_OBJECT="
    "-Dsignals=public"
    "-Dslots="
    "-Demit="
    "-DQT_BEGIN_NAMESPACE="
    "-DQT_END_NAMESPACE="
    "-DQT_BEGIN_HEADER="
    "-DQT_END_HEADER="
    # 跨平台属性宏，缺少会让解析器把声明看错
    "-DQ_DECL_OVERRIDE=override"
    "-DQ_DECL_FINAL=final"
)

ERRLOG="$(mktemp)"
trap 'rm -f "$ERRLOG"' EXIT

"$CPPCHECK" \
    --enable=warning,style,performance,portability \
    --language=c++ \
    --std=c++11 \
    --inline-suppr \
    --template="{id}|{severity}|{file}:{line}|{message}" \
    "${QT_MACROS[@]}" \
    -i "$ROOT/build" \
    -I "$ROOT/src" \
    "$ROOT/src" 2>"$ERRLOG" >/dev/null

if [ ! -s "$ERRLOG" ]; then
    echo "结论: 未发现问题"
    exit 0
fi

# 只看真正的发现（template 输出），忽略 cppcheck 的进度噪声
grep -E '^[a-zA-Z_][a-zA-Z0-9_]*\|' "$ERRLOG" >"$ERRLOG.clean" || true
mv "$ERRLOG.clean" "$ERRLOG"

# 文件里的路径可能是绝对路径，转成相对便于阅读
sed -i "s|$ROOT/||g" "$ERRLOG" 2>/dev/null || true

echo "---- warning / error（会影响退出码）----"
if grep -E '\|(warning|error)\|' "$ERRLOG"; then
    HARD=1
else
    echo "(无)"
    HARD=0
fi

echo
echo "---- style / performance / portability（仅提示）----"
if grep -E '\|(style|performance|portability)\|' "$ERRLOG"; then
    :
else
    echo "(无)"
fi

echo
echo "---- 按 id 统计 ----"
sed 's/|.*//' "$ERRLOG" | sort | uniq -c | sort -rn

echo
if [ "$HARD" -eq 1 ]; then
    echo "结论: 存在 warning/error 级别问题"
    exit 1
fi
echo "结论: 无 warning/error 级别问题（style 类仅供参考）"
exit 0
