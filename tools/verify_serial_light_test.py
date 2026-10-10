# -*- coding: utf-8 -*-
"""desktop_test_serial_light 故障注入自检（纯 Python 驱动）。

朝**真实的危险退化**去改 serial_light.cpp / app_config.cpp，要求对应用例必须
失败。两个对照必须仍然通过（不误报）。

判定方式（第 30 轮实测）：QtTest 的退出码 == FAIL 行数。
真正的崩溃 = 非零退出码但**一条 FAIL 行都没有**。
"""
import io
import os
import re
import shutil
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

D = r'C:\Users\user\Desktop\linux_ai\Accessterminal_desktop'
MSYS = r'C:\Users\user\.dsh\toolchains\msys64'
CMAKE = os.path.join(MSYS, 'mingw64', 'bin', 'cmake.exe')
BUILD = os.path.join(os.environ['TEMP'], 'fi33win')
EXE = os.path.join(BUILD, 'desktop_test_serial_light.exe')

_SRCDIR = os.path.join(
    BUILD, 'CMakeFiles', 'desktop_test_serial_light.dir', 'C_', 'Users',
    'user', 'Desktop', 'linux_ai', 'Accessterminal_desktop', 'src')

SL = os.path.join(D, 'src', 'hal', 'serial_light.cpp')
CFG = os.path.join(D, 'src', 'config', 'app_config.cpp')

SL_OBJ = os.path.join(_SRCDIR, 'hal', 'serial_light.cpp.obj')
CFG_OBJ = os.path.join(_SRCDIR, 'config', 'app_config.cpp.obj')

ENV = dict(os.environ)
ENV['PATH'] = (os.path.join(MSYS, 'mingw64', 'bin') + os.pathsep
               + os.path.join(MSYS, 'usr', 'bin') + os.pathsep + ENV['PATH'])

FILES = (SL, CFG)

# ⚠ 匹配 FAIL 行时**不要**写成 `\w+::(\w+)\(\)`。
# 数据驱动用例的名字是 `Class::case(desk)`，不是 `Class::case()`；
# 下面 `defaultCommandsMatchTheFrozenBytes` 就是数据驱动的，改坏 desk 指令
# 字节后 QtTest 输出 `FAIL!  : ...::defaultCommandsMatchTheFrozenBytes(desk) ...`，
# 那个正则匹配不到 -> failed 为空 -> 退出码非零被误判成**崩溃**。
# 夹具第一版正是如此，把一条正常的断言失败报成了"崩溃(rc=1, 0 条 FAIL 行)"。
# 正确地判崩溃必须只看行首标记，不依赖用例名的形状。
FAIL_RE = re.compile(r'^FAIL!\s*:', re.M)


def count_fails(out):
    return len(FAIL_RE.findall(out))


def read(p):
    return io.open(p, encoding='utf-8').read()


_ORIG = {p: read(p) for p in FILES}

_TEXT = _ORIG[SL]
_CFG = _ORIG[CFG]


def need(text, s, n=1):
    c = text.count(s)
    if c != n:
        raise AssertionError('锚点出现 %d 次（期望 %d）: %r' % (c, n, s[:70]))
    return s


# ---- 从真实文件里取出的锚点 ----
OPEN_HEAD = need(_TEXT,
                 'bool SerialLight::open(const QString& portName, int baudRate)\n'
                 '{\n'
                 '    if (!m_port) {\n'
                 '        m_port = new QSerialPort(this);\n'
                 '    }\n'
                 '    if (m_port->isOpen()) {\n'
                 '        m_port->close();\n'
                 '    }\n')

SET_PARAMS = need(_TEXT,
                  '    m_port->setPortName(portName);\n'
                  '    m_port->setBaudRate(baudRate);\n'
                  '    m_port->setDataBits(QSerialPort::Data8);\n'
                  '    m_port->setParity(QSerialPort::NoParity);\n'
                  '    m_port->setStopBits(QSerialPort::OneStop);\n'
                  '    m_port->setFlowControl(QSerialPort::NoFlowControl);\n')

OPEN_FAIL = need(_TEXT,
                 '    if (!m_port->open(QIODevice::ReadWrite)) {\n'
                 '        const QString msg = QStringLiteral("串口打开失败: %1 (%2)")\n'
                 '                                .arg(portName, m_port->errorString());\n'
                 '        qWarning() << "[灯控]" << msg;\n'
                 '        emit errorOccurred(msg);\n'
                 '        return false;\n'
                 '    }\n')

CLOSE_BODY = need(_TEXT,
                  'void SerialLight::close()\n'
                  '{\n'
                  '    if (m_port && m_port->isOpen()) {\n'
                  '        m_port->close();\n'
                  '    }\n'
                  '}\n')

