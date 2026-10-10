# -*- coding: utf-8 -*-
"""check_gated_wire_paths_have_resume_test 的故障注入自检（两仓库通用）。

用法: verify_gated_resume.py [verify.py] [本仓库根]

自足设计：不依赖本仓库里恰好存在某个推流源文件（桌面端没有
camera_preview_server.cpp，照搬会 FileNotFoundError）。真阳性用例在临时仓库里
**新建**合成闸门源文件与合成测试文件来构造。
"""
import importlib.util
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
VERIFY = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else \
    os.path.join(_HERE, "verify.py")
REPO = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else \
    os.path.dirname(_HERE)
FAILED = 0
TOTAL = 0

MEDIA = os.path.join("src", "core", "media")

# 合成闸门源文件：开始/停止各一处，形态与 CameraUdpServer 一致
# 注意：调用必须**恰好**写成 `X->start()` / `X->stop()`。
# 规则的正则是 `\bstart\s*\(`，要求 "start" 之后就是 '('；
# 若写成 `startTimer()`，'start' 后面紧跟 'T'（单词字符），`\b` 不成立，
# 夹具永远不会被识别为闸门，真阳性用例就会静默漏报。
GATE_SRC = """class ProbePusher {
public:
    void onReadyRead();
    void sendFrame();
private:
    bool sending;
    ProbeTimer* m_timer;
};

void ProbePusher::onReadyRead()
{
    if (!sending) {
        sending = true;
        m_timer->start();
    }
    if (false) {
        sending = false;
        m_timer->stop();
    }
}
void ProbePusher::sendFrame() {}
"""


def load():
    spec = importlib.util.spec_from_file_location("v", VERIFY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def safe_copytree(src, dst):
    def ig(_d, names):
        return {n for n in names
                if n in (".git", "build") or n.startswith("build-")}
    shutil.copytree(src, dst, ignore=ig)


def run_case(name, expect_fail, build):
    global FAILED, TOTAL
    TOTAL += 1
    tmp = tempfile.mkdtemp(prefix="gated_")
    try:
        root = os.path.join(tmp, "repo")
        safe_copytree(REPO, root)
        build(root)
        m = load()
        m.FAIL.clear()
        m.WARN.clear()
        m.check_gated_wire_paths_have_resume_test(root, os.path.join(root, "src"))
        got = len(m.FAIL) > 0
        ok = got == expect_fail
        print("  [{}] {}  (fail={}, 期望fail={})".format(
            "PASS" if ok else "FAIL", name, got, expect_fail))
        if not ok:
            FAILED += 1
            for x in m.FAIL[:2]:
                print("        -> " + x[:160])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def add_gate(root):
    # 先删掉真实的闸门源文件，否则规则的启用条件会被它满足，
    # 合成夹具即使写错也发现不了 —— 夹具本身就成了"未被测试的测试代码"。
    # 删掉后，规则是否启用完全由下面的合成夹具决定，两仓库强度一致。
    real = os.path.join(root, MEDIA, "camera_preview_server.cpp")
    if os.path.exists(real):
        os.remove(real)
    d = os.path.join(root, MEDIA)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "probe_gate.cpp"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write(GATE_SRC)


def add_gate_and_resume_test(root):
    add_gate(root)
    tests = os.path.join(root, "tests")
    os.makedirs(tests, exist_ok=True)
    with open(os.path.join(tests, "zz_probe_resume.cpp"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("// 开始 -> 停止 -> 再次开始（resume）必须能恢复\n"
                "void probeResumesPushing() {}\n")


def strip_resume_markers(root):
    """去掉测试里所有"恢复"语义的标记，模拟"只测了停止"。

    先确保仓库里有一个闸门源文件，否则规则本就不启用（无真阳性可言）。
    """
    add_gate(root)
    tests = os.path.join(root, "tests")
    for fn in os.listdir(tests):
        if not fn.endswith((".cpp", ".h", ".hpp", ".c")):
            continue
        p = os.path.join(tests, fn)
        with open(p, encoding="utf-8") as f:
            s = f.read()
        for mk in ("Resumes", "resume", "Resume", "reopen", "Reopen",
                   "restart", "Restart", "恢复", "再次", "重新开始"):
            s = s.replace(mk, "XX")
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)


def no_gate_at_all(root):
    """真阴性：仓库里没有任何闸门 -> 规则不启用。"""
    for name in ("camera_preview_server.cpp", "probe_gate.cpp"):
        p = os.path.join(root, MEDIA, name)
        if os.path.exists(p):
            os.remove(p)


print("== check_gated_wire_paths_have_resume_test 故障注入自检 ==")
run_case("当前仓库(真阴性)", False, lambda r: None)
run_case("有闸门但测试没有恢复语义(真阳性)", True, strip_resume_markers)
run_case("有闸门且测试覆盖了恢复(真阴性)", False, add_gate_and_resume_test)
run_case("仓库里没有闸门则不该要求(真阴性)", False, no_gate_at_all)

TOTAL += 1
m = load()
m.FAIL.clear()
m.check_gated_wire_paths_have_resume_test(REPO, os.path.join(REPO, "src"))
ok = len(m.FAIL) == 0
print("  [{}] 真实仓库实测  (fail={})".format("PASS" if ok else "FAIL", len(m.FAIL)))
if not ok:
    FAILED += 1
    for x in m.FAIL[:2]:
        print("        -> " + x[:160])

print("\n结果: {}/{} 通过".format(TOTAL - FAILED, TOTAL))
sys.exit(1 if FAILED else 0)
