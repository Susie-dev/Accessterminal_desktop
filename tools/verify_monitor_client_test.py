# -*- coding: utf-8 -*-
"""MonitorClient 测试的故障注入自检（纯 Python，Windows 路径）。

用法：python tools/verify_monitor_client_test.py
返回码 0 表示：每个危险退化都被抓到，且两个对照未误报。

要证明的核心命题
----------------
本测试的价值全在"能不能抓到**线上字节**与**接收态机**的退化"。
每个变异都朝 monitor_client.cpp 真实的危险退化去改，并要求对应用例失败。

为什么这些变异值得单独钉
------------------------
UDP 50000 是**协议硬约束**的一员，而它的语义与另外三条都不同：
请求文本是**裸的、不带 '\\n'**（TCP 8887 信令带 '\\n'），文本身份必须与
门口机 CameraUdpServer 的 exact match 逐字节一致。把 "getframe" 写成
"getframe\\n" 或把 "stop" 写成 "stopsend" 都会让门口机**静默不响应** ——
不报错、不断连，只是永远没有画面。这类退化只有测试能提前发现。

变异（全部是真实危险的退化）
  1. 请求文本 getframe -> get_frame（门口机 exact match 落空）
  2. 请求文本 getframe -> "getframe\\n"（多一个换行）
  3. 停止文本 stop -> stopsend（**同一前缀的另一个信令，极易混淆**）
  4. 停止文本 stop -> "stop\\n"
  5. getframe 发到错误端口（50001）
  6. stop 发到错误端口（50001）
  7. 首次 toggle 反而发 stop（开关逻辑反了）
  8. 再次 toggle 反而发 getframe
  9. 首次 toggle 不置 m_active = true（状态机不翻转）
 10. 再次 toggle 不置 m_active = false
 11. toggle 不再 emit activeChanged（UI 状态不同步）
 12. toggle 忽略 ensureSocket 的失败结果（绑定失败仍当成功）
 13. ensureSocket 绑定失败时仍返回 true
 14. stop() 不关闭 socket（端口泄漏，下次监看绑不上）
 15. stop() 不清 m_active（"停止后还在接收态"）
 16. stop() 还发 activeChanged(false)（重复翻转 -> UI 抖动/状态错）
 17. 析构不调用 stop()（RAII 失效）
 18. onReadyRead 只读一个数据报（if 取代 while -> 一次突发只出一帧）
 19. onReadyRead 不检查 !pix.isNull()（垃圾数据也当一帧发出去）
 20. onReadyRead 忽略 readDatagram 返回值（保留未初始化尾部字节）
 21. 最终帧不 emit frameReceived（收了但不上报）

对照（必须通过）
  C1. 只加无关注释
  C2. 改 qDebug 文案（不影响语义）

**故意不测的变异（如实记录限制）**
  - `"JPG"` -> `"JPEG"`：**实测 QPixmap::loadFromData 对两个标识都能解码**
    真实 JPEG（探针 result5.txt：两者都得 isNull=0、64x48），因此**任何行为
    断言都抓不到这个改动** —— 加进去只会得到一条假的"已覆盖"。
    这条限制由 tools/verify.py 的静态规则
    `check_monitor_client_jpeg_decoder_hint_is_pinned` 补上（它直接检查该
    字面量，并同时检查门口机侧的 "JPEG"，防止两侧被"顺手统一"）。
  - 去掉 `ShareAddress | ReuseAddressHint`：端口空闲时独占绑定同样成功，
    行为无差别（探针实测），没有判别力，故不列为变异。
"""
import atexit
import io
import os
import re
import shutil
import signal
import subprocess
import tempfile
# 注意：判定 FAIL 行只看行首 ``FAIL!``，**不要**去匹配用例名的形状。
# 数据驱动用例输出的是 ``Class::case(desk)`` 而不是 ``Class::case()``，
# 用 ``\w+::(\w+)\(\)`` 会漏掉它们，把正常的断言失败误判成崩溃。
import sys

# 标准输出固定 UTF-8：本机控制台是 GBK，脚本里的 ✓ 会抛 UnicodeEncodeError，
# 且崩在**打印结果那一行**，极易被误读成"通过"。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

if len(sys.argv) > 1:
    print("提示: 本脚本不需要参数，已忽略: %s" % " ".join(sys.argv[1:]))


