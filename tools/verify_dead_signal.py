# -*- coding: utf-8 -*-
"""对 check_declared_signal_is_emitted 做故障注入自检（纯 Python）。

重点覆盖我自己在写这条规则时踩到的两个坑：
  - 把 `public slots:` 当成 signals: 的延续 → 槽被误判为信号；
  - 忽略信号→信号链式连接（connect 的第 4 实参）→ 链式目标被误判为死信号。
"""
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


def run_case(name, files, expect_fail):
    global FAILED, TOTAL
    TOTAL += 1
    tmp = tempfile.mkdtemp(prefix="deadsig_")
    try:
        for rel, text in files.items():
            p = os.path.join(tmp, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        m = load()
        m.FAIL.clear()
        m.WARN.clear()
        m.check_declared_signal_is_emitted(tmp, os.path.join(tmp, "src"))
        got = len(m.FAIL) > 0
        ok = got == expect_fail
        print("  [{}] {}  (fail={}, 期望fail={})".format(
            "PASS" if ok else "FAIL", name, got, expect_fail))
        if not ok:
            FAILED += 1
            for f in m.FAIL[:3]:
                print("        -> " + f[:160])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


HEAD = """
#include <QObject>
class Worker : public QObject {
    Q_OBJECT
public:
    Worker() {}
signals:
    void dataReady(int v);
%s
};
"""

# 真阳性：声明了但从未 emit，也没被链式连接
C_DEAD = """
#include "worker.h"
void Worker::startWork() { }
"""

# 真阴性：显式 emit
C_LIVE = """
#include "worker.h"
void Worker::startWork() { emit dataReady(1); }
"""

# 真阴性：无 emit 关键字，直接调用信号
C_DIRECT = """
#include "worker.h"
void Worker::startWork() { dataReady(1); }
"""

# 真阴性：信号->信号 链式连接（第 4 实参）
#
# 注意 `other` 是**源**信号（第 2 实参），它自己必须另有 emit 出口，
# 否则它本身就是死信号（这是本检查的正确行为，不是误报）。
# `dataReady` 作为第 4 实参出现 → 被链式触发 → 活跃。
C_CHAIN = """
#include "worker.h"
void Worker::startWork() {
    emit other();
    connect(this, &Worker::other, this, &Worker::dataReady);
}
"""

# 真阳性：链式连接的**源**信号从未发射 —— 那么链式目标虽被"连接"，
# 整条链仍然永远不会触发。此处只要求检查发现源信号 other 是死的。
C_CHAIN_DEAD_SRC = """
#include "worker.h"
void Worker::startWork() {
    connect(this, &Worker::other, this, &Worker::dataReady);
}
"""

# 坑 1：public slots: 里的槽不得被当成信号
H_SLOT = """
#include <QObject>
class Worker : public QObject {
    Q_OBJECT
public:
    Worker() {}
signals:
    void dataReady(int v);
public slots:
    void onDataReady(int v);
private slots:
    void onInternal();
};
"""
C_SLOT = """
#include "worker.h"
void Worker::onDataReady(int v) { }
void Worker::onInternal() { }
void Worker::kick() { emit dataReady(1); }
"""

# 坑 2：链式目标必须有 connect（否则仍是死信号）
H_TWO = """
#include <QObject>
class Worker : public QObject {
    Q_OBJECT
public:
    Worker() {}
signals:
    void dataReady(int v);
    void neverFired(int v);
};
"""
C_TWO = """
#include "worker.h"
void Worker::startWork() {
    connect(this, &Worker::dataReady, this, &Worker::dataReady);
}
"""

# 非 Q_OBJECT 的类不参与
H_PLAIN = """
#include <QObject>
class Plain {
public:
    Plain() {}
signals:
    void orphanSig();
};
"""

print("== check_declared_signal_is_emitted 故障注入自检 ==")
run_case("声明但从未发射(真阳性)",
         {"src/worker.h": HEAD % "", "src/worker.cpp": C_DEAD,
          "src/other.cpp": "void x(){}"}, True)
run_case("显式emit(真阴性)",
         {"src/worker.h": HEAD % "", "src/worker.cpp": C_LIVE}, False)
run_case("无emit直接调用(真阴性)",
         {"src/worker.h": HEAD % "", "src/worker.cpp": C_DIRECT}, False)
run_case("信号->信号链式连接(真阴性)",
         {"src/worker.h": HEAD % "    void other();", "src/worker.cpp": C_CHAIN},
         False)
run_case("链式连接的源信号本身是死的(真阳性)",
         {"src/worker.h": HEAD % "    void other();",
          "src/worker.cpp": C_CHAIN_DEAD_SRC}, True)
run_case("槽不得被误判为信号(真阴性)",
         {"src/worker.h": H_SLOT, "src/worker.cpp": C_SLOT}, False)
run_case("另一个信号仍是死的(真阳性)",
         {"src/worker.h": H_TWO, "src/worker.cpp": C_TWO}, True)
run_case("非Q_OBJECT类不判定(真阴性)",
         {"src/plain.h": H_PLAIN, "src/plain.cpp": "int y(){return 0;}"}, False)
run_case("当前仓库已修复", {}, False)

# 真实仓库参与
TOTAL += 1
tmp = tempfile.mkdtemp(prefix="deadsig_real_")
try:
    shutil.copytree(os.path.join(ROOT, "src"), os.path.join(tmp, "src"))
    m = load()
    m.FAIL.clear()
    m.check_declared_signal_is_emitted(tmp, os.path.join(tmp, "src"))
    ok = len(m.FAIL) == 0
    print("  [{}] 真实仓库 src/ 全量  (fail={})".format(
        "PASS" if ok else "FAIL", len(m.FAIL)))
    if not ok:
        FAILED += 1
        for f in m.FAIL[:5]:
            print("        -> " + f[:160])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n结果: {} 个用例失败 (共 {})".format(FAILED, TOTAL))
sys.exit(1 if FAILED else 0)
