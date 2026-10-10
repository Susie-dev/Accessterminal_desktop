# -*- coding: utf-8 -*-
"""check_wire_format_constants_are_pinned 的故障注入自检（两仓库通用）。

用法: verify_wire_format.py <verify.py> <本仓库根>

自足设计：合成夹具在临时仓库里**新建**测试文件/协议常量，不依赖本仓库里
恰好存在某个特定测试文件（原版硬编码 test_audio_sender.cpp，桌面端没有该文件，
照搬过去会直接 FileNotFoundError）。
"""
import importlib.util
import os
import shutil
import sys
import tempfile

VERIFY = os.path.abspath(sys.argv[1])
REPO = os.path.abspath(sys.argv[2])
FAILED = 0
TOTAL = 0


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


def run_case(name, expect_fail, build, patch_module=None):
    global FAILED, TOTAL
    TOTAL += 1
    tmp = tempfile.mkdtemp(prefix="wire_")
    try:
        root = os.path.join(tmp, "repo")
        safe_copytree(REPO, root)
        build(root)
        m = load()
        if patch_module:
            patch_module(m)
        m.FAIL.clear()
        m.WARN.clear()
        m.check_wire_format_constants_are_pinned(root, os.path.join(root, "src"))
        got = len(m.FAIL) > 0
        ok = got == expect_fail
        print("  [{}] {}  (fail={}, 期望fail={})".format(
            "PASS" if ok else "FAIL", name, got, expect_fail))
        if not ok:
            FAILED += 1
            for x in m.FAIL[:3]:
                print("        -> " + x[:170])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def consts_of(module):
    return list(module.WIRE_FORMAT_CONSTANTS)


def strip_from_tests(root, consts):
    tests = os.path.join(root, "tests")
    for fn in os.listdir(tests):
        if not fn.endswith((".cpp", ".h", ".hpp", ".c")):
            continue
        p = os.path.join(tests, fn)
        with open(p, encoding="utf-8") as f:
            s = f.read()
        for c in consts:
            s = s.replace(c, "REMOVED_CONST")
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)


def add_probe_const(root, name):
    """在 protocol.h 里新增一个线上常量（未在任何测试中断言）。

    注意插入点：不能用 `s.index("constexpr")` —— protocol.h 的文档注释里就
    写着 "constexpr" 这个词，插进去会落在注释内，导致 `strip_comments_and_strings`
    把它清掉、declared 集合里根本没有新常量，于是真阳性用例**静默漏报**
    （夹具失效，不是规则失效）。必须锚定**行首**的真实声明。
    """
    p = os.path.join(root, "src", "core", "net", "protocol.h")
    with open(p, encoding="utf-8") as f:
        s = f.read()
    lines = s.split("\n")
    for idx, line in enumerate(lines):
        if line.startswith("constexpr"):
            lines.insert(idx, "constexpr quint16 %s = 20;" % name)
            break
    else:
        raise AssertionError("protocol.h 里找不到行首 constexpr 声明")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))


def assert_probe_in_new_test(root, name):
    """新增一个测试文件断言该常量。"""
    tests = os.path.join(root, "tests")
    p = os.path.join(tests, "zz_probe.cpp")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write('#include "core/net/protocol.h"\n'
                "static const int kProbe = protocol::%s;\n" % name)


def add_to_list(module, name):
    module.WIRE_FORMAT_CONSTANTS = tuple(module.WIRE_FORMAT_CONSTANTS) + (name,)


def make_strip_all(consts):
    def f(root):
        strip_from_tests(root, consts)
    return f


def strip_and_comment(root):
    consts = consts_of(load())
    strip_from_tests(root, consts)
    p = os.path.join(root, "tests")
    # 找一个已存在的测试文件追加注释（或新建）
    target = None
    for fn in sorted(os.listdir(p)):
        if fn.endswith(".cpp"):
            target = os.path.join(p, fn)
            break
    if target is None:
        target = os.path.join(p, "zz_comment.cpp")
    with open(target, "a", encoding="utf-8", newline="\n") as f:
        f.write("\n// 注释里提一下：" + " ".join(consts) + "\n")


PROBE_UNCOVERED = "kProbeUncovered"
PROBE_COVERED = "kProbeCovered"


def add_uncovered(root):
    add_probe_const(root, PROBE_UNCOVERED)


def add_covered(root):
    add_probe_const(root, PROBE_COVERED)
    assert_probe_in_new_test(root, PROBE_COVERED)


print("== check_wire_format_constants_are_pinned 故障注入自检 ==")
run_case("当前仓库(真阴性)", False, lambda r: None)
run_case("测试里完全没有断言(真阳性)", True,
         make_strip_all(consts_of(load())))
run_case("只在注释里提及(真阳性)", True, strip_and_comment)
run_case("新增线上常量却无测试(真阳性)", True, add_uncovered,
         lambda m: add_to_list(m, PROBE_UNCOVERED))
run_case("新增常量且测试已断言(真阴性)", False, add_covered,
         lambda m: add_to_list(m, PROBE_COVERED))
run_case("清单里的常量在 protocol.h 不存在(真阴性)",
         False, lambda r: None, lambda m: add_to_list(m, "kNotInProtocolAtAll"))

TOTAL += 1
m = load()
m.FAIL.clear()
m.check_wire_format_constants_are_pinned(REPO, os.path.join(REPO, "src"))
ok = len(m.FAIL) == 0
print("  [{}] 真实仓库实测  (fail={})".format("PASS" if ok else "FAIL", len(m.FAIL)))
if not ok:
    FAILED += 1
    for x in m.FAIL[:3]:
        print("        -> " + x[:170])

print("\n结果: {}/{} 通过".format(TOTAL - FAILED, TOTAL))
sys.exit(1 if FAILED else 0)