# ---------------------------------------------------------------------------
# 路径：由脚本自身定位，跨平台可跑。
#
# 原先这里写死 Windows 路径（C:\Users\user\...）并依赖 %TEMP%，结果是本夹具
# **只能在作者那一台机器上运行**：在 Linux 上直接 KeyError: 'TEMP' 退出。
# 而"夹具必须真的能跑"正是本工程的核心约定（README 开发约定第 N 条），
# 一个跑不起来的夹具等于没有判别力。现改为：
#
#   - 仓库根由 __file__ 反推（tools/ 的上一级），可用第 1 个参数覆盖；
#   - 构建目录走 tempfile，尊重 TMPDIR/TEMP；
#   - 可执行文件与 .obj 的名称按平台推断（Windows 有 .exe 与 .obj，
#     Linux 无后缀且 .o）。
#
# 用法（两平台一致）：
#   python3 tools/verify_monitor_client_test.py [<仓库根>]
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(_HERE)
SRC = os.path.join(D, 'src', 'core', 'net', 'monitor_client.cpp')

# cmake：优先用 PATH 里的，找不到再回退到 MSYS2 的常见位置。
CMAKE = shutil.which('cmake') or os.path.join(
    r'C:\Users\user\.dsh\toolchains\msys64', 'mingw64', 'bin', 'cmake.exe')

BUILD = os.path.join(tempfile.gettempdir(), 'fi_monitor_client')
_EXE_SUFFIX = '.exe' if os.name == 'nt' else ''
_OBJ_SUFFIX = '.obj' if os.name == 'nt' else '.o'
EXE = os.path.join(BUILD, 'desktop_test_monitor_client' + _EXE_SUFFIX)

# .obj/.o 的中间路径由构建目录到源文件的相对位置决定，不能写死作者机器的
# 目录名：把仓库根相对构建目录拼出来，并只取盘符/根之后的部分（CMake 会
# 把绝对路径里的 ':' 等字符转义成 '_'）。
_REL_SRC = os.path.relpath(SRC, os.path.splitdrive(BUILD)[0] + os.sep) \
    if os.name == 'nt' else os.path.relpath(SRC, os.sep)
OBJ = os.path.join(BUILD, 'CMakeFiles', 'desktop_test_monitor_client.dir',
                   _REL_SRC + _OBJ_SUFFIX)

ENV = dict(os.environ)
# 仅在 MSYS2 存在时才改 PATH，避免污染 Linux 的 PATH。
for _maybe in (r'C:\Users\user\.dsh\toolchains\msys64\mingw64\bin',):
    if os.path.isdir(_maybe):
        ENV['PATH'] = _maybe + os.pathsep + ENV.get('PATH', '')



def read_src():
    return io.open(SRC, encoding='utf-8', errors='replace').read()


_ORIG = read_src()


# ---------------------------------------------------------------------------
# 崩溃安全：本夹具是**就地改写真实源码**再还原的（src/core/net/monitor_client.cpp
# 就是工作区里那个文件）。原先每个变异的还原写在循环体**末尾**，一旦两次
# 写盘之间有异常（构建目录被删 -> Popen(cwd=D) 抛 FileNotFoundError、Ctrl-C、
# 断电、磁盘满……），异常会直接穿出循环，**还原那行永远执行不到**，
# 于是"变异态"就被永久留在工作区里 —— 而工作区此时看起来完全正常，
# 直到有人跑 tools/verify.py 才炸出一条莫名其妙的失败。
#
# 实测踩坑：一次运行因仓库目录被外部改名而抛 FileNotFoundError，
# 恰好卡在 UNDETECTABLE 的"去掉 resize 缩容"变异上，源码里的
# `if (bytesRead < datagram.size())` 就这么丢了一整天，verify.py 报红。
#
# 因此：把还原登记为**最优先的退出钩子**。atexit 在正常退出与 sys.exit 时
# 都会跑（LIFO，故注册在最后也无妨——这里只有这一个钩子），
# 信号钩子再兜住 SIGINT/SIGTERM 这类不触发 atexit 的情形。
# 还原是**幂等**的：写回 _ORIG 的原始字节，无论当前是不是变异态都安全。
# ---------------------------------------------------------------------------
def restore_src():
    """把源码写回运行本夹具之前捕获的原始字节（幂等）。"""
    try:
        current = read_src()
    except Exception:
        return
    if current != _ORIG:
        try:
            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG)
            print('\n[崩溃安全] 已把 %s 还原为运行前的原始内容'
                  % os.path.relpath(SRC, D))
        except Exception as exc:  # 还原失败必须吼出来，不能静默
            print('\n[崩溃安全][严重] 源码还原失败，工作区可能残留变异态: %r'
                  % (exc,))


