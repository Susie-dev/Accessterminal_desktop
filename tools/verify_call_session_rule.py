# -*- coding: utf-8 -*-
"""对第 34 轮新增的 check_call_session_contract_is_pinned 做故障注入自检。"""
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
CS = os.path.join(D, 'src', 'core', 'media', 'call_session.cpp')


def read(p):
    return io.open(p, encoding='utf-8', errors='replace').read()


_ORIG = read(CS)


def sub(old, new, count=1):
    n = _ORIG.count(old)
    if n != count:
        raise AssertionError('锚点出现 %d 次（期望 %d）: %r' % (n, count, old[:70]))
    return _ORIG.replace(old, new, count)


MUT = [
    ("音频口去掉 ShareAddress",
     '    if (!m_audioSocket->bind(QHostAddress::AnyIPv4, protocol::kAudioPort,\n'
     '                             QUdpSocket::ShareAddress)) {\n',
     '    if (!m_audioSocket->bind(QHostAddress::AnyIPv4, protocol::kAudioPort)) {\n'),

    ("视频口去掉 ShareAddress",
     '    if (!m_videoSocket->bind(QHostAddress::Any, protocol::kVideoPort,\n'
     '                             QUdpSocket::ShareAddress)) {\n',
     '    if (!m_videoSocket->bind(QHostAddress::Any, protocol::kVideoPort)) {\n'),

    ("采样率写死 8000", 'format.setSampleRate(protocol::kAudioSampleRate);',
     'format.setSampleRate(8000);'),
    ("声道写死 2", 'format.setChannelCount(protocol::kAudioChannels);',
     'format.setChannelCount(2);'),
    ("位深改成 8", 'format.setSampleSize(protocol::kAudioBytesPerSample * 8);',
     'format.setSampleSize(8);'),
    ("字节序改大端", 'format.setByteOrder(QAudioFormat::LittleEndian);',
     'format.setByteOrder(QAudioFormat::BigEndian);'),
    ("采样类型改无符号", 'format.setSampleType(QAudioFormat::SignedInt);',
     'format.setSampleType(QAudioFormat::UnSignedInt);'),

    ("音频接收去掉 bytesRead<0 判断",
     '        if (bytesRead < 0) {\n'
     '            continue; // 读取失败，丢弃该数据报（不要污染设备地址）\n'
     '        }\n', ''),

    ("音频接收去掉缩容",
     '        if (bytesRead < datagram.size()) {\n'
     '            datagram.resize(static_cast<int>(bytesRead));\n'
     '        }\n'
     '\n'
     '        // 只有收到过终端音频包，才知道回传目标地址。\n',
     '\n        // 只有收到过终端音频包，才知道回传目标地址。\n'),

    ("视频接收去掉 bytesRead<0 判断",
     '        if (bytesRead < 0) {\n'
     '            continue; // 读取失败，丢弃该数据报\n'
     '        }\n', ''),

    ("视频接收去掉缩容",
     '        if (bytesRead < datagram.size()) {\n'
     '            datagram.resize(static_cast<int>(bytesRead));\n'
     '        }\n'
     '\n'
     '        // 每包一帧完整 JPEG，直接解码。\n',
     '\n        // 每包一帧完整 JPEG，直接解码。\n'),

    ("上行去掉地址守卫",
     '        if (!m_deviceAddress.isNull() && m_devicePort != 0) {\n',
     '        if (true) {\n'),

    # ---- stop() 清空指针（那 9 行"可达未测"真正不可达的前提）----
    # 注意 m_audioOutput/m_audioInput 的清理块在 startAudioOutput()/
    # startAudioInput() 里**也出现一次**（同样是"先拆旧的"），锚点必须带上
    # 足够的上下文才能唯一命中 stop() 里那一段。
    ("stop() 不清 m_audioSocket",
     '    if (m_audioSocket) {\n'
     '        m_audioSocket->close();\n'
     '        m_audioSocket->deleteLater();\n'
     '        m_audioSocket = nullptr;\n'
     '    }\n', ''),
    ("stop() 不清 m_videoSocket",
     '    if (m_videoSocket) {\n'
     '        m_videoSocket->close();\n'
     '        m_videoSocket->deleteLater();\n'
     '        m_videoSocket = nullptr;\n'
     '    }\n', ''),
    ("stop() 不清 m_audioOutput",
     '    if (m_audioOutput) {\n'
     '        m_audioOutput->stop();\n'
     '        delete m_audioOutput;\n'
     '        m_audioOutput = nullptr;\n'
     '    }\n'
     '    if (m_audioInput) {\n', '    if (m_audioInput) {\n'),
    ("stop() 不清 m_audioInput",
     '    if (m_audioInput) {\n'
     '        m_audioInput->stop();\n'
     '        delete m_audioInput;\n'
     '        m_audioInput = nullptr;\n'
     '    }\n'
     '    m_audioDevice = nullptr;\n',
     '    m_audioDevice = nullptr;\n'),
]

