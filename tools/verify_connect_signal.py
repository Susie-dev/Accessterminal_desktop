# -*- coding: utf-8 -*-
"""自检 check_connect_signal_is_signal，重点覆盖"首实参含 -> 导致静默跳过"这一
潜在漏检（本轮修复）。

该检查按**顶层逗号**切分 connect 实参。此前的切分器把 `>` 也当成需要配对的
括号（`if ch in "(<[" / elif ch in ")>]"`），于是每遇到一个 `->`，深度就偏负
一次，顶层逗号再也分不出来 —— 整个实参列表被当成 1 个实参，函数随即因
`len(args) < 2` 而 `continue`，**跳过所有首实参含 `->` 的 connect**。

真实后果：`connect(ui->someWidget, &Cls::notASignal, ...)` 这类写法（正是本
工程最常见的形式）完全不被检查。下面的用例专门锁死这一点。
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
    tmp = tempfile.mkdtemp(prefix="connsig_")
    try:
        for rel, text in files.items():
            p = os.path.join(tmp, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        m = load()
        m.FAIL.clear()
        m.WARN.clear()
        m.check_connect_signal_is_signal(tmp, os.path.join(tmp, "src"))
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


H = """
#include <QObject>
class Form : public QObject {
    Q_OBJECT
public:
    Form() {}
public slots:
    void onOk();          // 槽：不能当信号源
signals:
    void realSignal();    // 信号：可以当信号源
};
"""

# 真阳性：首实参含 `->`，第二实参是槽 —— 旧切分器会整条静默跳过
C_ARROW_BAD = """
#include "form.h"
#include <QPushButton>
void Form::setup() {
    connect(ui->btnOk, &Form::onOk, this, &Form::onOk);
}
"""

# 真阴性：首实参含 `->`，第二实参是真信号
C_ARROW_OK = """
#include "form.h"
#include <QPushButton>
void Form::setup() {
    connect(ui->btnOk, &Form::realSignal, this, &Form::onOk);
}
"""

# 真阳性：无 `->`，第二实参是槽（旧版也能查到，作对照）
C_PLAIN_BAD = """
#include "form.h"
void Form::setup() {
    connect(this, &Form::onOk, this, &Form::onOk);
}
"""

print("== check_connect_signal_is_signal 故障注入自检 ==")
run_case("首实参含->且第二实参是槽(真阳性)",
         {"src/form.h": H, "src/form.cpp": C_ARROW_BAD}, True)
run_case("首实参含->且第二实参是信号(真阴性)",
         {"src/form.h": H, "src/form.cpp": C_ARROW_OK}, False)
run_case("无->且第二实参是槽(真阳性)",
         {"src/form.h": H, "src/form.cpp": C_PLAIN_BAD}, True)
run_case("当前仓库", {}, False)

# 真实仓库参与
TOTAL += 1
tmp = tempfile.mkdtemp(prefix="connsig_real_")
try:
    shutil.copytree(os.path.join(ROOT, "src"), os.path.join(tmp, "src"))
    m = load()
    m.FAIL.clear()
    m.check_connect_signal_is_signal(tmp, os.path.join(tmp, "src"))
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