atexit.register(restore_src)


def _restore_on_signal(signum, _frame):
    restore_src()
    # 恢复默认处置再自杀，让退出码正确反映"被信号打断"。
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


for _sig in (getattr(signal, 'SIGINT', None), getattr(signal, 'SIGTERM', None)):
    if _sig is not None:
        try:
            signal.signal(_sig, _restore_on_signal)
        except (ValueError, OSError):
            pass  # 非主线程等场景下装不上，atexit 仍兜底


def anchor(start_marker):
    """从**真实文件字节**里切出一个**完整的块**（花括号配对到收尾）。

    用配对而不是手写结束标记：生产代码是逐行注释风格，`return;` 与 `}` 之间
    夹着注释行，手抄结束标记极易漂移。
    """
    i = _ORIG.index(start_marker)
    j = _ORIG.index('{', i)
    depth = 0
    k = j
    while k < len(_ORIG):
        c = _ORIG[k]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return _ORIG[i:k + 1]
        k += 1
    raise ValueError('unbalanced braces for %r' % start_marker)


# ---- 从真实字节构造锚点 ----
GETFRAME_LIT = 'const QByteArray kGetFrame = QByteArrayLiteral("getframe");'
STOP_LIT = 'const QByteArray kStop = QByteArrayLiteral("stop");'

SEND_GETFRAME = ('        m_socket->writeDatagram(kGetFrame, m_deviceAddress, '
                 'protocol::kPreviewPort);')

# `writeDatagram(kStop, ...)` 这条语句现在出现**两次**：toggle() 的 else 分支
# 一次、stop() 里一次（后者是"退出时通知门口机停推"的修复）。两行的缩进与
# 文本完全相同，所以裸语句**不再是唯一锚点** —— 夹具的锚点唯一性自证会直接
# 报"[夹具错误] ... 锚点出现 2 次"。因此各带上一行独有的上下文来区分。
SEND_STOP_IN_TOGGLE = ('    } else {\n'
                       '        m_socket->writeDatagram(kStop, m_deviceAddress, '
                       'protocol::kPreviewPort);')
SEND_STOP_IN_STOP = ('    if (m_active && m_socket) {\n'
                     '        m_socket->writeDatagram(kStop, m_deviceAddress, '
                     'protocol::kPreviewPort);')

TOGGLE_IF = '    if (!m_active) {'
STOP_BODY = anchor('void MonitorClient::stop()')
ENSURE_BODY = anchor('bool MonitorClient::ensureSocket()')
ONREADY_BODY = anchor('void MonitorClient::onReadyRead()')
DTOR = anchor('MonitorClient::~MonitorClient()')

# stop() 内的三件套（必须唯一到 stop()，不能误命中 toggle() 里的 m_active = false）
STOP_ACTIVE_BLOCK = ('    if (m_active) {\n'
                     '        m_active = false;\n'
                     '        emit activeChanged(false);\n'
                     '    }\n')

# onReadyRead 的 while 循环
READ_WHILE = '    while (m_socket->hasPendingDatagrams()) {'

# 负载判定 + 上报
PAYLOAD_IF = ('        if (pix.loadFromData(datagram, "JPG") && !pix.isNull()) {\n'
              '            emit frameReceived(pix);\n'
              '        }')


