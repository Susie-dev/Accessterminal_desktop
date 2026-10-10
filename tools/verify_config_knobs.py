#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_config_knobs_are_used 的故障注入自检（验证「校验器本身」有效）。

为什么需要这个文件
------------------
tools/verify.py 里的 check_config_knobs_are_used() 是一条静态规则。静态规则
写错了会**静默失效**（永远返回通过），比没有规则更危险 —— 本条规则针对的
「假旋钮」缺陷恰恰就是「配置被读取、被文档化，但从不生效」，它既不崩溃也
不告警，只能靠这类结构化检查拦住。

本文件用故障注入证明规则真的能区分好坏代码：

  真阳性（必须 fail）：
    * 假旋钮：成员只在 envOverride/jsonInt 回退实参里被「读」，从未被消费
    * 复现真实缺陷：把某个访问器的成员改成只被写入
    * 头文件里完全没有访问器 -> 报「检查器已失效」（防正则过期）

  真阴性（不得误报 fail）：
    * 当前仓库（已修复）
    * 访问器无人调用、但成员在加载代码之外被读取（如 lightCommand/m_lightCommands）
      -> 只能 warn，不能 fail

对室内机而言，本规则重点保护的是 signaling_port：若它的消费点
（widget.cpp 的 listen(cfg.signalingPort())）被误删，门口机就再也连不上，
而程序不会报任何错。

关键设计点：**加载代码里的成员读取不算消费**。像
    m_x = jsonInt(o, "x", m_x);
这种自引用回退实参是「读」，但配置改了完全没用；若把它算作消费，
真正的假旋钮就会被漏掉（本规则第一版正是这样漏掉的）。

用法：
    python tools/verify_config_knobs.py [项目根目录]
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
                 "check_config_knobs_are_used"):
        s = src.index("def %s(" % name)
        e = src.index("\ndef ", s + 10)
        exec(compile(src[s:e], VERIFY, "exec"), ns)
except ValueError as exc:
    print("无法从 verify.py 提取函数（规则被改名/删除？）: %s" % exc)
    sys.exit(2)
check = ns["check_config_knobs_are_used"]

HDR = os.path.join("src", "config", "app_config.h")
IMP = os.path.join("src", "config", "app_config.cpp")
REAL_H = open(os.path.join(REPO, HDR), encoding="utf-8").read()
REAL_C = open(os.path.join(REPO, IMP), encoding="utf-8").read()


