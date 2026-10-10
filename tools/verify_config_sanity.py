#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_config_value_sanity 的故障注入自检（验证「校验器本身」有效）。

为什么需要这个文件
------------------
tools/verify.py 里的 check_config_value_sanity() 是一条静态规则。静态规则
有个通病：写错了会**静默失效**（永远返回通过），比没有规则更危险。本文件
用故障注入证明该规则真的能区分好坏代码。

本案（室内机）关注的配置项是 signaling_port 与 ringtone_volume：
端口为 0 会让 QTcpServer 绑定到随机临时端口（门口机永远连不上），
ringtone_volume 越界则使 QMediaPlayer::setVolume 的行为未定义。
门口机那边同一模式已造成真实崩溃（cfg.faceDetectInterval() 为 0 时
取模除零 → SIGFPE），故两端使用同一条规则、同一份自检。

  真阳性（应该报错）：
    * 把某个数值访问器的 clamp 包裹去掉 → 必须失败
    * 去掉 clamp 且源码中不存在除零调用点 → 仍然必须失败（规则 A 独立生效）
    * 所有访问器都裸返回 → 必须聚合报错并额外报出除零点
    * 头文件里完全没有数值访问器 → 必须报「检查器已失效」（防正则过期）

  真阴性（不应误报）：
    * 原始仓库 → 必须通过
    * 用非数值访问器做除数 → 只应产生警告，不应失败

做法：把 verify.py 中被测函数及其依赖（find_files /
strip_comments_and_strings）**原样提取**出来执行，再在临时目录里合成
源码。这样测的是真实规则本身，而不是复制品。

注意：注入只在纯 Python 里做（读写都是 UTF-8 + newline=""），不经过
PowerShell 文本往返 —— 后者会把中文源码转坏。

用法：
    python tools/verify_config_sanity.py [项目根目录]