MUT = [
    ("请求文本 getframe -> get_frame（门口机 exact match 落空）",
     GETFRAME_LIT,
     GETFRAME_LIT.replace('"getframe"', '"get_frame"')),

    ("请求文本 getframe 多一个换行",
     GETFRAME_LIT,
     GETFRAME_LIT.replace('"getframe"', '"getframe\\n"')),

    # 'stop' 是 'stopsend' 的前缀。把停止发成 stopsend，门口机会当成完全
    # 不同的信令（那是 TCP 8887 的"本端停止发送"），UDP 侧永远不会停推。
    ("停止文本 stop -> stopsend（同前缀的另一个信令）",
     STOP_LIT,
     STOP_LIT.replace('"stop"', '"stopsend"')),

    ("停止文本 stop 多一个换行",
     STOP_LIT,
     STOP_LIT.replace('"stop"', '"stop\\n"')),

    ("getframe 发到错误端口 50001",
     SEND_GETFRAME,
     SEND_GETFRAME.replace('protocol::kPreviewPort', '50001')),

    ("stop 发到错误端口 50001",
     SEND_STOP_IN_TOGGLE,
     SEND_STOP_IN_TOGGLE.replace('protocol::kPreviewPort', '50001')),

    ("首次 toggle 反而发 stop（开关逻辑反了）",
     '        m_socket->writeDatagram(kGetFrame,',
     '        m_socket->writeDatagram(kStop,'),

    ("再次 toggle 反而发 getframe",
     SEND_STOP_IN_TOGGLE,
     SEND_STOP_IN_TOGGLE.replace('kStop', 'kGetFrame')),

    # 本轮新增：stop() 必须通知门口机停止推流（交接文档 1.3 条）。
    # 这是**曾经真实缺失**的一条：修复前 stop() 只关本地 socket，从不发
    # kStop，而门口机 CameraUdpServer 只在收到 Stop 时 sendTimer->stop()，
    # 于是"监看中途退出程序"会让它按 20fps 永久空转推流。
    ("stop() 不通知门口机（退出后门口机永久推流）",
     SEND_STOP_IN_STOP,
     '    if (m_active && m_socket) {\n'),

    # 守卫被弱化：未处于接收态时也补发 stop（多余信令）。
    # 这条是实测的**变异漏网**：原有用例全绿，因为"停过之后 socket 已被
    # 销毁"，守卫里的 m_socket 恰好也为假。补了
    # stopAfterToggleOffDoesNotResendStop（toggle 开→关、socket 仍在）才抓住。
    ("stop() 失去 m_active 守卫（未接收也发 stop）",
     '    if (m_active && m_socket) {',
     '    if (m_socket) {'),

    # STOP_ACTIVE_BLOCK 必须恰好出现在 stop() 里一次（自证见 main）
    ("stop() 不清 m_active（停止后仍处于接收态）",
     STOP_ACTIVE_BLOCK,
     '    if (m_active) {\n        emit activeChanged(false);\n    }\n'),

    ("stop() 重复发 activeChanged(false)",
     STOP_ACTIVE_BLOCK,
     '    if (m_active) {\n        m_active = false;\n'
     '        emit activeChanged(false);\n        emit activeChanged(false);\n    }\n'),

    ("stop() 不关闭 socket（端口泄漏）",
     '        m_socket->close();\n', ''),

    ("析构不调用 stop()（RAII 失效）",
     DTOR,
     'MonitorClient::~MonitorClient()\n{\n}'),

    ("绑定失败时 ensureSocket 仍返回 true",
     '        delete m_socket;\n        m_socket = nullptr;\n        return false;\n',
     '        delete m_socket;\n        m_socket = nullptr;\n        return true;\n'),

    ("toggle 忽略 ensureSocket 的失败结果",
     '    if (!ensureSocket()) {\n        return false;\n    }\n',
     ''),

    # 去掉 !pix.isNull()：垃圾数据也会被当成一帧 emit 出去。
    ("onReadyRead 不检查解码结果（垃圾数据也上报）",
     PAYLOAD_IF,
     '        pix.loadFromData(datagram, "JPG");\n'
     '        emit frameReceived(pix);'),

    ("收到完整帧后不上报（收了但不用）",
     '            emit frameReceived(pix);\n', ''),

    ("对照：加无关注释",
     'bool MonitorClient::ensureSocket()',
     'bool MonitorClient::ensureSocket()\n    // 无关注释', False),

    ("对照：改 qDebug 文案（不影响语义）",
     'qDebug() << "[监看] 已发送 getframe 到" << deviceIp;',
     'qDebug() << "[monitor] sent getframe to" << deviceIp;', False),
]


