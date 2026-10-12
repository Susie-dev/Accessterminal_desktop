# -*- coding: utf-8 -*-
"""对第 31 轮新增的 check_monitor_client_contract_is_pinned 做故障注入自检。

每个变异都朝真实的危险退化去改，并要求 verify.py **必须失败**；
两个对照必须仍然通过（不误报）。
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
T = r'C:\Users\user\Desktop\linux_ai\Accessterminal_T113'
PY = r'C:\Users\user\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
VERIFY = os.path.join(D, 'tools', 'verify.py')
MC = os.path.join(D, 'src', 'core', 'net', 'monitor_client.cpp')
WID = os.path.join(D, 'src', 'ui', 'widget.cpp')


def read(p):
    return io.open(p, encoding='utf-8', errors='replace').read()


_ORIG = {p: read(p) for p in (MC, WID)}


def sub(p, old, new, count=1):
    """返回 (path, mutated_text)；同时自证 old 恰好出现 count 次。"""
    s = _ORIG[p]
    n = s.count(old)
    if n != count:
        raise AssertionError('%s 锚点出现 %d 次（期望 %d）: %r'
                             % (os.path.basename(p), n, count, old[:60]))
    return s.replace(old, new, count)


# (名称, 目标文件, 旧, 新)  —— 期望 verify.py 失败
MUT = [
    ("解码提示改成 JPEG（与门口机侧『顺手统一』）",
     MC, 'loadFromData(datagram, "JPG")', 'loadFromData(datagram, "JPEG")'),

    ("解码提示改成空串", 
     MC, 'loadFromData(datagram, "JPG")', 'loadFromData(datagram, "")'),

    ("while 排空退化成只读一个（if 版）",
     MC, '    while (m_socket->hasPendingDatagrams()) {',
     '    if (m_socket->hasPendingDatagrams()) {'),

    ("while 退化成只跑一次的 for",
     MC, '    while (m_socket->hasPendingDatagrams()) {',
     '    for (int once = 0; once < 1 && m_socket->hasPendingDatagrams(); ++once) {'),

    ("删掉 readDatagram 返回值",
     MC, '        const qint64 bytesRead = m_socket->readDatagram(datagram.data(), datagram.size());\n',
     '        m_socket->readDatagram(datagram.data(), datagram.size());\n'),

    ("删掉 bytesRead < 0 判断",
     MC, '        if (bytesRead < 0) {\n            continue; // 读取失败，丢弃该数据报\n        }\n',
     ''),

    ("删掉 bytesRead < size 的缩容",
     MC, '        if (bytesRead < datagram.size()) {\n            datagram.resize(static_cast<int>(bytesRead));\n        }\n',
     ''),

    ("请求文本 getframe -> get_frame",
     MC, 'QByteArrayLiteral("getframe")', 'QByteArrayLiteral("get_frame")'),

    ("请求文本加换行",
     MC, 'QByteArrayLiteral("getframe")', 'QByteArrayLiteral("getframe\\n")'),

    ("停止文本 stop -> stopsend",
     MC, 'QByteArrayLiteral("stop")', 'QByteArrayLiteral("stopsend")'),

    ("停止文本加换行",
     MC, 'QByteArrayLiteral("stop")', 'QByteArrayLiteral("stop\\n")'),

    # 端口硬编码：protocol::kPreviewPort 在文件里出现 6 次，全部替换。
    #
    # 这个计数**曾经是 5**，后来变成 6 —— 第 45 轮才被发现：
    # `48f89dd`（退出监看时给门口机发 stop）在 stop() 里新增了一处
    # `writeDatagram(..., protocol::kPreviewPort)`，但**没有同步这里的计数**。
    # 于是夹具变成 `锚点出现 6 次（期望 5）` 的**夹具错误**并一直红着，
    # 而它看起来只像"某个变异有问题"，很容易被当成环境噪声忽略。
    #
    # 计数型锚点的固有风险：被计数的那个 token 是**正常会被修改**的东西
    # （这里每加一处端口引用就该改一次）。改代码的人不会知道这个数字在夹具里。
    # 保留计数是因为它能证明"全部替换"，但每次改动 monitor_client.cpp 都要
    # 顺手核对它 —— 这也是本仓库把"夹具长期红着必须解释"写进 README 第 66 条的
    # 直接起因。
    ("端口硬编码 50000",
     MC, 'protocol::kPreviewPort', '50000', 6),

    # 只删 onVideoFrameReady 里那道门。**必须带上 frame.isNull()**
    # 这个限定，否则会连 on_btngetframe_clicked 里的 `if (!m_cameraActive)`
    # 一起改掉 —— 那条规则专门处理"别处顶包"的情况，变异也要精确。
    ("Widget 去掉非活动态不收帧的门",
     WID, 'if (frame.isNull() || !m_cameraActive) {', 'if (frame.isNull()) {'),

    ("Widget 退回内联 writeDatagram（不走 MonitorClient）",
     WID, 'm_monitor->toggle(', 'm_monitorInline_toggle('),
]

# 对照：必须仍然通过
CTRL = [
    ("加无关注释", MC,
     'bool MonitorClient::ensureSocket()',
     'bool MonitorClient::ensureSocket()\n    // 无关注释'),
    ("改 qDebug 文案", MC,
     'qDebug() << "[监看] 已发送 getframe 到"',
     'qDebug() << "[monitor] sent getframe to"'),
]


def run_verify():
    return subprocess.run([PY, VERIFY, D, T], capture_output=True, cwd=D)


def main():
    problems = []
    try:
        # 基线：必须先通过
        r = run_verify()
        out = (r.stdout + r.stderr).decode('utf-8', 'replace')
        print('基线 rc = %d' % r.returncode)
        if r.returncode != 0:
            print('*** 基线就不过，无法继续')
            print(out[-2500:])
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
            hit = ('[monitor-client]' in out)
            hits = re.findall(r'^\s*X (\[monitor-client\][^\n]*)', out, re.M)
            if r.returncode != 0 and hit:
                print('  %-44s 被抓到 ✓ %s' % (
                    name, (hits[0][:64] if hits else '')))
            else:
                print('  %-44s *** 未被抓到（假绿）rc=%d' % (name, r.returncode))
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
                print(out[-800:])
                problems.append(name)
            io.open(p, 'w', encoding='utf-8', newline='\n').write(_ORIG[p])
    finally:
        for p in (MC, WID):
            io.open(p, 'w', encoding='utf-8', newline='\n').write(_ORIG[p])

    same = all(read(p) == _ORIG[p] for p in (MC, WID))
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
