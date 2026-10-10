# -*- coding: utf-8 -*-
"""对第 33 轮新增的 check_serial_light_contract_is_pinned 做故障注入自检。"""
import io
import os
import re
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

D = r'C:\Users\user\Desktop\linux_ai\Accessterminal_desktop'
T = r'C:\Users\user\Desktop\linux_ai\Accessterminal_T113'
PY = r'C:\Users\user\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
VERIFY = os.path.join(D, 'tools', 'verify.py')
SL = os.path.join(D, 'src', 'hal', 'serial_light.cpp')
SHIM = os.path.join(D, 'tests', 'fake_serial_port', 'QSerialPort')
CM = os.path.join(D, 'tests', 'CMakeLists.txt')


def read(p):
    return io.open(p, encoding='utf-8', errors='replace').read()


FILES = (SL, SHIM, CM)
_ORIG = {p: read(p) for p in FILES}


def sub(p, old, new, count=1):
    s = _ORIG[p]
    n = s.count(old)
    if n != count:
        raise AssertionError('%s 锚点出现 %d 次（期望 %d）: %r'
                             % (os.path.basename(p), n, count, old[:60]))
    return s.replace(old, new, count)


MUT = [
    # 8N1 / 流控 / 读写模式
    ("数据位改成 Data7", SL, 'setDataBits(QSerialPort::Data8)',
     'setDataBits(QSerialPort::Data7)'),
    ("校验位改成偶校验", SL, 'setParity(QSerialPort::NoParity)',
     'setParity(QSerialPort::EvenParity)'),
    ("停止位改成 2 位", SL, 'setStopBits(QSerialPort::OneStop)',
     'setStopBits(QSerialPort::TwoStop)'),
    ("流控改成硬件流控", SL, 'setFlowControl(QSerialPort::NoFlowControl)',
     'setFlowControl(QSerialPort::HardwareControl)'),
    ("打开模式改成只读", SL, 'open(QIODevice::ReadWrite)',
     'open(QIODevice::ReadOnly)'),

    # 日志前缀：`[灯控]` 在文件里出现 6 次，必须整行整句替换才是唯一锚点。
    ("日志前缀 [灯控] 改成 [light]（全部）", SL, '[灯控]', '[light]', 6),

    # 两个前置检查换序（只改顺序，保持可编译）
    ("未知指令名分支挪到串口检查之后", SL,
     '    if (command.isEmpty()) {\n'
     '        qWarning() << "[灯控] 未知的指令名称:" << name;\n'
     '        return false;\n'
     '    }\n'
     '    if (!isOpen()) {\n'
     '        // 与重构前一致：不打弹窗，仅记录日志，避免现场无串口时阻塞操作。\n'
     '        qWarning() << "[灯控] 串口未打开，无法发送指令:" << name;\n'
     '        return false;\n'
     '    }\n',
     '    if (!isOpen()) {\n'
     '        // 与重构前一致：不打弹窗，仅记录日志，避免现场无串口时阻塞操作。\n'
     '        qWarning() << "[灯控] 串口未打开，无法发送指令:" << name;\n'
     '        return false;\n'
     '    }\n'
     '    if (command.isEmpty()) {\n'
     '        qWarning() << "[灯控] 未知的指令名称:" << name;\n'
     '        return false;\n'
     '    }\n'),

    # 影子头安全阀。
    # 注意：`ACC_SERIAL_LIGHT_TEST` 在影子头里出现 3 次（文档注释 2 次 +
    # 真指令 1 次），所以必须用**完整指令块**当锚点，不能只换那个宏名。
    ("影子头去掉 #error 安全阀", SHIM,
     '#ifndef ACC_SERIAL_LIGHT_TEST\n'
     '#  error "这个影子 QSerialPort 只能用于测试；请在测试目标上定义 ACC_SERIAL_LIGHT_TEST"\n'
     '#endif\n', ''),

    ("影子头安全阀改成恒真（#ifndef -> #if 0）", SHIM,
     '#ifndef ACC_SERIAL_LIGHT_TEST\n', '#if 0\n'),

    # CMake 侧。同理要剥掉注释才能真正验证 —— 见 verify.py 里那段说明。
    ("CMake 不再定义 ACC_SERIAL_LIGHT_TEST", CM,
     'target_compile_definitions(desktop_test_serial_light PRIVATE\n'
     '    ACC_SERIAL_LIGHT_TEST\n'
     ')\n', ''),

    ("CMake 不再引用 fake_serial_port 目录", CM,
     '    ${CMAKE_CURRENT_LIST_DIR}/fake_serial_port\n', ''),

    ("CMake 去掉 BEFORE（影子头排在 Qt 之后）", CM,
     'target_include_directories(desktop_test_serial_light BEFORE PRIVATE',
     'target_include_directories(desktop_test_serial_light PRIVATE'),
]