DTOR = need(_TEXT,
            'SerialLight::~SerialLight()\n'
            '{\n'
            '    close();\n'
            '}\n')

SEND_HEAD = need(_TEXT,
                 'bool SerialLight::sendCommand(const QString& name)\n'
                 '{\n'
                 '    const QByteArray command = AppConfig::instance().lightCommand(name);\n'
                 '    if (command.isEmpty()) {\n'
                 '        qWarning() << "[灯控] 未知的指令名称:" << name;\n'
                 '        return false;\n'
                 '    }\n')

# 两个前置检查**合在一起**的完整文本。做"换序"变异必须整段替换：
# 只替换前半段会在函数体里留下一个没有闭合的 `{`，那是**编译错误**而不是
# 行为变化（夹具第一版就是这样，报 "expected declaration before '}' token"）。
SEND_CHECKS = need(_TEXT,
                   '    const QByteArray command = AppConfig::instance().lightCommand(name);\n'
                   '    if (command.isEmpty()) {\n'
                   '        qWarning() << "[灯控] 未知的指令名称:" << name;\n'
                   '        return false;\n'
                   '    }\n'
                   '    if (!isOpen()) {\n'
                   '        // 与重构前一致：不打弹窗，仅记录日志，避免现场无串口时阻塞操作。\n'
                   '        qWarning() << "[灯控] 串口未打开，无法发送指令:" << name;\n'
                   '        return false;\n'
                   '    }\n')

WRITE_TAIL = need(_TEXT,
                  '    const qint64 written = m_port->write(command);\n'
                  '    m_port->flush();\n'
                  '    if (written != command.size()) {\n'
                  '        const QString msg = QStringLiteral("灯控指令写入不完整: %1").arg(name);\n'
                  '        qWarning() << "[灯控]" << msg;\n'
                  '        emit errorOccurred(msg);\n'
                  '        return false;\n'
                  '    }\n')

# app_config.cpp 里的一条默认灯控指令（逐字节）
DESK_HEX = need(_CFG,
                '    m_lightCommands.insert(QStringLiteral("desk"),       QByteArray::fromHex("FD034C12045DDF"));\n')


