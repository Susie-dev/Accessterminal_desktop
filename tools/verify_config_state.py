# -*- coding: utf-8 -*-
"""对 check_load_state_reset / check_narrowing_cast_of_config 做故障注入自检。"""
import importlib.util
import os
import shutil
import sys
import tempfile

VERIFY = sys.argv[1]
ROOT = sys.argv[2]
FAILED = 0
TOTAL = 0


def load():
    spec = importlib.util.spec_from_file_location("v", VERIFY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_case(name, files, checkname, expect_fail):
    global FAILED, TOTAL
    TOTAL += 1
    tmp = tempfile.mkdtemp(prefix="cfgrule_")
    try:
        for rel, text in files.items():
            p = os.path.join(tmp, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        m = load()
        m.FAIL.clear()
        m.WARN.clear()
        getattr(m, checkname)(tmp, os.path.join(tmp, "src"))
        got = len(m.FAIL) > 0
        ok = got == expect_fail
        print("  [{}] {}  (fail={}, 期望fail={})".format(
            "PASS" if ok else "FAIL", name, got, expect_fail))
        if not ok:
            FAILED += 1
            for x in m.FAIL[:3]:
                print("        -> " + x[:160])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------- check_load_state_reset ----------------
LOAD_BAD = """
#include "app_config.h"
bool AppConfig::load(const QString& p) {
    applyDefaults();
    QFile f(p);
    if (f.open(QIODevice::ReadOnly)) {
        m_loadedFromFile = true;
        m_configPath = p;
    }
    return m_loadedFromFile;
}
"""
LOAD_GOOD = """
#include "app_config.h"
bool AppConfig::load(const QString& p) {
    applyDefaults();
    m_loadedFromFile = false;
    m_configPath.clear();
    QFile f(p);
    if (f.open(QIODevice::ReadOnly)) {
        m_loadedFromFile = true;
        m_configPath = p;
    }
    return m_loadedFromFile;
}
"""
# 真阴性：用函数局部变量，天然无此问题（门口机的写法）
LOAD_LOCAL = """
#include "app_config.h"
bool AppConfig::load(const QString& p) {
    applyDefaults();
    bool fileLoaded = false;
    QFile f(p);
    if (f.open(QIODevice::ReadOnly)) {
        fileLoaded = true;
    }
    return fileLoaded;
}
"""

# ---------------- check_narrowing_cast_of_config ----------------
CAST_BAD = """
#include "app_config.h"
void AppConfig::parse(const QJsonObject& net) {
    m_signalingPort = static_cast<quint16>(
        jsonInt(net, QStringLiteral("signaling_port"), m_signalingPort));
}
"""
CAST_GOOD = """
#include "app_config.h"
void AppConfig::parse(const QJsonObject& net) {
    m_signalingPort = static_cast<quint16>(
        clampInt(jsonInt(net, QStringLiteral("signaling_port"), m_signalingPort),
                 1, 65535));
}
"""
# 真阴性：窄 cast 的实参不是配置读取函数（普通算术）
CAST_OTHER = """
#include "app_config.h"
void f(int x) {
    const quint16 p = static_cast<quint16>(x + 1);
}
"""

print("== check_load_state_reset 故障注入自检 ==")
run_case("末尾return成员且未复位(真阳性)",
         {"src/app_config.cpp": LOAD_BAD}, "check_load_state_reset", True)
run_case("开头复位(真阴性)",
         {"src/app_config.cpp": LOAD_GOOD}, "check_load_state_reset", False)
run_case("用函数局部变量(真阴性)", 
         {"src/app_config.cpp": LOAD_LOCAL}, "check_load_state_reset", False)

print()
print("== check_narrowing_cast_of_config 故障注入自检 ==")
run_case("cast前未夹取(真阳性)",
         {"src/app_config.cpp": CAST_BAD}, "check_narrowing_cast_of_config", True)
run_case("cast前已夹取(真阴性)",
         {"src/app_config.cpp": CAST_GOOD}, "check_narrowing_cast_of_config", False)
run_case("cast实参非配置读取(真阴性)",
         {"src/app_config.cpp": CAST_OTHER}, "check_narrowing_cast_of_config", False)

TOTAL += 1
tmp = tempfile.mkdtemp(prefix="cfgrule_real_")
try:
    shutil.copytree(os.path.join(ROOT, "src"), os.path.join(tmp, "src"))
    m = load()
    m.FAIL.clear()
    m.check_load_state_reset(tmp, os.path.join(tmp, "src"))
    m.check_narrowing_cast_of_config(tmp, os.path.join(tmp, "src"))
    ok = len(m.FAIL) == 0
    print()
    print("  [{}] 真实仓库 src/ 全量  (fail={})".format(
        "PASS" if ok else "FAIL", len(m.FAIL)))
    if not ok:
        FAILED += 1
        for x in m.FAIL[:5]:
            print("        -> " + x[:170])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("结果: {} 个用例失败 (共 {})".format(FAILED, TOTAL))
sys.exit(1 if FAILED else 0)
