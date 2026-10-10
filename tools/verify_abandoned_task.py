# -*- coding: utf-8 -*-
"""对 check_abandoned_async_tasks 做故障注入自检（纯 Python）。"""
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
    tmp = tempfile.mkdtemp(prefix="abandtask_")
    try:
        for rel, text in files.items():
            p = os.path.join(tmp, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        m = load()
        m.FAIL.clear()
        m.WARN.clear()
        m.check_abandoned_async_tasks(tmp, os.path.join(tmp, "src"))
        got = len(m.FAIL) > 0
        ok = got == expect_fail
        print("  [{}] {}  (fail={}, 期望fail={})".format(
            "PASS" if ok else "FAIL", name, got, expect_fail))
        if not ok:
            FAILED += 1
            for f in m.FAIL[:3]:
                print("        -> " + f[:170])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# 真阳性：每次播放都覆盖同一个成员，析构只等最后一个
C_ABANDON = """
#include "am.h"
#include <QtConcurrent/QtConcurrent>
void AudioManager::playAsync(const QString& f) {
    stop();
    flag = std::make_shared<std::atomic<bool>>(false);
    playFuture = QtConcurrent::run([=]() { play(f, flag.get()); });
}
AudioManager::~AudioManager() {
    stop();
    if (playFuture.isRunning()) playFuture.waitForFinished();
}
"""

# 真阴性：把未完成的 future 收集进容器
C_COLLECT = """
#include "am.h"
#include <QtConcurrent/QtConcurrent>
void AudioManager::playAsync(const QString& f) {
    stop();
    QVector<QFuture<void>> alive;
    for (const QFuture<void>& x : playFutures) if (x.isRunning()) alive.append(x);
    playFutures = alive;
    playFuture = QtConcurrent::run([=]() { play(f); });
    playFutures.append(playFuture);
}
void AudioManager::~AudioManager() { stop(); waitForAllTasks(); }
"""

# 真阴性：即发即忘（不赋给变量），由 QPointer 守卫
C_FIRE_AND_FORGET = """
#include "w.h"
#include <QtConcurrent/QtConcurrent>
void Widget::updateFrame() {
    QPointer<Widget> self(this);
    QtConcurrent::run([self]() {
        if (self.isNull()) return;
        QMetaObject::invokeMethod(self.data(), [](){}, Qt::QueuedConnection);
    });
}
"""

# 真阳性：局部变量被覆盖（同样丢任务）
C_LOCAL = """
#include "am.h"
#include <QtConcurrent/QtConcurrent>
void AudioManager::startBoth() {
    QFuture<void> t = QtConcurrent::run([=]() { a(); });
    t = QtConcurrent::run([=]() { b(); });
}
"""

print("== check_abandoned_async_tasks 故障注入自检 ==")
run_case("只留最后一个future(真阳性)",
         {"src/am.cpp": C_ABANDON}, True)
run_case("收集未完成任务(真阴性)",
         {"src/am.cpp": C_COLLECT}, False)
run_case("即发即忘+QPointer守卫(真阴性)",
         {"src/w.cpp": C_FIRE_AND_FORGET}, False)
run_case("局部future被覆盖(真阳性)",
         {"src/am2.cpp": C_LOCAL}, True)

# 真实仓库参与
TOTAL += 1
tmp = tempfile.mkdtemp(prefix="abandtask_real_")
try:
    shutil.copytree(os.path.join(ROOT, "src"), os.path.join(tmp, "src"))
    m = load()
    m.FAIL.clear()
    m.check_abandoned_async_tasks(tmp, os.path.join(tmp, "src"))
    ok = len(m.FAIL) == 0
    print("  [{}] 真实仓库 src/ 全量  (fail={})".format(
        "PASS" if ok else "FAIL", len(m.FAIL)))
    if not ok:
        FAILED += 1
        for f in m.FAIL[:5]:
            print("        -> " + f[:170])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n结果: {} 个用例失败 (共 {})".format(FAILED, TOTAL))
sys.exit(1 if FAILED else 0)