# ---------------------------------------------------------------------------
# 如实记录：**经实测判定为本测试不可观测**的退化。
#
# 这些不是"忘了测"，而是"测了也抓不到"：把它们塞进 MUT 只会得到一条
# 假的"已覆盖"。但也不能只是嘴上说说 —— 夹具要**实测证明**它们确实抓不到，
# 并在将来某次改动让它们变得可观测时**提醒把它提升为真变异**。
# 这是"未触发时先证明变异真的改变了被测属性"这条规矩的正向用法。
# ---------------------------------------------------------------------------
UNDETECTABLE = [
    # 实测（探针 result8.txt）：Qt 在数据报仍有剩余时会**再次**发出
    # readyRead，所以 "while 全排空" 与 "一次只读一个" 最终都把帧送完，
    # 只有回调次数不同：
    #     连发 50 个：while 版读到 50、readyRead 触发 1 次
    #                 if    版读到 50、readyRead 触发 50 次
    # 因此"帧有没有全到"这个可观测量对 while/if **没有判别力**。
    # （不能用 `if` 取代 `while`：循环体里有 `continue`，改成 if 会直接
    #  编译失败。这里用只跑一次的 for —— 仍是循环，但至多读一个数据报。）
    # `while` 的存在改由 tools/verify.py 的静态规则直接检查源码文本来保证。
    ("onReadyRead 只读一个数据报（while 改成只跑一次）",
     READ_WHILE,
     '    for (int once = 0;\n'
     '         once < 1 && m_socket->hasPendingDatagrams(); ++once) {'),

    # 实测（探针 result7.txt）：缓冲区按 pendingDatagramSize() 分配时，
    # readDatagram 的返回值**永远等于**该大小（长度 0/1/4/100/678/1400/65507
    # 全部相等=1）。因此 `bytesRead < 0` 与 `bytesRead < datagram.size()`
    # 两个分支在真实 socket 路径上**不可达**，删掉它们没有任何可观测差别。
    # 这段防御代码的价值是"将来若换实现/换平台仍安全"，属于纵深防御。
    # 它由 tools/verify.py 的静态规则守着（规则会检查这两个判断存在）。
    ("onReadyRead 忽略 readDatagram 返回值",
     '        if (bytesRead < 0) {\n            continue; // 读取失败，丢弃该数据报\n        }\n',
     ''),

    ("onReadyRead 不做 bytesRead < size 的缩容",
     '        if (bytesRead < datagram.size()) {\n            datagram.resize(static_cast<int>(bytesRead));\n        }\n',
     ''),
]


def build(target=None):
    args = [CMAKE, '--build', BUILD]
    if target:
        args += ['--target', target]
    return subprocess.run(args, capture_output=True, env=ENV, cwd=D)


def run_exe():
    return subprocess.run([EXE], capture_output=True, env=ENV, cwd=D)