返回码 0 表示全部用例符合预期。
"""
import os
import re
import shutil
import sys
import tempfile

REPO = os.path.abspath(
    sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(__file__)))
VERIFY = os.path.join(REPO, "tools", "verify.py")

if not os.path.isfile(VERIFY):
    print("找不到 tools/verify.py: %s" % VERIFY)
    sys.exit(2)

src = open(VERIFY, "r", encoding="utf-8").read()

# ---- 从 verify.py 里原样提取被测函数与依赖 ----
FAIL = []
WARN = []
ns = {
    "os": os,
    "re": re,
    "fail": FAIL.append,
    "warn": WARN.append,
    "read": lambda p: open(p, "r", encoding="utf-8", errors="replace").read(),
}
try:
    for name in ("find_files", "strip_comments_and_strings",
                 "check_config_value_sanity"):
        s = src.index("def %s(" % name)
        e = src.index("\ndef ", s + 10)
        exec(compile(src[s:e], VERIFY, "exec"), ns)
except ValueError as exc:
    print("无法从 verify.py 提取函数（规则被改名/删除？）: %s" % exc)
    sys.exit(2)
check = ns["check_config_value_sanity"]

HEADER_REL = os.path.join("src", "config", "app_config.h")
GOOD_HEADER = open(os.path.join(REPO, HEADER_REL), encoding="utf-8").read()
if "clampInt(" not in GOOD_HEADER:
    print("被测头文件中没有 clampInt —— 规则已被绕过？")
    sys.exit(2)

# clampInt(expr, lo, hi) -> expr（兼容 static_cast<...>(clampInt(...)) 外层）
CLAMP_RE = re.compile(r"clamp(?:Int|Double)\(\s*([A-Za-z_]\w*)\s*,[^()]*\)")
if not CLAMP_RE.findall(GOOD_HEADER):
    print("HEADER 中未匹配到任何 clamp 调用")
    sys.exit(2)


def strip_all_clamps(text):
    return CLAMP_RE.sub(r"\1", text)


def strip_one_clamp(text, getter):
    """只去掉 `getter()` 那个访问器里的 clamp 包裹。"""
    out = []
    for line in text.split("\n"):
        if getter + "()" in line and "clamp" in line:
            line = CLAMP_RE.sub(r"\1", line)
        out.append(line)
    return "\n".join(out)


# 门口机与室内机暴露的数值访问器不同，挑实际存在的那个做注入目标。
if "faceDetectInterval" in GOOD_HEADER:
    TARGET = "faceDetectInterval"
elif "signalingPort" in GOOD_HEADER:
    TARGET = "signalingPort"
else:
    TARGET = sorted(CLAMP_RE.findall(GOOD_HEADER))[0]

BAD_HEADER = strip_one_clamp(GOOD_HEADER, TARGET)
if BAD_HEADER == GOOD_HEADER:
    print("注入失败：%s 未被改写" % TARGET)
    sys.exit(2)

ALL_BARE = strip_all_clamps(GOOD_HEADER)
# 辅助函数自身的定义 `inline int clampInt(...)` 会保留，故只检查调用点。
if ALL_BARE == GOOD_HEADER or "return clamp" in ALL_BARE:
    print("注入失败：未能去掉全部 clamp 调用点")
    sys.exit(2)

DIVISOR_CPP = ("void Widget::updateFrame()\n"
               "{\n"
               "    if (++detectCounter % cfg.__G__() == 0) {\n"
               "    }\n"
               "}\n").replace("__G__", TARGET)


def run(header_text, cpp_text):
    FAIL[:] = []
    WARN[:] = []
    tmp = tempfile.mkdtemp(prefix="fi_cfg_")
    try:
        os.makedirs(os.path.join(tmp, "src", "config"))
        os.makedirs(os.path.join(tmp, "src", "ui"))
        with open(os.path.join(tmp, HEADER_REL), "w",
                  encoding="utf-8", newline="") as f:
            f.write(header_text)
        if cpp_text is not None:
            with open(os.path.join(tmp, "src", "ui", "widget.cpp"), "w",
                      encoding="utf-8", newline="") as f:
                f.write(cpp_text)
        check(tmp, os.path.join(tmp, "src"))
        return list(FAIL), list(WARN)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


cases = []

# 真阴性：原始仓库必须通过
f, w = run(GOOD_HEADER, DIVISOR_CPP)
cases.append(("原始仓库(已修复)", f == [], f))

# 真阳性：单个访问器去掉 clamp
f, w = run(BAD_HEADER, DIVISOR_CPP)
cases.append(("%s 去掉兜底(真阳性)" % TARGET, len(f) >= 1, f))

# 真阳性：规则 A 独立生效（无除零调用点也要报）
f, w = run(BAD_HEADER, "int f() { return 0; }\n")
cases.append(("去掉兜底且无除零点(真阳性-A)", len(f) >= 1, f))

# 真阳性：全部裸返回 → 聚合报告 + 除零点报告
f, w = run(ALL_BARE, DIVISOR_CPP)
agg = [x for x in f if "未做范围兜底" in x]
cases.append(("全部访问器裸返回(聚合+除零点)", len(agg) == 1 and len(f) >= 2, f))

# 真阳性：完全没有数值访问器 → 防「检查器已失效」
f, w = run("class AppConfig { public: QString x() const { return m_x; } };\n",
           DIVISOR_CPP)
cases.append(("无任何数值访问器(失效保护)", len(f) >= 1, f))

# 真阴性：非数值（无参）访问器做除数 → 仅警告
f, w = run(GOOD_HEADER, "int g() { return 100 % cfg.selfIp(); }\n")
cases.append(("非数值访问器做除数(真阴性-仅警告)", f == [] and len(w) >= 1, f))

print("=" * 68)
print("校验目标: %s" % REPO)
bad = 0
for name, ok, f in cases:
    print("  [%s] %s" % ("PASS" if ok else "FAIL", name))
    if not ok:
        bad += 1
        for x in f:
            print("        -> " + x)
print("=" * 68)
print("结果: %d 个用例失败 (共 %d)" % (bad, len(cases)))
sys.exit(1 if bad else 0)