CTRL = [
    ("加无关注释（文件末尾）", SL,
     '} // namespace accessterminal',
     '// 无关注释\n} // namespace accessterminal'),
    ("改 qInfo 文案", SL,
     'qInfo() << "[灯控] 串口打开成功:" << portName << "波特率:" << baudRate;',
     'qInfo() << "[灯控] opened:" << portName << baudRate;'),
]


def run_verify():
    return subprocess.run([PY, VERIFY, D, T], capture_output=True, cwd=D)


def main():
    problems = []
    try:
        r = run_verify()
        print('基线 rc = %d' % r.returncode)
        if r.returncode != 0:
            print('*** 基线就不过')
            print((r.stdout + r.stderr).decode('utf-8', 'replace')[-2500:])
            return 2
        print()

        for item in MUT:
            name, p, old, new = item[0], item[1], item[2], item[3]
            cnt = item[4] if len(item) > 4 else 1
            try:
                text = sub(p, old, new, cnt)
            except AssertionError as e:
                print('  [夹具错误] %-44s %s' % (name, e))
                problems.append(name)
                continue
            io.open(p, 'w', encoding='utf-8', newline='\n').write(text)
            if read(p) == _ORIG[p]:
                print('  [夹具错误] %-44s 文件未变' % name)
                problems.append(name)
                io.open(p, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG[p])
                continue

            r = run_verify()
            out = (r.stdout + r.stderr).decode('utf-8', 'replace')
            hits = re.findall(r'^\s*X (\[serial\][^\n]*)', out, re.M)
            if r.returncode != 0 and hits:
                print('  %-44s 被抓到 ✓ %s' % (name, hits[0][:50]))
            else:
                print('  %-44s *** 未被抓到（假绿）rc=%d'
                      % (name, r.returncode))
                problems.append(name)

            io.open(p, 'w', encoding='utf-8', newline='\n').write(_ORIG[p])

        print()
        for name, p, old, new in CTRL:
            try:
                text = sub(p, old, new)
            except AssertionError as e:
                print('  [夹具错误] %-44s %s' % (name, e))
                problems.append(name)
                continue
            io.open(p, 'w', encoding='utf-8', newline='\n').write(text)
            r = run_verify()
            out = (r.stdout + r.stderr).decode('utf-8', 'replace')
            if r.returncode == 0:
                print('  %-44s 通过 ✓（不误报）' % name)
            else:
                print('  %-44s *** 误报 rc=%d' % (name, r.returncode))
                print(out[-600:])
                problems.append(name)
            io.open(p, 'w', encoding='utf-8', newline='\n').write(_ORIG[p])
    finally:
        for p in FILES:
            io.open(p, 'w', encoding='utf-8', newline='\n').write(_ORIG[p])

    same = all(read(p) == _ORIG[p] for p in FILES)
    print()
    print('还原逐字节一致:', same)
    r = run_verify()
    for l in (r.stdout + r.stderr).decode('utf-8', 'replace').split('\n'):
        if '结论' in l:
            print('还原后:', l.strip())
    print()
    print('变异 %d 个，对照 %d 个，致命问题 %d 个'
          % (len(MUT), len(CTRL), len(problems)))
    if problems:
        print('问题清单:', problems)
    return 1 if (problems or not same) else 0


if __name__ == '__main__':
    sys.exit(main())
