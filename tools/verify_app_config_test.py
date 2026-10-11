# -*- coding: utf-8 -*-
"""AppConfig 测试的故障注入自检（跨平台）。

用法：python3 tools/verify_app_config_test.py [<仓库根>]
返回码 0 表示：每个危险退化都被抓到，对照未误报，且源码被逐字节还原。

要证明的核心命题
----------------
`tests/test_app_config.cpp`（15 个用例）守的是**配置解析**：JSON 是不可信输入，
解析错一步的后果要么是"灯按不动"（指令字节错位），要么是"门口机永远连不上"
（端口被夹成随机），要么是**每次启动都打一条假错误**（把现场排障引向不存在的
配置问题）。这几种都不会崩溃、只会静默出错，所以必须靠断言钉住。

变异（全部是真实危险的退化）
  1. lights 段不跳过 '_' 开头的注释键（启动即打假告警）
  2. parseHexBytes 去掉 isHexOnly 显式校验（fromHex 会静默重排，指令错位）
  3. parseHexBytes 不检查奇数长度
  4. lights 解析成功却不写入指令表（测试用非默认键 lamp2 才能暴露）
  5. load() 不复位 m_loadedFromFile（reload 后状态撒谎）

对照（必须通过）
  C1. 只加无关注释
  C2. 改 qWarning 文案（不影响语义）

**故意不测的变异（如实记录限制）**
  - 去掉 `compact.isEmpty()` 这一半判断：空串走 `isHexOnly("")` 为真、
    `fromHex("")` 返回空，最终仍是空结果，与保留该判断**无可观测差异**
    （纵深防御）。由 UNDETECTABLE 反向守住。
  - 去掉 `if (!it.value().isString())` 判断：非字符串值的 `toString()` 得到空串，
    解析失败同样不插入，指令表内容不变（只会多一条告警，而现有断言不看它）。
"""
import atexit
import io
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

if len(sys.argv) > 1:
    print("提示: 本脚本不需要参数，已忽略: %s" % " ".join(sys.argv[1:]))

_HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.dirname(_HERE)
SRC = os.path.join(D, 'src', 'config', 'app_config.cpp')

CMAKE = shutil.which('cmake')
BUILD = os.path.join(tempfile.gettempdir(), 'fi_app_config')
_EXE_SUFFIX = '.exe' if os.name == 'nt' else ''
EXE = os.path.join(BUILD, 'desktop_test_app_config' + _EXE_SUFFIX)

ENV = dict(os.environ)
ENV['QT_QPA_PLATFORM'] = 'offscreen'

SKIP_COMMENT = ("            if (it.key().startsWith(QLatin1Char('_'))) {\n"
                "                continue;\n"
                "            }\n")
IS_HEX_ONLY = ("    if (!isHexOnly(compact)) {\n"
               "        return QByteArray();\n"
               "    }\n")
ODD_LEN = ("    if (compact.isEmpty() || compact.size() % 2 != 0) {\n"
           "        return QByteArray();\n"
           "    }\n")
INSERT_CMD = "                m_lightCommands.insert(it.key(), bytes);\n"
LOAD_RESET = "    m_loadedFromFile = false;\n    m_configPath.clear();\n"
IS_STRING = ("            if (!it.value().isString()) {\n"
             "                continue;\n"
             "            }\n")

MUT = [
    ("lights 不跳过 '_' 开头的注释键（启动即打假告警）",
     SKIP_COMMENT, ''),

    ("parseHexBytes 去掉 isHexOnly 显式校验（指令会静默错位）",
     IS_HEX_ONLY, ''),

    ("parseHexBytes 不检查奇数长度",
     'if (compact.isEmpty() || compact.size() % 2 != 0) {',
     'if (compact.isEmpty() || false) {'),

    # 注意：这条只对**没有内置默认值**的键可观测。测试里因此用了 lamp2；
    # 若哪天有人把测试改成只用 desk/work 这类键，本变异会立刻变成"抓不到"，
    # 正好像现在这样把问题暴露出来。
    ("lights 解析成功却不写入指令表（仅非默认键可暴露）",
     INSERT_CMD,
     '                (void)bytes;\n'),

    ("load() 不复位 m_loadedFromFile",
     LOAD_RESET, ''),
]

CONTROL = [
    ("C1 只加无关注释",
     'QByteArray parseHexBytes(const QString& text)',
     'QByteArray parseHexBytes(const QString& text) // C1 无关注释'),

    ("C2 改另一条 qWarning 文案（不影响语义）",
     'qWarning() << "[配置] 解析失败" << candidate << error.errorString();',
     'qWarning() << "[配置] parse failed" << candidate << error.errorString();'),
]

UNDETECTABLE = [
    ("parseHexBytes 不再单独判断空串（纵深防御）",
     ODD_LEN,
     "    if (compact.size() % 2 != 0) {\n        return QByteArray();\n    }\n"),

    ("lights 不再要求值必须是字符串",
     IS_STRING, ''),
]


def read_src():
    return io.open(SRC, encoding='utf-8', errors='replace').read()


_ORIG = read_src()


def restore_src():
    try:
        current = read_src()
    except Exception:
        return
    if current != _ORIG:
        try:
            io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)
            print('\n[崩溃安全] 已把 %s 还原为运行前的原始内容'
                  % os.path.relpath(SRC, D))
        except Exception as exc:
            print('\n[崩溃安全][严重] 源码还原失败: %r' % (exc,))


atexit.register(restore_src)