def main():
    # 锚点唯一性自证：锚点必须唯一，且必须唯一到**正确的函数**。
    for item in MUT + UNDETECTABLE:
        name, old = item[0], item[1]
        n = _ORIG.count(old)
        if n != 1:
            print('[夹具错误] %s 锚点出现 %d 次（必须恰好 1 次）' % (name, n))
            return 2

    # STOP_ACTIVE_BLOCK 必须唯一到 stop()：它靠的是这段文字在 todo 文件里
    # **恰好出现一次**。实测 `        m_active = false;` 在文件里出现 **2** 次
    # （stop() 一次、toggle() 的 else 分支一次），所以唯一性不能靠它，
    # 而要靠整块（含 if 与 emit）—— 自证如下。
    if _ORIG.count(STOP_ACTIVE_BLOCK) != 1:
        print('[夹具错误] stop() 里的 m_active 块出现 %d 次（必须恰好 1 次）'
              % _ORIG.count(STOP_ACTIVE_BLOCK))
        return 2
    if _ORIG.count('        m_active = false;\n') != 2:
        print('[夹具错误] 期望 "        m_active = false;" 出现 2 次'
              '（stop + toggle else），实际 %d 次'
              % _ORIG.count('        m_active = false;\n'))
        return 2

    # 夹具自身逻辑自证：确认两处端口常量确实还在（否则变异 5/6 会变成假变异）
    if _ORIG.count('protocol::kPreviewPort') < 3:
        print('[夹具错误] protocol::kPreviewPort 出现次数过少，变异 5/6 会失效')
        return 2

    shutil.rmtree(BUILD, ignore_errors=True)
    r = subprocess.run([CMAKE, '-S', os.path.join(D, 'tests'), '-B', BUILD,
                        '-G', 'Ninja'], capture_output=True, env=ENV, cwd=D)
    print('configure rc=%d' % r.returncode)
    if r.returncode != 0:
        print(r.stderr.decode('utf-8', 'replace')[-1500:])
        return 2
    rb = build('desktop_test_monitor_client')
    if rb.returncode != 0:
        print('基线构建失败:')
        print((rb.stdout + rb.stderr).decode('utf-8', 'replace')[-1500:])
        return 2
    print()

    problems = []
    try:
        for item in MUT:
            name, old, new = item[0], item[1], item[2]
            expect_fail = item[3] if len(item) > 3 else True

            text = _ORIG.replace(old, new, 1)
            io.open(SRC, 'w', encoding='utf-8', newline='\n').write(text)
            if read_src() == _ORIG:
                print('  [夹具错误] %-46s 文件未变' % name)
                problems.append(name)
                io.open(SRC, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG)
                continue

            t0 = os.path.getmtime(OBJ) if os.path.exists(OBJ) else 0
            rb = build('desktop_test_monitor_client')
            if rb.returncode != 0:
                print('  [构建失败] %-46s %s' % (
                    name, (rb.stdout + rb.stderr).decode(
                        'utf-8', 'replace')[-220:]))
                problems.append(name)
                io.open(SRC, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG)
                continue
            t1 = os.path.getmtime(OBJ) if os.path.exists(OBJ) else 0

            rr = run_exe()
            out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
            failed = re.findall(r'^FAIL!\s*:', out, re.M)

            # QtTest 的退出码 == FAIL 行数。所以 "returncode not in (0,1)"
            # **不能**用来判断崩溃 —— 那会把"多个用例干净失败"误标成"崩溃"，
            # 也会让真正的崩溃（如 0xC0000005）与它混为一谈。
            # 真正的崩溃 = 非零退出码但**一条 FAIL 行都没有**。
            totals = re.search(r'Totals:\s*(\d+) passed,\s*(\d+) failed', out)
            crashed = rr.returncode != 0 and not failed
            consistent = (totals is not None
                          and rr.returncode == int(totals.group(2)))

            if t1 <= t0:
                print('  [夹具错误] %-46s .obj 未重编' % name)
                problems.append(name)
            elif expect_fail:
                if failed or crashed:
                    if crashed:
                        tag = '崩溃(rc=%d, 0 条 FAIL 行)' % rr.returncode
                    elif consistent:
                        tag = '%d 条 FAIL 行(rc=%d)' % (len(failed), rr.returncode)
                    else:
                        tag = '%d 条 FAIL 行(rc=%d 与 failed 计数不符)' % (
                            len(failed), rr.returncode)
                    print('  %-46s 被抓到 ✓ %s' % (name, tag))
                else:
                    print('  %-46s *** 未被抓到（假绿）rc=%d' % (name, rr.returncode))
                    problems.append(name)
            else:
                if not failed and not crashed:
                    print('  %-46s 通过 ✓（不误报）' % name)
                else:
                    print('  %-46s *** 误报：%s' % (name, failed[:3]))
                    problems.append(name)

            io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)
    finally:
        io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)

    same = read_src() == _ORIG
    print()
    print('还原逐字节一致:', same)

    # -----------------------------------------------------------------
    # 实测"判定为不可观测"的那几个退化：必须真的抓不到。
    #
    # 逻辑要反过来：MUT 里要求"必须抓到"，这里要求"必须抓不到"。
    # 若某天它**被抓到了**，说明代码或测试变了、这个退化变得可观测 ——
    # 那就该把它提升为 MUT 里的真变异，而不是继续留在免责清单里。
    # 这条检查把"我们没测它"从一句托词变成一条可执行的断言。
    # -----------------------------------------------------------------
    print()
    print('--- 已判定不可观测的退化（必须抓不到；一旦能抓到就该提升为真变异）---')
    for item in UNDETECTABLE:
        name, old, new = item[0], item[1], item[2]
        if _ORIG.count(old) != 1:
            print('  [夹具错误] %-46s 锚点出现 %d 次'
                  % (name, _ORIG.count(old)))
            problems.append(name)
            continue
        io.open(SRC, 'w', encoding='utf-8',
                newline='\n').write(_ORIG.replace(old, new, 1))
        if read_src() == _ORIG:
            print('  [夹具错误] %-46s 文件未变' % name)
            problems.append(name)
            io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)
            continue
        rb = build('desktop_test_monitor_client')
        if rb.returncode != 0:
            # 构建都过不去 => 这个变异改变了编译结果，已不是"不可观测"
            print('  *** %-46s 构建失败（不可再自称不可观测）' % name)
            problems.append(name)
            io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)
            continue
        rr = run_exe()
        out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
        failed = re.findall(r'^FAIL!\s*:', out, re.M)
        crashed = rr.returncode != 0 and not failed
        if failed or crashed:
            print('  *** %-46s 竟然被抓到了（%d 条 FAIL, rc=%d）'
                  % (name, len(failed), rr.returncode))
            print('      => 它已可观测，应提升为真变异，而不是继续免责')
            problems.append(name)
        else:
            print('  %-46s 确认抓不到 ✓（与探针 result7.txt 一致）' % name)
        io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)

    same = same and (read_src() == _ORIG)
    print()
    build('desktop_test_monitor_client')
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
