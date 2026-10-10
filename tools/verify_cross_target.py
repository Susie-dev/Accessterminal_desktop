# -*- coding: utf-8 -*-
"""check_cross_repo_test_targets_are_unique 的故障注入自检。

用法: verify_cross_target.py <verify.py> <本仓库根> <另一仓库根>
"""
import importlib.util
import os
import shutil
import sys
import tempfile

VERIFY = sys.argv[1]
OWN = os.path.abspath(sys.argv[2])
OTHER = os.path.abspath(sys.argv[3])
FAILED = 0
TOTAL = 0


def load():
    spec = importlib.util.spec_from_file_location("v", VERIFY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def make_repo(tmp, name, cml):
    r = os.path.join(tmp, name)
    os.makedirs(os.path.join(r, "tests"), exist_ok=True)
    with open(os.path.join(r, "tests", "CMakeLists.txt"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write(cml)
    return r


def run_case(name, own_cml, other_cml, expect_fail):
    global FAILED, TOTAL
    TOTAL += 1
    tmp = tempfile.mkdtemp(prefix="cross_")
    try:
        own = make_repo(tmp, "own", own_cml)
        other = make_repo(tmp, "other", other_cml)
        m = load()
        m.FAIL.clear()
        m.WARN.clear()
        m.check_cross_repo_test_targets_are_unique(own, other)
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


BASE = """
cmake_minimum_required(VERSION 3.16)
project(x LANGUAGES CXX)
enable_testing()
"""

OWN = BASE + "add_executable(t113_test_protocol t.cpp)\nadd_test(NAME t113_protocol COMMAND t113_test_protocol)\n"
DUP_TARGET = BASE + "add_executable(t113_test_protocol t.cpp)\nadd_test(NAME other_case COMMAND t113_test_protocol)\n"
DUP_CASE = BASE + "add_executable(other_target t.cpp)\nadd_test(NAME t113_protocol COMMAND other_target)\n"
UNIQ = BASE + "add_executable(desktop_test_protocol t.cpp)\nadd_test(NAME desktop_protocol COMMAND desktop_test_protocol)\n"

print("== check_cross_repo_test_targets_are_unique 故障注入自检 ==")
run_case("目标重名(真阳性)", OWN, DUP_TARGET, True)
run_case("仅 ctest 用例名重名(真阳性)", OWN, DUP_CASE, True)
run_case("目标与用例名都唯一(真阴性)", OWN, UNIQ, False)
run_case("另一仓库无 tests/(真阴性)", OWN, BASE, False)

# 真实跨仓库实测
TOTAL += 1
m = load()
m.FAIL.clear()
m.check_cross_repo_test_targets_are_unique(OWN, OTHER)
ok = len(m.FAIL) == 0
print()
print("  [{}] 真实两仓库实测  (fail={})".format("PASS" if ok else "FAIL", len(m.FAIL)))
if not ok:
    FAILED += 1
    for x in m.FAIL[:4]:
        print("        -> " + x[:170])

print()
print("结果: {} 个用例失败 (共 {})".format(FAILED, TOTAL))
sys.exit(1 if FAILED else 0)