# 影子头注入方式（与 serial_light 同款风险）。CMake 在另一个文件里，
# 单独一组处理。
CM = os.path.join(D, 'tests', 'CMakeLists.txt')
_CM_ORIG = read(CM)

CM_MUT = [
    ("CMake 去掉 fake_audio 的 BEFORE",
     'target_include_directories(desktop_test_call_session BEFORE PRIVATE\n'
     '    ${CMAKE_CURRENT_LIST_DIR}/fake_audio\n'
     ')\n',
     'target_include_directories(desktop_test_call_session PRIVATE\n'
     '    ${CMAKE_CURRENT_LIST_DIR}/fake_audio\n'
     ')\n'),
    ("CMake 不再定义 ACC_CALL_SESSION_TEST",
     'target_compile_definitions(desktop_test_call_session PRIVATE\n'
     '    ACC_CALL_SESSION_TEST\n'
     ')\n', ''),
    ("CMake 不再引用 fake_audio 目录（只留源文件）",
     'target_include_directories(desktop_test_call_session BEFORE PRIVATE\n'
     '    ${CMAKE_CURRENT_LIST_DIR}/fake_audio\n'
     ')\n', ''),
]

SHIM = os.path.join(D, 'tests', 'fake_audio', 'QAudioFormat')
_SHIM_ORIG = read(SHIM)

SHIM_MUT = [
    ("影子头去掉 #error 安全阀",
     '#ifndef ACC_CALL_SESSION_TEST\n'
     '#  error "影子 QtMultimedia 头只能用于测试；请在测试目标上定义 ACC_CALL_SESSION_TEST"\n'
     '#endif\n', ''),
    ("影子头安全阀改成恒真（#ifndef -> #if 0）",
     '#ifndef ACC_CALL_SESSION_TEST\n', '#if 0\n'),
]

CTRL = [
    ("加无关注释（文件末尾）", '} // namespace accessterminal',
     '// 无关注释\n} // namespace accessterminal'),
    ("改 qInfo 文案", 'qInfo() << "[通话] 音视频通道已启动";',
     'qInfo() << "[call] channels up";'),
]


def run_verify():
    return subprocess.run([PY, VERIFY, D, T], capture_output=True, cwd=D)


