# -*- coding: utf-8 -*-
"""对 check_subproject_cmake_is_selfcontained 做故障注入自检（纯 Python）。"""
import importlib.util
import os
import shutil
import sys
import tempfile

VERIFY = sys.argv[1]
ROOT = sys.argv[2]
FAILED = 0
TOTAL = 0

GOOD = """\
cmake_minimum_required(VERSION 3.16)
project(t LANGUAGES CXX)
set(CMAKE_AUTOMOC ON)
enable_testing()
find_package(Qt5 5.12 REQUIRED COMPONENTS Core Test)
add_executable(test_x test_x.cpp)
add_test(NAME x COMMAND test_x)
"""
GOOD_CPP = '#include "test_x.moc"\n'

NO_MINIMUM = """\
project(t LANGUAGES CXX)
enable_testing()
add_executable(test_x test_x.cpp)
add_test(NAME x COMMAND test_x)
"""
NO_PROJECT = """\
cmake_minimum_required(VERSION 3.16)
enable_testing()
add_executable(test_x test_x.cpp)
add_test(NAME x COMMAND test_x)
"""
NO_ENABLE_TESTING = """\
cmake_minimum_required(VERSION 3.16)
project(t LANGUAGES CXX)
add_executable(test_x test_x.cpp)
add_test(NAME x COMMAND test_x)
"""
NO_AUTOMOC = """\
cmake_minimum_required(VERSION 3.16)
project(t LANGUAGES CXX)
enable_testing()
add_executable(test_x test_x.cpp)
add_test(NAME x COMMAND test_x)
"""
NO_MOC_INCLUDE_CPP = "int main(){return 0;}\n"


def load():
    spec = importlib.util.spec_from_file_location("v", VERIFY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_case(name, tests_cmake, tests_cpp, expect_fail):
    global FAILED, TOTAL
    TOTAL += 1
    tmp = tempfile.mkdtemp(prefix="subcmake_")
    try:
        with open(os.path.join(tmp, "CMakeLists.txt"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write("cmake_minimum_required(VERSION 3.16)\n"
                    "project(主工程 LANGUAGES CXX)\n"
                    "enable_testing()\nset(CMAKE_AUTOMOC ON)\n")
        d = os.path.join(tmp, "tests")
        os.makedirs(d)
        with open(os.path.join(d, "CMakeLists.txt"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(tests_cmake)
        with open(os.path.join(d, "test_x.cpp"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(tests_cpp)
        m = load()
        m.FAIL.clear()
        m.WARN.clear()
        m.check_subproject_cmake_is_selfcontained(tmp, os.path.join(tmp, "src"))
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


print("== check_subproject_cmake_is_selfcontained 故障注入自检 ==")
run_case("完整子工程(真阴性)", GOOD, GOOD_CPP, False)
run_case("缺 cmake_minimum_required(真阳性)", NO_MINIMUM, GOOD_CPP, True)
run_case("缺 project(真阳性)", NO_PROJECT, GOOD_CPP, True)
run_case("缺 enable_testing(真阳性)", NO_ENABLE_TESTING, GOOD_CPP, True)
run_case("缺 AUTOMOC 且有 .moc include(真阳性)", NO_AUTOMOC, GOOD_CPP, True)
run_case("缺 AUTOMOC 但无 .moc include(真阴性)", NO_AUTOMOC,
         NO_MOC_INCLUDE_CPP, False)

# 真实仓库
for label, repo in (("门口机", ROOT), ("室内机", sys.argv[3])):
    TOTAL += 1
    m = load()
    m.FAIL.clear()
    m.WARN.clear()
    m.check_subproject_cmake_is_selfcontained(repo, os.path.join(repo, "src"))
    ok = len(m.FAIL) == 0
    print("  [{}] 真实仓库 {}  (fail={})".format(
        "PASS" if ok else "FAIL", label, len(m.FAIL)))
    if not ok:
        FAILED += 1
        for x in m.FAIL[:5]:
            print("        -> " + x[:170])

print("\n结果: {} 个用例失败 (共 {})".format(FAILED, TOTAL))
sys.exit(1 if FAILED else 0)