MUT = [
    # ---- open() 的参数 ----
    ("数据位设成 7（Data7）",
     SL, 'm_port->setDataBits(QSerialPort::Data8);',
     'm_port->setDataBits(QSerialPort::Data7);'),

    ("校验位设成偶校验",
     SL, 'm_port->setParity(QSerialPort::NoParity);',
     'm_port->setParity(QSerialPort::EvenParity);'),

    ("停止位设成 2 位",
     SL, 'm_port->setStopBits(QSerialPort::OneStop);',
     'm_port->setStopBits(QSerialPort::TwoStop);'),

    ("流控设成硬件流控",
     SL, 'm_port->setFlowControl(QSerialPort::NoFlowControl);',
     'm_port->setFlowControl(QSerialPort::HardwareControl);'),

    ("打开模式改成只读",
     SL, 'if (!m_port->open(QIODevice::ReadWrite)) {',
     'if (!m_port->open(QIODevice::ReadOnly)) {'),

    ("波特率不传下去（写死 9600）",
     SL, 'm_port->setBaudRate(baudRate);',
     'm_port->setBaudRate(9600);'),

    ("端口名不传下去（写死 ttyUSB0）",
     SL, 'm_port->setPortName(portName);',
     'm_port->setPortName(QStringLiteral("/dev/ttyUSB0"));'),

    # ---- open() 的失败处理 ----
    # 注意：不能用 "qWarning() << \"[灯控]\" << msg;\n emit errorOccurred(msg);"
    # 这种短锚点 —— 打开失败与短写失败**共用**这两句，短锚点会命中两处
    # （夹具第一次跑就报 "锚点出现 2 次"）。下面一律用**完整的 if 块**。
    ("打开失败不发 errorOccurred",
     SL, OPEN_FAIL,
     '    if (!m_port->open(QIODevice::ReadWrite)) {\n'
     '        const QString msg = QStringLiteral("串口打开失败: %1 (%2)")\n'
     '                                .arg(portName, m_port->errorString());\n'
     '        qWarning() << "[灯控]" << msg;\n'
     '        return false;\n'
     '    }\n'),

    ("打开失败也返回 true（假成功）",
     SL, OPEN_FAIL,
     '    if (!m_port->open(QIODevice::ReadWrite)) {\n'
     '        const QString msg = QStringLiteral("串口打开失败: %1 (%2)")\n'
     '                                .arg(portName, m_port->errorString());\n'
     '        qWarning() << "[灯控]" << msg;\n'
     '        emit errorOccurred(msg);\n'
     '        return true;\n'
     '    }\n'),

    ("打开失败不写日志",
     SL, OPEN_FAIL,
     '    if (!m_port->open(QIODevice::ReadWrite)) {\n'
     '        const QString msg = QStringLiteral("串口打开失败: %1 (%2)")\n'
     '                                .arg(portName, m_port->errorString());\n'
     '        emit errorOccurred(msg);\n'
     '        return false;\n'
     '    }\n'),

    ("失败文案丢了端口名",
     SL,
     'QStringLiteral("串口打开失败: %1 (%2)")\n'
     '                                .arg(portName, m_port->errorString())',
     'QStringLiteral("串口打开失败: (%1)")\n'
     '                                .arg(m_port->errorString())'),

    ("失败文案丢了失败原因",
     SL,
     'QStringLiteral("串口打开失败: %1 (%2)")\n'
     '                                .arg(portName, m_port->errorString())',
     'QStringLiteral("串口打开失败: %1")\n'
     '                                .arg(portName)'),

    # ---- 已打开时先关再开 ----
    ("已打开时不先关（漏关句柄）",
     SL,
     '    if (m_port->isOpen()) {\n'
     '        m_port->close();\n'
     '    }\n',
     ''),

    # ---- close() / 析构 ----
    ("close() 变成空实现",
     SL, CLOSE_BODY,
     'void SerialLight::close()\n{\n}\n'),

    ("close() 不做 isOpen 判断（重复关）",
     SL,
     '    if (m_port && m_port->isOpen()) {\n'
     '        m_port->close();\n'
     '    }\n',
     '    if (m_port) {\n'
     '        m_port->close();\n'
     '    }\n'),

    ("析构不关串口",
     SL, DTOR,
     'SerialLight::~SerialLight()\n{\n}\n'),

    # ---- sendCommand() ----
    ("未知指令名也照样往下写",
     SL,
     '    if (command.isEmpty()) {\n'
     '        qWarning() << "[灯控] 未知的指令名称:" << name;\n'
     '        return false;\n'
     '    }\n',
     ''),

    ("两个前置检查换序（先查串口再查指令名）",
     SL, SEND_CHECKS,
     '    if (!isOpen()) {\n'
     '        // 与重构前一致：不打弹窗，仅记录日志，避免现场无串口时阻塞操作。\n'
     '        qWarning() << "[灯控] 串口未打开，无法发送指令:" << name;\n'
     '        return false;\n'
     '    }\n'
     '    const QByteArray command = AppConfig::instance().lightCommand(name);\n'
     '    if (command.isEmpty()) {\n'
     '        qWarning() << "[灯控] 未知的指令名称:" << name;\n'
     '        return false;\n'
     '    }\n'),

    ("串口未打开也照样写",
     SL,
     '    if (!isOpen()) {\n'
     '        // 与重构前一致：不打弹窗，仅记录日志，避免现场无串口时阻塞操作。\n'
     '        qWarning() << "[灯控] 串口未打开，无法发送指令:" << name;\n'
     '        return false;\n'
     '    }\n',
     ''),

    ("未打开时的日志串改掉（分支不可分辨）",
     SL, 'qWarning() << "[灯控] 串口未打开，无法发送指令:" << name;',
     'qWarning() << "[灯控] 无法发送指令:" << name;'),

    ("未知指令名的日志串改掉（分支不可分辨）",
     SL, 'qWarning() << "[灯控] 未知的指令名称:" << name;',
     'qWarning() << "[灯控] 指令名有误:" << name;'),

    ("不调 flush()",
     SL, '    m_port->flush();\n', ''),

    ("写入长度不校验（短写静默成功）",
     SL, WRITE_TAIL,
     '    const qint64 written = m_port->write(command);\n'
     '    m_port->flush();\n'),

    ("短写不发 errorOccurred",
     SL, WRITE_TAIL,
     '    const qint64 written = m_port->write(command);\n'
     '    m_port->flush();\n'
     '    if (written != command.size()) {\n'
     '        const QString msg = QStringLiteral("灯控指令写入不完整: %1").arg(name);\n'
     '        qWarning() << "[灯控]" << msg;\n'
     '        return false;\n'
     '    }\n'),

    ("短写文案丢了指令名",
     SL,
     'QStringLiteral("灯控指令写入不完整: %1").arg(name)',
     'QStringLiteral("灯控指令写入不完整")'),

    # ---- 灯控指令字节（app_config.cpp）----
    ("desk 指令字节改了一个字节",
     CFG,
     'QByteArray::fromHex("FD034C12045DDF")',
     'QByteArray::fromHex("FD034C12045DDE")'),

    # ---- 对照（必须不误报）----
    ("对照：加无关注释",
     SL, '} // namespace accessterminal',
     '// 无关注释（对照）\n} // namespace accessterminal', False),

    ("对照：改 qInfo 文案",
     SL, 'qInfo() << "[灯控] 串口打开成功:" << portName << "波特率:" << baudRate;',
     'qInfo() << "[light] opened:" << portName << baudRate;', False),
]