def _restore_on_signal(signum, _frame):
    restore_src()
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


for _sig in (getattr(signal, 'SIGINT', None), getattr(signal, 'SIGTERM', None)):
    if _sig is not None:
        try:
            signal.signal(_sig, _restore_on_signal)
        except (ValueError, OSError):
            pass


def build(target=None):
    args = [CMAKE, '--build', BUILD]
    if target:
        args += ['--target', target]
    return subprocess.run(args, capture_output=True, env=ENV, cwd=D)


def run_exe():
    return subprocess.run([EXE], capture_output=True, env=ENV, cwd=D)


def totals(out):
    m = re.search(r'Totals:\s*(\d+) passed,\s*(\d+) failed', out)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def main():
    if not CMAKE:
        print('找不到 cmake，无法运行自检')
        return 2

    for item in MUT + CONTROL + UNDETECTABLE:
        name, old = item[0], item[1]
        n = _ORIG.count(old)
        if n != 1:
            print('[夹具错误] %s 锚点出现 %d 次（必须恰好 1 次）' % (name, n))
            return 2

    shutil.rmtree(BUILD, ignore_errors=True)
    cfg = subprocess.run([CMAKE, '-S', os.path.join(D, 'tests'), '-B', BUILD,
                          '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release'],
                         capture_output=True, env=ENV, cwd=D)
    print('configure rc=%d' % cfg.returncode)
    if cfg.returncode != 0:
        print(cfg.stderr.decode('utf-8', 'replace')[-1500:])
        return 2

    rb = build('desktop_test_app_config')
    if rb.returncode != 0:
        print('基线构建失败:')
        print((rb.stdout + rb.stderr).decode('utf-8', 'replace')[-1500:])
        return 2

    rr = run_exe()
    base_out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
    base = totals(base_out)
    if base is None or base[1] != 0:
        print('基线就不干净（Totals=%r）：' % (base,))
        print(base_out[-1500:])
        return 2
    print('基线: %d passed, %d failed' % base)
    print()

    problems = []
    caught = 0
    try:
        print('--- 变异（每个都必须被抓到）---')
        for item in MUT:
            name, old, new = item[0], item[1], item[2]
            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG.replace(old, new, 1))
            if read_src() == _ORIG:
                print('  [夹具错误] %-50s 文件未变' % name)
                problems.append(name)
                io.open(SRC, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG)
                continue
            rb = build('desktop_test_app_config')
            if rb.returncode != 0:
                print('  [构建失败] %-50s %s'
                      % (name, (rb.stdout + rb.stderr).decode(
                          'utf-8', 'replace')[-200:]))
                problems.append(name)
                io.open(SRC, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG)
                continue
            rr = run_exe()
            out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
            t = totals(out)
            fails = re.findall(r'^FAIL!\s*:\s*(\S+)', out, re.M)
            if t is None:
                print('  [夹具错误] %-50s 没有 Totals 行（崩溃？rc=%d）'
                      % (name, rr.returncode))
                problems.append(name)
            elif t[1] > 0:
                caught += 1
                print('  %-50s 抓到 ✓ (%d 条: %s)'
                      % (name, t[1], ', '.join(sorted(set(fails))[:3])))
            else:
                print('  *** %-50s 没抓到（全绿）' % name)
                problems.append(name)
            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG)

        print()
        print('--- 对照（必须全绿，不能误报）---')
        for item in CONTROL:
            name, old, new = item[0], item[1], item[2]
            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG.replace(old, new, 1))
            rb = build('desktop_test_app_config')
            if rb.returncode != 0:
                print('  *** %-50s 构建失败（对照本身有问题）' % name)
                problems.append(name)
                io.open(SRC, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG)
                continue
            rr = run_exe()
            out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
            t = totals(out)
            if t is None or t[1] != 0:
                print('  *** %-50s 误报（Totals=%r）' % (name, t))
                problems.append(name)
            else:
                print('  %-50s 全绿 ✓' % name)
            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG)

        print()
        print('--- 已判定不可观测的退化（必须抓不到）---')
        for item in UNDETECTABLE:
            name, old, new = item[0], item[1], item[2]
            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG.replace(old, new, 1))
            rb = build('desktop_test_app_config')
            if rb.returncode != 0:
                print('  *** %-50s 构建失败（不可再自称不可观测）' % name)
                problems.append(name)
                io.open(SRC, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG)
                continue
            rr = run_exe()
            out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
            t = totals(out)
            if t is not None and t[1] > 0:
                print('  *** %-50s 竟然被抓到了 —— 应提升为真变异' % name)
                problems.append(name)
            else:
                print('  %-50s 确认抓不到 ✓（如实记录限制）' % name)
            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG)
    finally:
        io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)

    same = read_src() == _ORIG
    print()
    print('还原后重建并复核...')
    build('desktop_test_app_config')
    rr = run_exe()
    final = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
    t = totals(final)
    print('还原后全量: %s' % (('Totals: %d passed, %d failed' % t)
                             if t else '(无 Totals 行)'))
    print()
    print('变异 %d 个（抓到 %d），对照 %d 个，不可观测 %d 个，致命问题 %d 个'
          % (len(MUT), caught, len(CONTROL), len(UNDETECTABLE), len(problems)))
    if problems:
        print('问题清单:', problems)
    if not same:
        print('*** 源码未逐字节还原！')
    return 1 if (problems or not same) else 0


if __name__ == '__main__':
    sys.exit(main())
