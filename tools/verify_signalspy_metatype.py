# -*- coding: utf-8 -*-
"""check_signalspy_types_are_registered 的故障注入自检（两仓库通用）。"""
import importlib.util
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
VERIFY = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else \
    os.path.join(_HERE, "verify.py")
REPO = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.dirname(_HERE)
FAILED = 0
TOTAL = 0

# 合成夹具：注册了 vs 没注册
GOOD_SRC = """#include <QSignalSpy>
#include <QTcpSocket>
#include "core/net/protocol.h"
Q_DECLARE_METATYPE(accessterminal::protocol::Signal)
class P : public QObject {
    Q_OBJECT
private slots:
    void t() {
        qRegisterMetaType<accessterminal::protocol::Signal>(
            "accessterminal::protocol::Signal");
        qRegisterMetaType<QTcpSocket*>("QTcpSocket*");
        QSignalSpy spy(this, 0);
        spy.at(0).at(0).value<accessterminal::protocol::Signal>();
        spy.at(0).at(1).value<QTcpSocket*>();
    }
};
"""

BAD_SRC = """#include <QSignalSpy>
#include <QTcpSocket>
#include "core/net/protocol.h"
Q_DECLARE_METATYPE(accessterminal::protocol::Signal)
class P : public QObject {
    Q_OBJECT
private slots:
    void t() {
        QSignalSpy spy(this, 0);
        spy.at(0).at(0).value<accessterminal::protocol::Signal>();
        spy.at(0).at(1).value<QTcpSocket*>();
    }
};
"""

# 只注册 Signal、漏掉 QTcpSocket* —— 这是实测里真实的半缺失情况
HALF_SRC = """#include <QSignalSpy>
#include <QTcpSocket>
#include "core/net/protocol.h"
Q_DECLARE_METATYPE(accessterminal::protocol::Signal)
class P : public QObject {
    Q_OBJECT
private slots:
    void t() {
        qRegisterMetaType<accessterminal::protocol::Signal>(
            "accessterminal::protocol::Signal");
        QSignalSpy spy(this, 0);
        spy.at(0).at(0).value<accessterminal::protocol::Signal>();
        spy.at(0).at(1).value<QTcpSocket*>();
    }
};
"""


def load():
    spec = importlib.util.spec_from_file_location("v", VERIFY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def make(mutate):
    tmp = tempfile.mkdtemp(prefix="smetatype_")
    root = os.path.join(tmp, "repo")
    shutil.copytree(REPO, root, ignore=shutil.ignore_patterns(
        ".git", "build", "build-*"))
    mutate(root)
    m = load()
    m.FAIL.clear()
    m.WARN.clear()
    m.check_signalspy_types_are_registered(root, os.path.join(root, "src"))
    return tmp, list(m.FAIL)


def only(root, src):
    d = os.path.join(root, "tests")
    os.makedirs(d, exist_ok=True)
    # 清掉真实测试文件，让判定只由夹具决定
    for f in os.listdir(d):
        if f.endswith(".cpp"):
            os.remove(os.path.join(d, f))
    with open(os.path.join(d, "probe.cpp"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(src)


def run_case(name, src, expect_fail_count):
    global FAILED, TOTAL
    TOTAL += 1
    tmp, fails = make(lambda r: only(r, src))
    try:
        ok = len(fails) == expect_fail_count
        print("  [{}] {}  (失败 {} 项, 期望 {})".format(
            "PASS" if ok else "FAIL", name, len(fails), expect_fail_count))
        if not ok:
            FAILED += 1
            for x in fails:
                print("        -> " + x[:130])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


print("== check_signalspy_types_are_registered 故障注入自检 ==")
run_case("两种类型都注册 -> 无告警(真阴性)", GOOD_SRC, 0)
run_case("两种类型都漏 -> 2 项(真阳性)", BAD_SRC, 2)
run_case("只漏 QTcpSocket* -> 1 项(半缺失也能抓)", HALF_SRC, 1)

# 真实仓库实测：本仓库若有 QSignalSpy 测试，必须全绿
TOTAL += 1
m = load()
m.FAIL.clear()
m.WARN.clear()
m.check_signalspy_types_are_registered(REPO, os.path.join(REPO, "src"))
n = len(m.FAIL)
ok = n == 0
print("  [{}] 真实仓库实测  ({} 项)".format("PASS" if ok else "FAIL",
                                            "无问题" if n == 0 else "{} 项问题".format(n)))
if not ok:
    FAILED += 1
    for x in m.FAIL:
        print("        -> " + x[:130])

print("\n结果: {}/{} 通过".format(TOTAL - FAILED, TOTAL))
sys.exit(1 if FAILED else 0)
