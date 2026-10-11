# -*- coding: utf-8 -*-
"""desktop_test_call_session 故障注入自检（纯 Python 驱动）。

朝真实的危险退化改 call_session.cpp，要求对应用例必须失败。
两个对照必须仍然通过（不误报）。

判定方式（第 30 轮实测）：QtTest 退出码 == FAIL 行数；真正的崩溃 = 非零退出码
但一条 FAIL 行都没有。**只看行首标记**，不要去匹配用例名形状（第 33 轮教训：
数据驱动用例是 case(desk) 而不是 case()）。
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
BUILD = os.path.join(os.environ['TEMP'], 'fi34win')
EXE = os.path.join(BUILD, 'desktop_test_call_session.exe')
OBJ = os.path.join(
    BUILD, 'CMakeFiles', 'desktop_test_call_session.dir', 'C_', 'Users',
    'user', 'Desktop', 'linux_ai', 'Accessterminal_desktop', 'src',
    'core', 'media', 'call_session.cpp.obj')
SRC = os.path.join(D, 'src', 'core', 'media', 'call_session.cpp')

ENV = dict(os.environ)
ENV['PATH'] = (os.path.join(MSYS, 'mingw64', 'bin') + os.pathsep
               + os.path.join(MSYS, 'usr', 'bin') + os.pathsep + ENV['PATH'])

FAIL_RE = re.compile(r'^FAIL!\s*:', re.M)


def read():
    return io.open(SRC, encoding='utf-8').read()


_ORIG = read()


def need(s, n=1):
    c = _ORIG.count(s)
    if c != n:
        raise AssertionError('锚点出现 %d 次（期望 %d）: %r' % (c, n, s[:70]))
    return s


# ---- 从真实文件取锚点 ----
FORMAT = need(
    'QAudioFormat pcmFormat()\n'
    '{\n'
    '    QAudioFormat format;\n'
    '    format.setSampleRate(protocol::kAudioSampleRate);\n'
    '    format.setChannelCount(protocol::kAudioChannels);\n'
    '    format.setSampleSize(protocol::kAudioBytesPerSample * 8);\n'
    '    format.setCodec(QStringLiteral("audio/pcm"));\n'
    '    format.setByteOrder(QAudioFormat::LittleEndian);\n'
    '    format.setSampleType(QAudioFormat::SignedInt);\n'
    '    return format;\n'
    '}\n')

AUDIO_BIND = need(
    '    if (!m_audioSocket->bind(QHostAddress::AnyIPv4, protocol::kAudioPort,\n'
    '                             QUdpSocket::ShareAddress)) {\n')

VIDEO_BIND = need(
    '    if (!m_videoSocket->bind(QHostAddress::Any, protocol::kVideoPort,\n'
    '                             QUdpSocket::ShareAddress)) {\n')

OUT_START = need('    m_audioDevice = m_audioOutput->start();\n')
OUT_BUFSZ = need('    m_audioOutput->setBufferSize(bytesPerMs * 27);\n')
IN_BUFSZ = need('    m_audioInput->setBufferSize(protocol::kAudioFramesPerPacket);\n')

AUDIO_READ = need(
    '        const qint64 bytesRead = m_audioSocket->readDatagram(\n'
    '            datagram.data(), datagram.size(), &sender, &senderPort);\n'
    '        if (bytesRead < 0) {\n'
    '            continue; // 读取失败，丢弃该数据报（不要污染设备地址）\n'
    '        }\n'
    '        if (bytesRead < datagram.size()) {\n'
    '            datagram.resize(static_cast<int>(bytesRead));\n'
    '        }\n')

DEV_ADDR = need(
    '        // 只有收到过终端音频包，才知道回传目标地址。\n'
    '        m_deviceAddress = sender;\n'
    '        m_devicePort = senderPort;\n')

CAP = need(
    '        if (m_audioBuffer.size() > maxBufferBytes) {\n'
    '            m_audioBuffer.remove(0, m_audioBuffer.size() - maxBufferBytes);\n'
    '        }\n')

WRITE_LOOP = need(
    '    while (!m_audioBuffer.isEmpty() && m_audioOutput->bytesFree() > 0) {\n'
    '        const int chunk = qMin(m_audioBuffer.size(), m_audioOutput->bytesFree());\n'
    '        const int written = m_audioDevice->write(m_audioBuffer.constData(), chunk);\n'
    '        if (written > 0) {\n'
    '            m_audioBuffer.remove(0, written);\n'
    '        } else {\n'
    '            break;\n'
    '        }\n'
    '    }\n')

# 注意：函数体里用的是文件顶部的**局部别名** `kAudioPacketBytes`
# （第 25 行 `constexpr int kAudioPacketBytes = protocol::kAudioBytesPerPacket;`），
# 不是全名 `kAudioBytesPerPacket`。锚点必须从真实字节抄，手写全名会匹配不到。
UPLINK_GUARD = need(
    '        // 未学到目标地址前不发送，避免把语音发给未知主机。\n'
    '        if (!m_deviceAddress.isNull() && m_devicePort != 0) {\n'
    '            m_audioSocket->writeDatagram(m_inputBuffer.constData(), kAudioPacketBytes,\n'
    '                                         m_deviceAddress, m_devicePort);\n'
    '        }\n'
    '        m_inputBuffer.remove(0, kAudioPacketBytes);\n')

INPUT_LOOP = need(
    '    while (m_inputBuffer.size() >= kAudioPacketBytes) {\n')

VIDEO_READ = need(
    '        const qint64 bytesRead =\n'
    '            m_videoSocket->readDatagram(datagram.data(), datagram.size());\n'
    '        if (bytesRead < 0) {\n'
    '            continue; // 读取失败，丢弃该数据报\n'
    '        }\n'
    '        if (bytesRead < datagram.size()) {\n'
    '            datagram.resize(static_cast<int>(bytesRead));\n'
    '        }\n')

VIDEO_DECODE = need(
    '        QImage image;\n'
    '        if (image.loadFromData(datagram, "JPG") && !image.isNull()) {\n'
    '            emit videoFrameReady(image);\n'
    '        }\n')

INFO_FORMAT = need('format.setSampleSize(protocol::kAudioBytesPerSample * 8);\n')
INFO_CODEC = need('format.setCodec(QStringLiteral("audio/pcm"));\n')
INFO_ORDER = need('format.setByteOrder(QAudioFormat::LittleEndian);\n')
INFO_TYPE = need('format.setSampleType(QAudioFormat::SignedInt);\n')
INFO_RATE = need('format.setSampleRate(protocol::kAudioSampleRate);\n')
INFO_CH = need('format.setChannelCount(protocol::kAudioChannels);\n')

OUT_STOP = need(
    '    if (m_audioOutput) {\n'
    '        m_audioOutput->stop();\n'
    '        delete m_audioOutput;\n'
    '        m_audioOutput = nullptr;\n'
    '    }\n') if False else None

DTOR = need(
    'CallSession::~CallSession()\n'
    '{\n'
    '    stop();\n'
    '}\n')


MUT = [
    # ---- 声卡格式（协议硬约束）----
    ("采样率设成 8000", INFO_RATE,
     'format.setSampleRate(8000);\n'),
    ("声道数设成 2", INFO_CH,
     'format.setChannelCount(2);\n'),
    ("位深设成 8 位", INFO_FORMAT,
     'format.setSampleSize(protocol::kAudioBytesPerSample * 4);\n'),
    ("codec 改成 audio/raw", INFO_CODEC,
     'format.setCodec(QStringLiteral("audio/raw"));\n'),
    ("字节序改成大端", INFO_ORDER,
     'format.setByteOrder(QAudioFormat::BigEndian);\n'),
    ("采样类型改成无符号", INFO_TYPE,
     'format.setSampleType(QAudioFormat::UnSignedInt);\n'),

    # ---- 缓冲区大小 ----
    ("输出缓冲改成 27 毫秒之外的 10 毫秒", OUT_BUFSZ,
     '    m_audioOutput->setBufferSize(bytesPerMs * 10);\n'),

    ("输入缓冲改成一包的 2 倍", IN_BUFSZ,
     '    m_audioInput->setBufferSize(protocol::kAudioFramesPerPacket * 2);\n'),

    # ---- 端口（协议硬约束）----
    ("音频口绑到 12346", AUDIO_BIND,
     '    if (!m_audioSocket->bind(QHostAddress::AnyIPv4, 12346,\n'
     '                             QUdpSocket::ShareAddress)) {\n'),

    ("视频口绑到 23457", VIDEO_BIND,
     '    if (!m_videoSocket->bind(QHostAddress::Any, 23457,\n'
     '                             QUdpSocket::ShareAddress)) {\n'),

    # ---- 音频接收 ----
    # "不判 readDatagram 返回值 / 不缩容" 两处实测抓不到，见 UNDETECTABLE。

    ("不记录回传地址（学不到目标）", DEV_ADDR, ''),

    ("缓冲区不设上限（延迟会累积）", CAP, ''),

    ("writeAudioData 不检查 bytesFree", WRITE_LOOP,
     '    while (!m_audioBuffer.isEmpty()) {\n'
     '        const int chunk = m_audioBuffer.size();\n'
     '        const int written = m_audioDevice->write(m_audioBuffer.constData(), chunk);\n'
     '        if (written > 0) {\n'
     '            m_audioBuffer.remove(0, written);\n'
     '        } else {\n'
     '            break;\n'
     '        }\n'
     '    }\n'),

    # ---- 音频回传 ----
    # "未学到地址也发上行语音" 实测抓不到，见 UNDETECTABLE。

    ("不足一包也发出去（>= 改成 >）", INPUT_LOOP,
     '    while (m_inputBuffer.size() > kAudioPacketBytes) {\n'),

    ("上行每包发多了（发整个缓冲）", UPLINK_GUARD,
     '        // 未学到目标地址前不发送，避免把语音发给未知主机。\n'
     '        if (!m_deviceAddress.isNull() && m_devicePort != 0) {\n'
     '            m_audioSocket->writeDatagram(m_inputBuffer.constData(), m_inputBuffer.size(),\n'
     '                                         m_deviceAddress, m_devicePort);\n'
     '        }\n'
     '        m_inputBuffer.remove(0, kAudioPacketBytes);\n'),

    # ---- 视频 ----
    # "视频不判 readDatagram 返回值" 实测抓不到，见 UNDETECTABLE。

    ("视频不判 loadFromData 结果（坏包也发帧）", VIDEO_DECODE,
     '        QImage image;\n'
     '        image.loadFromData(datagram, "JPG");\n'
     '        emit videoFrameReady(image);\n'),

    ("视频不发 videoFrameReady", VIDEO_DECODE,
     '        QImage image;\n'
     '        if (image.loadFromData(datagram, "JPG") && !image.isNull()) {\n'
     '        }\n'),

    # ---- 生命周期 ----
    ("析构不 stop()", DTOR,
     'CallSession::~CallSession()\n{\n}\n'),

    ("start() 后不清理旧状态（不复位回归地址）",
     'void CallSession::start()\n'
     '{\n'
     '    if (m_running) {\n'
     '        stop();\n'
     '    }\n'
     '    m_running = true;\n',
     'void CallSession::start()\n'
     '{\n'
     '    m_running = true;\n'),

    ("stop() 不置 m_running = false", '    m_running = false;\n}\n',
     '}\n'),

    # ---- 对照（必须不误报）----
    ("对照：加无关注释",
     '} // namespace accessterminal',
     '// 无关注释（对照）\n} // namespace accessterminal', False),

    ("对照：改 qInfo 文案",
     'qInfo() << "[通话] 音视频通道已启动";',
     'qInfo() << "[call] channels up";', False),
]


# ---------------------------------------------------------------------------
# 经实测判定为**本测试不可观测**的退化（如实记录，不假装覆盖）。
# 每个都附实测依据；一旦能抓到，夹具会报错提示提升为真变异。
# ---------------------------------------------------------------------------
UNDETECTABLE = [
    # 音频口去掉 ShareAddress。
    #
    # 为什么抓不到（探针 result20.txt A 组，3 组对照全部第二个绑失败）：
    # 在 Windows 上 ShareAddress **并不能**让两个 socket 同时绑同一端口 ——
    #   A1 两者都带 ShareAddress       : true / false
    #   A2 第一个独占、第二个共享       : true / false
    #   A3 第一个共享、第二个独占       : true / false
    # 也就是说"能不能重复绑"取决于**本机 socket 语义**，与共享标志无关。
    # 于是"本会话已绑着 12345 时再绑一次"在任何写法下都失败，测不出差别。
    # 这一条属于**跨平台行为差异**：Linux 上 SO_REUSEADDR 是允许重复绑的，
    # 若将来在 Linux 上跑测试并观察到差异，应把它提升为真变异。
    ("音频口不共享（去掉 ShareAddress）",
     '    if (!m_audioSocket->bind(QHostAddress::AnyIPv4, protocol::kAudioPort,\n'
     '                             QUdpSocket::ShareAddress)) {\n',
     '    if (!m_audioSocket->bind(QHostAddress::AnyIPv4, protocol::kAudioPort)) {\n'),

    # 音频侧不判 readDatagram 的返回值 / 不做缩容。
    #
    # 为什么抓不到（探针 result20.txt B 组）：对 0/1/4/100/640/678/1400/65507
    # 共 8 种长度实测，`readDatagram` 的返回值**恒等于** pendingDatagramSize()
    # （不等的次数 = 0）。UDP 上根本不会出现"短读"，所以那两句永远不生效。
    # 与第 31/32 轮在 monitor_client 上量到的结论一致。
    # 注意：这段代码**仍然值得保留** —— 它防的是 Qt 实现变化或平台差异，
    # 属于"防御性但当前不可观测"，不是死代码（UB 与平台差异都真实存在）。
    ("音频不判 readDatagram 返回值（bytesRead<0 也往下走）",
     '        const qint64 bytesRead = m_audioSocket->readDatagram(\n'
     '            datagram.data(), datagram.size(), &sender, &senderPort);\n'
     '        if (bytesRead < 0) {\n'
     '            continue; // 读取失败，丢弃该数据报（不要污染设备地址）\n'
     '        }\n',
     '        const qint64 bytesRead = m_audioSocket->readDatagram(\n'
     '            datagram.data(), datagram.size(), &sender, &senderPort);\n'),

    ("音频短读不缩容",
     '        if (bytesRead < datagram.size()) {\n'
     '            datagram.resize(static_cast<int>(bytesRead));\n'
     '        }\n'
     '\n'
     '        // 只有收到过终端音频包，才知道回传目标地址。\n',
     '\n'
     '        // 只有收到过终端音频包，才知道回传目标地址。\n'),

    # 视频侧同上（同一原因，result20.txt B 组）。
    ("视频不判 readDatagram 返回值（bytesRead<0 也往下走）",
     '        const qint64 bytesRead =\n'
     '            m_videoSocket->readDatagram(datagram.data(), datagram.size());\n'
     '        if (bytesRead < 0) {\n'
     '            continue; // 读取失败，丢弃该数据报\n'
     '        }\n',
     '        const qint64 bytesRead =\n'
     '            m_videoSocket->readDatagram(datagram.data(), datagram.size());\n'),

    # 上行语音的"未学到地址不发"守卫。
    #
    # 为什么抓不到（探针 result19.txt）：地址为空时 Qt **自己**就拒绝发送 ——
    #   writeDatagram(空地址, 有效端口) 返回 -1，对端什么也收不到
    #   writeDatagram(127.0.0.2, 0)     返回 640（端口 0 反而"成功"）
    # 所以那道 `if (!m_deviceAddress.isNull() && m_devicePort != 0)` 与 Qt 内部
    # 校验重叠，去掉它行为不变（端口 0 那半仍然由 Qt 兜着：发不到任何人）。
    # 保留它是**可读性 + 显式意图**，不是唯一防线。
    ("未学到地址也发上行语音",
     '        // 未学到目标地址前不发送，避免把语音发给未知主机。\n'
     '        if (!m_deviceAddress.isNull() && m_devicePort != 0) {\n'
     '            m_audioSocket->writeDatagram(m_inputBuffer.constData(), kAudioPacketBytes,\n'
     '                                         m_deviceAddress, m_devicePort);\n'
     '        }\n'
     '        m_inputBuffer.remove(0, kAudioPacketBytes);\n',
     '        m_audioSocket->writeDatagram(m_inputBuffer.constData(), kAudioPacketBytes,\n'
     '                                     m_deviceAddress, m_devicePort);\n'
     '        m_inputBuffer.remove(0, kAudioPacketBytes);\n'),
]


def configure():
    return subprocess.run(
        [CMAKE, '-S', os.path.join(D, 'tests'), '-B', BUILD, '-G', 'Ninja'],
        capture_output=True, env=ENV, cwd=D)


def build():
    return subprocess.run(
        [CMAKE, '--build', BUILD, '--target', 'desktop_test_call_session'],
        capture_output=True, env=ENV, cwd=D)


def run_exe():
    return subprocess.run([EXE], capture_output=True, env=ENV, cwd=D)


def mt(p):
    return os.path.getmtime(p) if os.path.exists(p) else 0


def main():
    for item in MUT + UNDETECTABLE:
        name, old = item[0], item[1]
        n = _ORIG.count(old)
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
    tot = re.search(r'Totals:\s*(\d+) passed,\s*(\d+) failed', out)
    print('基线: %s' % (tot.group(0) if tot else '(无 Totals)'))
    if FAIL_RE.findall(out):
        print('*** 基线就有 FAIL，无法继续')
        print(out[-3000:])
        return 2
    print()

    problems = []
    try:
        for item in MUT:
            name, old, new = item[0], item[1], item[2]
            expect_fail = item[3] if len(item) > 3 else True

            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG.replace(old, new, 1))
            if read() == _ORIG:
                print('  [夹具错误] %-46s 文件未变' % name)
                problems.append(name)
                io.open(SRC, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG)
                continue

            t0 = mt(OBJ)
            rb = build()
            if rb.returncode != 0:
                print('  [构建失败] %-46s %s' % (
                    name, (rb.stdout + rb.stderr).decode(
                        'utf-8', 'replace')[-180:]))
                problems.append(name)
                io.open(SRC, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG)
                continue
            t1 = mt(OBJ)

            rr = run_exe()
            out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
            failed = FAIL_RE.findall(out)
            nfail = len(failed)
            crashed = rr.returncode != 0 and not failed
            totals = re.search(r'Totals:\s*(\d+) passed,\s*(\d+) failed', out)
            consistent = (totals is not None
                          and rr.returncode == int(totals.group(2)))

            if t1 <= t0:
                print('  [夹具错误] %-46s .obj 未重编（可能是旧二进制）' % name)
                problems.append(name)
            elif expect_fail:
                if failed or crashed:
                    tag = ('崩溃(rc=%d, 0 条 FAIL 行)' % rr.returncode
                           if crashed else
                           '%d 条 FAIL 行(rc=%d%s)'
                           % (nfail, rr.returncode,
                              '' if consistent else ' 与计数不符'))
                    print('  %-46s 被抓到 ✓ %s' % (name, tag))
                else:
                    print('  %-46s *** 未被抓到（假绿）rc=%d'
                          % (name, rr.returncode))
                    problems.append(name)
            else:
                if not failed and not crashed:
                    print('  %-46s 通过 ✓（不误报）' % name)
                else:
                    print('  %-46s *** 误报' % name)
                    problems.append(name)

            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG)
    finally:
        io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)

    same = read() == _ORIG
    print()
    print('还原逐字节一致:', same)

    # -----------------------------------------------------------------
    # 实测"判定为不可观测"的那几个退化：必须真的抓不到。
    # 一旦能抓到，说明它已可观测，应提升为真变异而不是继续免责。
    # -----------------------------------------------------------------
    print()
    print('--- 已判定不可观测的退化（必须抓不到；一旦能抓到就该提升为真变异）---')
    for item in UNDETECTABLE:
        name, old, new = item[0], item[1], item[2]
        io.open(SRC, 'w', encoding='utf-8',
                newline='\n').write(_ORIG.replace(old, new, 1))
        if read() == _ORIG:
            print('  [夹具错误] %-46s 文件未变' % name)
            problems.append(name)
            io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)
            continue
        rb = build()
        if rb.returncode != 0:
            print('  *** %-46s 构建失败（不可再自称不可观测）：%s'
                  % (name, (rb.stdout + rb.stderr).decode(
                      'utf-8', 'replace')[-150:]))
            problems.append(name)
            io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)
            continue
        rr = run_exe()
        out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
        failed = FAIL_RE.findall(out)
        nfail = len(failed)
        crashed = rr.returncode != 0 and not failed
        if failed or crashed:
            print('  *** %-46s 竟然被抓到了（%d 条 FAIL, rc=%d）'
                  % (name, nfail, rr.returncode))
            print('      => 它已可观测，应提升为真变异，而不是继续免责')
            problems.append(name)
        else:
            print('  %-46s 确认抓不到 ✓' % name)
        io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)

    same = same and (read() == _ORIG)

    build()
    rr = run_exe()
    for l in (rr.stdout + rr.stderr).decode('utf-8', 'replace').split('\n'):
        if 'Totals' in l:
            print('还原后全量:', l.strip())
    print()
    print('变异 %d 个（另有无判别力退化 %d 个已实测确认），致命问题 %d 个'
          % (len(MUT), len(UNDETECTABLE), len(problems)))
    if problems:
        print('问题清单:', problems)
    return 1 if (problems or not same) else 0


if __name__ == '__main__':
    sys.exit(main())
