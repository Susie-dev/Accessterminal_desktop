# -*- coding: utf-8 -*-
"""对 check_hex_parse_is_validated 做故障注入自检（纯 Python）。注意：
本检查的语义已用**真实 Qt** 在 tests/test_app_config.cpp 中独立验证过
（fromHex 对偶数长度非法输入返回非空的错位结果），此处只验证静态规则的判据。
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
    tmp = tempfile.mkdtemp(prefix="hexparse_")
    try:
        for rel, text in files.items():
            p = os.path.join(tmp, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        m = load()
        m.FAIL.clear()
        m.WARN.clear()
        m.check_hex_parse_is_validated(tmp, os.path.join(tmp, "src"))
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


# 真阳性：变量直接进 fromHex，无任何校验（修复前的真实形态）
BAD = """
#include "app_config.h"
static QByteArray parseHexBytes(const QString& text) {
    QString compact = text;
    if (compact.isEmpty() || compact.size() % 2 != 0) return QByteArray();
    return QByteArray::fromHex(compact.toLatin1());
}
"""

# 真阴性：有显式逐字符校验
GOOD = """
#include "app_config.h"
static bool isHexOnly(const QString& t) {
    for (int i = 0; i < t.size(); ++i) {
        const QChar c = t.at(i);
        if (!((c >= QChar('0') && c <= QChar('9')))) return false;
    }
    return true;
}
static QByteArray parseHexBytes(const QString& text) {
    if (!isHexOnly(text)) return QByteArray();
    return QByteArray::fromHex(text.toLatin1());
}
"""

# 真阴性：只对字面量调用 fromHex
LITERAL_ONLY = """
#include "app_config.h"
void applyDefaults() {
    m_lightCommands.insert(QStringLiteral("desk"), QByteArray::fromHex("FD034C12045DDF"));
    m_lightCommands.insert(QStringLiteral("work"), QByteArray::fromHex("FD034C12025DDF"));
}
"""

# 真阴性：用函数式校验
GOOD_FUNCCHECK = """
#include "app_config.h"
QByteArray f(const QString& s) {
    if (!validateHexOnly(s)) return QByteArray();
    return QByteArray::fromHex(s.toLatin1());
}
"""

print("== check_hex_parse_is_validated 故障注入自检 ==")
run_case("变量直接进fromHex(真阳性)", {"src/a.cpp": BAD}, True)
run_case("有isHexOnly校验(真阴性)", {"src/a.cpp": GOOD}, False)
run_case("只对字面量调用(真阴性)", {"src/a.cpp": LITERAL_ONLY}, False)
run_case("函数式校验(真阴性)", {"src/a.cpp": GOOD_FUNCCHECK}, False)
# 说明：不能基于字符字面量（QChar('0') / c >= '0'）做识别，
# 因为 strip_comments_and_strings() 会把字符字面量清空。
# 该限制已写入 check_hex_parse_is_validated 的注释。

TOTAL += 1
tmp = tempfile.mkdtemp(prefix="hexparse_real_")
try:
    shutil.copytree(os.path.join(ROOT, "src"), os.path.join(tmp, "src"))
    m = load()
    m.FAIL.clear()
    m.check_hex_parse_is_validated(tmp, os.path.join(tmp, "src"))
    ok = len(m.FAIL) == 0
    print("  [{}] 真实仓库 src/ 全量  (fail={})".format(
        "PASS" if ok else "FAIL", len(m.FAIL)))
    if not ok:
        FAILED += 1
        for x in m.FAIL[:5]:
            print("        -> " + x[:170])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n结果: {} 个用例失败 (共 {})".format(FAILED, TOTAL))
sys.exit(1 if FAILED else 0)
