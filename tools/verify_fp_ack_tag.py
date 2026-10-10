# -*- coding: utf-8 -*-
"""check_fingerprint_ack_tag_is_validated 的故障注入自检（两仓库通用）。"""
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

# 合成源文件：一个校验了包标识（应放行），一个没校验（应告警）
GOOD_SRC = """#include <QByteArray>
class Probe {
public:
    void good(const QByteArray& resp);
    void bad(const QByteArray& resp);
};
void Probe::good(const QByteArray& resp)
{
    if (resp.size() < 12 || (quint8)resp[6] != PKT_ACK) {
        return;
    }
    quint8 confirm = (quint8)resp[9];
    (void)confirm;
}
"""

BAD_SRC = """#include <QByteArray>
class Probe {
public:
    void bad(const QByteArray& resp);
};
void Probe::bad(const QByteArray& resp)
{
    if (resp.size() < 12) {
        return;
    }
    quint8 confirm = (quint8)resp[9];
    (void)confirm;
}
"""


def load():
    spec = importlib.util.spec_from_file_location("v", VERIFY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def safe_copytree(src, dst):
    def ig(_d, names):
        return {n for n in names if n in (".git", "build") or n.startswith("build-")}
    shutil.copytree(src, dst, ignore=ig)


def run_case(name, expect_fail, build):
    global FAILED, TOTAL
    TOTAL += 1
    tmp = tempfile.mkdtemp(prefix="acktag_")
    try:
        root = os.path.join(tmp, "repo")
        safe_copytree(REPO, root)
        build(root)
        m = load()
        m.FAIL.clear()
        m.WARN.clear()
        m.check_fingerprint_ack_tag_is_validated(root, os.path.join(root, "src"))
        got = len(m.WARN) > 0
        ok = got == expect_fail
        print("  [{}] {}  (warn={}, 期望warn={})".format(
            "PASS" if ok else "FAIL", name, got, expect_fail))
        if not ok:
            FAILED += 1
            for x in m.WARN[:1]:
                print("        -> " + x[:150])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def strip_real_offenders(root):
    """清掉真实仓库里已知的"未校验包标识"文件。

    否则负向用例（合成一个校验过的文件，期望**没有**告警）会被真实仓库里
    本来就存在的告警污染 —— 我第一版就踩了这个坑：真阴性用例恒为 warn=True。
    成功与失败都必须只由合成夹具决定。
    """
    for rel in (os.path.join("src", "hal", "fingerprint_hailin.cpp"),
                os.path.join("src", "managers", "fingerprint_manager.cpp"),
                os.path.join("src", "ui", "form_finger.cpp")):
        p = os.path.join(root, rel)
        if os.path.exists(p):
            os.remove(p)


def only_good(root):
    strip_real_offenders(root)
    d = os.path.join(root, "src", "probe")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "probe_good.cpp"), "w", encoding="utf-8",
              newline="\n") as f:
        f.write(GOOD_SRC)


def only_bad(root):
    strip_real_offenders(root)
    d = os.path.join(root, "src", "probe")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "probe_bad.cpp"), "w", encoding="utf-8",
              newline="\n") as f:
        f.write(BAD_SRC)


print("== check_fingerprint_ack_tag_is_validated 故障注入自检 ==")
run_case("校验了包标识 -> 不告警(真阴性)", False, only_good)
run_case("没校验包标识 -> 告警(真阳性)", True, only_bad)

TOTAL += 1
m = load()
m.FAIL.clear()
m.WARN.clear()
m.check_fingerprint_ack_tag_is_validated(REPO, os.path.join(REPO, "src"))
n = len(m.WARN)
# 本仓库是否真的有指纹代码。桌面端（室内机）完全没有指纹通路，此时
# "真实仓库必须告警"这一期望不成立 —— 规则对它是 no-op，属正常情况，
# 不能算失败（两仓库共用同一个自检脚本）。
has_fp = any(os.path.exists(os.path.join(REPO, p))
             for p in (os.path.join("src", "hal", "fingerprint_hailin.cpp"),
                       os.path.join("src", "managers", "fingerprint_manager.cpp")))
if has_fp:
    ok = n > 0
    print("  [{}] 真实仓库实测  (含指纹代码，告警 {} 项)".format(
        "PASS" if ok else "FAIL", n))
    if not ok:
        FAILED += 1
else:
    print("  [PASS] 真实仓库实测  (本仓库无指纹代码，规则为 no-op)")

print("\n结果: {}/{} 通过".format(TOTAL - FAILED, TOTAL))
sys.exit(1 if FAILED else 0)