def run(header_text, impl_text, extra_files=None):
    """
    在临时目录里合成最小工程。额外文件由 extra_files 提供。

    注意：本函数**不会**带上真实仓库的其它源码，因此「访问器被别处调用」
    必须由 extra_files 显式给出。若要验证真实仓库自身，请用 run_real()。
    """
    FAIL[:] = []
    WARN[:] = []
    tmp = tempfile.mkdtemp(prefix="fi_knobs_")
    try:
        os.makedirs(os.path.join(tmp, "src", "config"))
        with open(os.path.join(tmp, HDR), "w",
                  encoding="utf-8", newline="") as f:
            f.write(header_text)
        with open(os.path.join(tmp, IMP), "w",
                  encoding="utf-8", newline="") as f:
            f.write(impl_text)
        for rel, text in (extra_files or {}).items():
            full = os.path.join(tmp, "src", rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        check(tmp, os.path.join(tmp, "src"))
        return list(FAIL), list(WARN)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_real(header_text, impl_text, scrub_accessor=None):
    """
    复制真实 src/ 树，再覆盖 app_config.h/.cpp。

    这样才保留真实的调用点，用于验证「当前仓库」以及「只破坏某一处消费点」
    这类需要真实上下文的场景。

    scrub_accessor: 若给出访问器名，则在 app_config.* 之外的**所有**文件中
    把 `X()` 文本抹掉，用于模拟「配置项还在、但所有消费点被删除」的重构退化。
    这是纯文本注入（不改语义），目的是测试静态规则本身，不需要能编译。
    """
    FAIL[:] = []
    WARN[:] = []
    tmp = tempfile.mkdtemp(prefix="fi_knobs_real_")
    try:
        shutil.copytree(os.path.join(REPO, "src"),
                        os.path.join(tmp, "src"))
        with open(os.path.join(tmp, HDR), "w",
                  encoding="utf-8", newline="") as f:
            f.write(header_text)
        with open(os.path.join(tmp, IMP), "w",
                  encoding="utf-8", newline="") as f:
            f.write(impl_text)

        if scrub_accessor:
            pat = re.compile(r'\b' + scrub_accessor + r'\s*\(\s*\)')
            for dp, dn, fn in os.walk(os.path.join(tmp, "src")):
                for name in fn:
                    if not name.endswith((".cpp", ".h")):
                        continue
                    if name in ("app_config.h", "app_config.cpp"):
                        continue
                    p = os.path.join(dp, name)
                    body = open(p, "r", encoding="utf-8",
                                errors="replace").read()
                    new = pat.sub(scrub_accessor + "_removed", body)
                    if new != body:
                        with open(p, "w", encoding="utf-8",
                                  newline="") as f:
                            f.write(new)

        check(tmp, os.path.join(tmp, "src"))
        return list(FAIL), list(WARN)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- 合成场景 ----
# 两个仓库的环境变量覆盖函数名不同（T113: applyEnvOverrides，
# desktop: applyEnvironment），从真实实现里探测，保证加载函数确实被识别。
ENV_FN = "applyEnvOverrides" if "applyEnvOverrides" in REAL_C \
    else "applyEnvironment"

# 假旋钮：访问器存在，成员只在 envOverride 里被写入（从未被消费）
FAKE_H = """class AppConfig {
public:
    static AppConfig& instance();
    int mysteryKnob() const { return m_mysteryKnob; }
private:
    int m_mysteryKnob = 7;
};
"""
FAKE_C = """void AppConfig::%s()
{
    envOverride("ACCESSTERMINAL_MYSTERY", m_mysteryKnob, toInt);
}
""" % ENV_FN

# 自引用回退实参：m_x = jsonInt(o, "x", m_x) —— 加载代码里的读，不算消费
SELFREF_H = """class AppConfig {
public:
    static AppConfig& instance();
    int ghostKnob() const { return m_ghostKnob; }
private:
    bool load(const QString& p);
    int m_ghostKnob = 5;
};
"""
SELFREF_C = """bool AppConfig::load(const QString& p)
{
    m_ghostKnob = jsonInt(obj, "ghost_knob", m_ghostKnob);
    return true;
}
"""

# 真阴性：访问器无人调，但成员在加载之外被读取
READ_H = """class AppConfig {
public:
    static AppConfig& instance();
    QString pcmDir() const { return m_pcmDir; }
    QString pcmFile(const QString& n) const;
private:
    QString m_pcmDir;
};
"""
READ_C = """QString AppConfig::pcmFile(const QString& n) const
{
    return QDir(m_pcmDir).filePath(n);
}
"""

EMPTY_H = "class AppConfig { public: static AppConfig& instance(); };\n"
EMPTY_C = "AppConfig& AppConfig::instance() { static AppConfig c; return c; }\n"

cases = []

# 1) 真阳性：假旋钮必须 fail
f, w = run(FAKE_H, FAKE_C)
cases.append(("假旋钮(真阳性-fail)",
              len(f) == 1 and "mysteryKnob" in f[0], f))

# 2) 真阳性：自引用回退实参不算消费 -> 必须 fail（本规则第一版漏掉的正是这种）
f, w = run(SELFREF_H, SELFREF_C)
hits = [x for x in f if "ghostKnob" in x]
cases.append(("自引用回退实参(真阳性-fail)", len(hits) == 1, f))

# 3) 真阴性：成员在加载之外被读取 -> 只能 warn
f, w = run(READ_H, READ_C)
cases.append(("成员仍被读取(真阴性-仅warn)", f == [] and len(w) == 1, f))

# 4) 真阳性：解析不到访问器 -> 检查器失效保护
f, w = run(EMPTY_H, EMPTY_C)
cases.append(("无访问器(失效保护)", len(f) == 1, f))

# 5) 真阴性：当前仓库必须通过（用真实 src/ 树，保留真实调用点）
f, w = run_real(REAL_H, REAL_C)
cases.append(("当前仓库(已修复)", f == [], f))

# 6) 真阳性：把真实仓库某个访问器的成员改成「只在加载里被写」
#    模拟「配置项还在、但消费点被误删」这一重构退化。
target = None
for m in re.finditer(r'^\s*(?:const\s+)?[\w:<>]+\s+(\w+)\s*\(\s*\)\s*const\s*\{',
                     REAL_H, re.M):
    body_end = REAL_H.index("}", m.end())
    body = REAL_H[m.end():body_end]
    found = set(re.findall(r'\b(m_\w+)\b', body))
    if len(found) != 1:
        continue
    name = m.group(1)
    if name in ("instance", "load", "configPath"):
        continue
    member = found.pop()
    # 只在「该成员确实参与了配置加载」时才适合做这个注入
    if re.search(r'\b' + member + r'\b', REAL_C):
        target = (name, member)
        break

if target:
    name, member = target
    # 模拟「所有消费点被误删」：抹掉别处对 X() 的调用，
    # 并把成员改成只在加载代码里被写入（envOverride）。
    BROKEN_C = re.sub(r'\b' + member + r'\b', 'm_ghost_fallback', REAL_C)
    BROKEN_C = ("void AppConfig::%s()\n{\n"
                "    envOverride(\"X\", %s, toInt);\n}\n"
                % (ENV_FN, member)) + BROKEN_C
    f, w = run_real(REAL_H, BROKEN_C, scrub_accessor=name)
    hits = [x for x in f if name + "()" in x]
    cases.append(("消费点被误删: %s(真阳性-fail)" % name, len(hits) == 1, f))
else:
    cases.append(("消费点被误删(跳过-未找到样本)", True, []))

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