def configure():
    return subprocess.run(
        [CMAKE, '-S', os.path.join(D, 'tests'), '-B', BUILD, '-G', 'Ninja'],
        capture_output=True, env=ENV, cwd=D)


def build():
    return subprocess.run(
        [CMAKE, '--build', BUILD, '--target', 'desktop_test_serial_light'],
        capture_output=True, env=ENV, cwd=D)


def run_exe():
    return subprocess.run([EXE], capture_output=True, env=ENV, cwd=D)


def mt(p):
    return os.path.getmtime(p) if os.path.exists(p) else 0


def main():
    for item in MUT:
        name, path, old = item[0], item[1], item[2]
        n = _ORIG[path].count(old)
        if n != 1:
            print('[夹具错误] %s 锚点出现 %d 次（必须恰好 1 次）' % (name, n))
            return 2

    shutil.rmtree(BUILD, ignore_errors=True)
    r = configure()
    print('configure rc=%d' % r.returncode)
    if r.returncode != 0:
        print(r.stderr.decode('utf-8', 'replace')[-2000:])
        return 2
    rb = build()
    if rb.returncode != 0:
        print('基线构建失败:')
        print((rb.stdout + rb.stderr).decode('utf-8', 'replace')[-2500:])
        return 2
    rr = run_exe()
    out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
    base_fail = FAIL_RE.findall(out)
    tot = re.search(r'Totals:\s*(\d+) passed,\s*(\d+) failed', out)
    print('基线: %s' % (tot.group(0) if tot else '(无 Totals)'))
    if base_fail:
        print('*** 基线就有 %d 条 FAIL，无法继续' % len(base_fail))
        print(out[-3000:])
        return 2
    print()

    problems = []
    try:
        for item in MUT:
            name, path, old, new = item[0], item[1], item[2], item[3]
            expect_fail = item[4] if len(item) > 4 else True

            io.open(path, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG[path].replace(old, new, 1))
            if read(path) == _ORIG[path]:
                print('  [夹具错误] %-44s 文件未变' % name)
                problems.append(name)
                io.open(path, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG[path])
                continue

            obj = SL_OBJ if path == SL else CFG_OBJ
            t0 = mt(obj)
            rb = build()
            if rb.returncode != 0:
                print('  [构建失败] %-44s %s' % (
                    name, (rb.stdout + rb.stderr).decode(
                        'utf-8', 'replace')[-200:]))
                problems.append(name)
                io.open(path, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG[path])
                continue
            t1 = mt(obj)

            rr = run_exe()
            out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
            failed = FAIL_RE.findall(out)
            crashed = rr.returncode != 0 and not failed
            totals = re.search(r'Totals:\s*(\d+) passed,\s*(\d+) failed', out)
            consistent = (totals is not None
                          and rr.returncode == int(totals.group(2)))

            if t1 <= t0:
                print('  [夹具错误] %-44s .obj 未重编（可能是旧二进制）' % name)
                problems.append(name)
            elif expect_fail:
                if failed or crashed:
                    if crashed:
                        tag = '崩溃(rc=%d, 0 条 FAIL 行)' % rr.returncode
                    elif consistent:
                        tag = '%d 条 FAIL 行(rc=%d)' % (len(failed),
                                                        rr.returncode)
                    else:
                        tag = '%d 条 FAIL(rc=%d 与计数不符)' % (
                            len(failed), rr.returncode)
                    print('  %-44s 被抓到 ✓ %s' % (name, tag))
                else:
                    print('  %-44s *** 未被抓到（假绿）rc=%d'
                          % (name, rr.returncode))
                    problems.append(name)
            else:
                if not failed and not crashed:
                    print('  %-44s 通过 ✓（不误报）' % name)
                else:
                    print('  %-44s *** 误报：%s' % (name, failed[:3]))
                    problems.append(name)

            io.open(path, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG[path])
    finally:
        for p in FILES:
            io.open(p, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG[p])

    same = all(read(p) == _ORIG[p] for p in FILES)
    print()
    print('还原逐字节一致:', same)
    build()
    rr = run_exe()
    for l in (rr.stdout + rr.stderr).decode('utf-8', 'replace').split('\n'):
        if 'Totals' in l:
            print('还原后全量:', l.strip())
    print()
    print('变异 %d 个，致命问题 %d 个' % (len(MUT), len(problems)))
    if problems:
        print('问题清单:', problems)
    return 1 if (problems or not same) else 0


if __name__ == '__main__':
    sys.exit(main())