def main():
    problems = []

    # 先把 CMake / 影子头的锚点也验一遍（避免 Region 写错却静默跳过）。
    for f, orig, muts, lbl in ((CM, _CM_ORIG, CM_MUT, 'CMakeLists'),
                               (SHIM, _SHIM_ORIG, SHIM_MUT, '影子头')):
        for item in muts:
            if orig.count(item[1]) != 1:
                print('[夹具错误] %s/%s 锚点出现 %d 次（必须恰好 1 次）: %r'
                      % (lbl, item[0], orig.count(item[1]), item[1][:60]))
                return 2

    try:
        r = run_verify()
        print('基线 rc = %d' % r.returncode)
        if r.returncode != 0:
            print('*** 基线就不过')
            print((r.stdout + r.stderr).decode('utf-8', 'replace')[-2500:])
            return 2
        print()

        for name, old, new in MUT:
            try:
                text = sub(old, new)
            except AssertionError as e:
                print('  [夹具错误] %-44s %s' % (name, e))
                problems.append(name)
                continue
            io.open(CS, 'w', encoding='utf-8', newline='\n').write(text)
            if read(CS) == _ORIG:
                print('  [夹具错误] %-44s 文件未变' % name)
                problems.append(name)
                io.open(CS, 'w', encoding='utf-8', newline='\n').write(_ORIG)
                continue

            r = run_verify()
            out = (r.stdout + r.stderr).decode('utf-8', 'replace')
            hits = re.findall(r'^\s*X (\[call\][^\n]*)', out, re.M)
            if r.returncode != 0 and hits:
                print('  %-44s 被抓到 ✓ %s' % (name, hits[0][:48]))
            else:
                print('  %-44s *** 未被抓到（假绿）rc=%d' % (name, r.returncode))
                problems.append(name)

            io.open(CS, 'w', encoding='utf-8', newline='\n').write(_ORIG)

        print()
        # ---- CMake 与影子头的变异 ----
        for f, orig, muts in ((CM, _CM_ORIG, CM_MUT),
                              (SHIM, _SHIM_ORIG, SHIM_MUT)):
            for name, old, new in muts:
                io.open(f, 'w', encoding='utf-8',
                        newline='\n').write(orig.replace(old, new, 1))
                if read(f) == orig:
                    print('  [夹具错误] %-44s 文件未变' % name)
                    problems.append(name)
                    io.open(f, 'w', encoding='utf-8',
                            newline='\n').write(orig)
                    continue
                r = run_verify()
                out = (r.stdout + r.stderr).decode('utf-8', 'replace')
                hits = re.findall(r'^\s*X (\[(?:call|serial)\][^\n]*)', out, re.M)
                if r.returncode != 0 and hits:
                    print('  %-44s 被抓到 ✓ %s' % (name, hits[0][:46]))
                else:
                    print('  %-44s *** 未被抓到（假绿）rc=%d'
                          % (name, r.returncode))
                    problems.append(name)
                io.open(f, 'w', encoding='utf-8',
                        newline='\n').write(orig)

        print()
        for name, old, new in CTRL:
            try:
                text = sub(old, new)
            except AssertionError as e:
                print('  [夹具错误] %-44s %s' % (name, e))
                problems.append(name)
                continue
            io.open(CS, 'w', encoding='utf-8', newline='\n').write(text)
            r = run_verify()
            out = (r.stdout + r.stderr).decode('utf-8', 'replace')
            if r.returncode == 0:
                print('  %-44s 通过 ✓（不误报）' % name)
            else:
                print('  %-44s *** 误报 rc=%d' % (name, r.returncode))
                print(out[-600:])
                problems.append(name)
            io.open(CS, 'w', encoding='utf-8', newline='\n').write(_ORIG)
    finally:
        io.open(CS, 'w', encoding='utf-8', newline='\n').write(_ORIG)
        io.open(CM, 'w', encoding='utf-8', newline='\n').write(_CM_ORIG)
        io.open(SHIM, 'w', encoding='utf-8', newline='\n').write(_SHIM_ORIG)

    same = (read(CS) == _ORIG and read(CM) == _CM_ORIG
            and read(SHIM) == _SHIM_ORIG)
    print()
    print('还原逐字节一致:', same)
    r = run_verify()
    for l in (r.stdout + r.stderr).decode('utf-8', 'replace').split('\n'):
        if '结论' in l:
            print('还原后:', l.strip())
    print()
    print('变异 %d 个（+CMake %d +影子头 %d），对照 %d 个，致命问题 %d 个'
          % (len(MUT), len(CM_MUT), len(SHIM_MUT), len(CTRL), len(problems)))
    if problems:
        print('问题清单:', problems)
    return 1 if (problems or not same) else 0


if __name__ == '__main__':
    sys.exit(main())
