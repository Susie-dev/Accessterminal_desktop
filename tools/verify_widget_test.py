# -*- coding: utf-8 -*-
"""Widget 测试的故障注入自检（跨平台）。

用法：python3 tools/verify_widget_test.py [<仓库根>]
返回码 0 表示：每个危险退化都被抓到，对照未误报，且源码被逐字节还原。

要证明的核心命题
----------------
`tests/test_widget.cpp` 的价值全在"能不能抓到 `src/ui/widget.cpp` 的
**线上字节**与**编排状态机**的退化"。每个变异都朝真实的危险退化去改，
并要求对应用例失败；抓不到的变异要么修测试，要么如实列入 UNDETECTABLE。

为什么这些变异值得单独钉
------------------------
widget.cpp 不含协议编解码，但它决定了三件直接影响互操作的事：
  1. 浮层的 accepted / hangupClicked 必须**逐字节**回 `accept\\n` / `recstop\\n`
     给**同一个连接** —— 改错信令、改错连接、少一个 '\\n' 都是静默失败；
  2. `unlock\\n` 必须广播给所有在线门口机；
  3. 退出程序时必须让门口机停推流（Widget 析构 -> MonitorClient::stop()）。
另外按钮槽靠 uic 的 connectSlotsByName 自动接线，灯控指令的**确切字节**
必须逐字节对得上，否则现场是"按了没反应"。

变异（全部是真实危险的退化）
  1.  电源键不再翻转 m_screenOff（第二次点还是黑屏）
  2.  主键不再切换灯光面板可见性（只能开不能关）
  3.  台灯键指令名 desk_round -> work_round（按错灯）
  4.  白光键指令名 desk -> wall（按错灯）
  5.  accept 回执被写成 recstop（门口机永远接不通）
  6.  recstop 回执被写成 accept（门口机永远挂不断）
  7.  handleCall 不记 m_callClient（回执发不出去）
  8.  handleCall 去掉"已存在则不重复弹窗"守卫（来电风暴）
  9.  handleCall 只在首次来电时记 m_callClient（第二通电话回执发错人）
  10. handleStopSend 不再关窗（门口机停推后浮层还挂着）
  11. ~Widget 不再关通话浮层（退出后残留顶层窗口）
  12. 开锁键不再广播 unlock
  13. onVideoFrameReady 丢掉 !m_cameraActive 门控（关掉监看后画面复活）
  14. onVideoFrameReady 丢掉 frame.isNull() 门控（空帧也弹画面）
  15. 离线状态下仍然响铃（playRing 恒真）
  16. 日期格式改掉（用户看到的日期变了）
  17. on_btngetframe_clicked 忽略 toggle 结果（状态机与 UI 不同步）
  18. handleCall 不再 show() 浮层（弹窗不出现）

对照（必须通过）
  C1. 只加无关注释
  C2. 改 qInfo 文案（不影响语义）

**故意不测的变异（如实记录限制）**
  - 去掉 `centerOnMain(m_callForm);`：没有任何断言检查浮层坐标，
    去掉后行为差异（位置不对）观测不到，故不列为变异。
  - 去掉 `m_cameraFirstShow = true;`：它只影响"下次是否重播动画"，
    测试断言的是可见性与 pixmap，对动画重播没有判别力。
  上面两条由本文件的 UNDETECTABLE 列表**反向**守住：一旦它们某天
  变得可观测（被用例抓到），说明测试或代码变了，那时应当把它提升为真变异。
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

# 标准输出固定 UTF-8：本机控制台可能是 GBK，脚本里的 ✓ 会抛 UnicodeEncodeError。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

if len(sys.argv) > 1:
    print("提示: 本脚本不需要参数，已忽略: %s" % " ".join(sys.argv[1:]))

_HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.dirname(_HERE)
SRC = os.path.join(D, 'src', 'ui', 'widget.cpp')
UI = os.path.join(D, 'src', 'ui', 'widget.ui')

CMAKE = shutil.which('cmake')
BUILD = os.path.join(tempfile.gettempdir(), 'fi_widget')
_EXE_SUFFIX = '.exe' if os.name == 'nt' else ''
EXE = os.path.join(BUILD, 'desktop_test_widget' + _EXE_SUFFIX)

ENV = dict(os.environ)
ENV['QT_QPA_PLATFORM'] = 'offscreen'

# ---------------------------------------------------------------------------
# 变异定义。所有锚点都必须**在真实文件里恰好出现一次**（main() 会自证）。
# ---------------------------------------------------------------------------
SEND_ACCEPT = ('            m_signaling->reply(m_callClient, '
               'accessterminal::protocol::Signal::Accept);')
SEND_RECSTOP = ('            m_signaling->reply(m_callClient, '
                'accessterminal::protocol::Signal::RecStop);')
CALL_CLIENT_BLOCK = ('    m_callClient = client;\n'
                     '\n'
                     '    if (m_callForm) {\n'
                     '        return; // 通话窗口已存在，不重复弹出\n'
                     '    }\n')
FORM_GUARD = ('    if (m_callForm) {\n'
              '        return; // 通话窗口已存在，不重复弹出\n'
              '    }\n')
FRAME_GUARD = '    if (frame.isNull() || !m_cameraActive) {\n'
DESTROY_AND_UI = '    destroyCallForm();\n    delete ui;\n'
CAMERA_TOGGLE = ('    m_cameraActive = m_monitor->toggle('
                 'AppConfig::instance().deviceIp());')

MUT = [
    # ---- 界面开关 ----
    ("电源键不再翻转 m_screenOff（第二次点仍黑屏）",
     '    m_screenOff = !m_screenOff;\n',
     ''),

    ("主键不再切换灯光面板可见性",
     '    ui->widget_light->setVisible(!ui->widget_light->isVisible());\n',
     '    ui->widget_light->setVisible(true);\n'),

    # ---- 灯控字节 ----
    ("台灯键指令名 desk_round -> work_round",
     'm_light->sendCommand(QStringLiteral("desk_round"));',
     'm_light->sendCommand(QStringLiteral("work_round"));'),

    ("白光键指令名 desk -> wall",
     '    m_light->sendCommand(QStringLiteral("desk"));\n',
     '    m_light->sendCommand(QStringLiteral("wall"));\n'),

    # ---- 信令回执字节 ----
    ("accept 回执被写成 recstop",
     SEND_ACCEPT,
     SEND_ACCEPT.replace('Signal::Accept', 'Signal::RecStop')),

    ("recstop 回执被写成 accept",
     SEND_RECSTOP,
     SEND_RECSTOP.replace('Signal::RecStop', 'Signal::Accept')),

    ("handleCall 不记 m_callClient（回执发不出去）",
     '    m_callClient = client;\n',
     ''),

    ("handleCall 去掉重复弹窗守卫",
     FORM_GUARD,
     ''),

    ("handleCall 只在首次来电时记 m_callClient（第二通回执发错人）",
     CALL_CLIENT_BLOCK,
     '    if (m_callForm) {\n'
     '        return; // 通话窗口已存在，不重复弹出\n'
     '    }\n'
     '    m_callClient = client;\n'),

    ("handleStopSend 不再关窗",
     'void Widget::handleStopSend()\n{\n    destroyCallForm();\n}',
     'void Widget::handleStopSend()\n{\n}'),

    ("~Widget 不再关通话浮层",
     DESTROY_AND_UI,
     '    delete ui;\n'),

    ("开锁键不再广播 unlock",
     '    const int sent = m_signaling->broadcast('
     'accessterminal::protocol::Signal::Unlock);\n',
     '    const int sent = 0;\n'),

    # ---- 监看门控 ----
    ("onVideoFrameReady 丢掉 !m_cameraActive 门控（关掉监看后画面复活）",
     FRAME_GUARD,
     '    if (frame.isNull()) {\n'),

    ("onVideoFrameReady 丢掉 frame.isNull() 门控（空帧也弹画面）",
     FRAME_GUARD,
     '    if (!m_cameraActive) {\n'),

    ("on_btngetframe_clicked 忽略 toggle 结果（状态机与 UI 不同步）",
     CAMERA_TOGGLE,
     '    m_monitor->toggle(AppConfig::instance().deviceIp());\n'
     '    m_cameraActive = true;'),

    # ---- 其余 ----
    ("离线状态下仍然响铃",
     '    const bool playRing = !ui->label_off->isVisible();\n',
     '    const bool playRing = true;\n'),

    ("日期格式改成 MM-dd-yyyy",
     'now.date().toString(QStringLiteral("yyyy-MM-dd"));',
     'now.date().toString(QStringLiteral("MM-dd-yyyy"));'),

    ("handleCall 不再 show() 浮层",
     '    m_callForm->show();\n',
     ''),
]

CONTROL = [
    ("C1 只加无关注释",
     'constexpr int kCameraAnimMs = 1000;',
     'constexpr int kCameraAnimMs = 1000; // C1 无关注释'),

    ("C2 改 qInfo 文案（不影响语义）",
     'qInfo() << "[开锁] unlock 已发送到" << sent << "台门口机";',
     'qInfo() << "[开锁] sent" << sent;'),
]

UNDETECTABLE = [
    ("浮层不再居中（centerOnMain）",
     '    centerOnMain(m_callForm);\n',
     ''),

    ("关掉监看后不重置首帧动画标志",
     '    m_cameraFirstShow = true;\n',
     ''),
]


def read_src():
    return io.open(SRC, encoding='utf-8', errors='replace').read()


_ORIG = read_src()


# ---------------------------------------------------------------------------
# 崩溃安全：本夹具**就地改写真实源码**再还原（src/ui/widget.cpp 就是工作区
# 里那个文件）。若还原只写在循环末尾，一旦中途抛异常（构建目录消失、
# Ctrl-C、断电），异常穿出循环，还原那行永远执行不到，**变异态被永久留在
# 工作区** —— 而工作区看起来完全正常，直到有人跑 tools/verify.py 才炸出
# 一条莫名其妙失败。详见 tools/verify_monitor_client_test.py 里同一段说明。
# ---------------------------------------------------------------------------
def restore_src():
    """把源码写回运行本夹具之前捕获的原始字节（幂等）。"""
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
            print('\n[崩溃安全][严重] 源码还原失败，工作区可能残留变异态: %r'
                  % (exc,))


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
    """解析 'Totals: X passed, Y failed'；返回 (passed, failed) 或 None。"""
    m = re.search(r'Totals:\s*(\d+) passed,\s*(\d+) failed', out)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def main():
    if not CMAKE:
        print('找不到 cmake，无法运行自检')
        return 2

    # 锚点唯一性自证：锚点必须恰好出现一次，否则变异会打偏。
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

    rb = build('desktop_test_widget')
    if rb.returncode != 0:
        print('基线构建失败:')
        print((rb.stdout + rb.stderr).decode('utf-8', 'replace')[-1500:])
        return 2

    rr = run_exe()
    base_out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
    base = totals(base_out)
    if base is None or base[1] != 0:
        print('基线就不干净（Totals=%r），自检无意义：' % (base,))
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
                print('  [夹具错误] %-52s 文件未变' % name)
                problems.append(name)
                io.open(SRC, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG)
                continue

            rb = build('desktop_test_widget')
            if rb.returncode != 0:
                print('  [构建失败] %-52s %s'
                      % (name, (rb.stdout + rb.stderr).decode(
                          'utf-8', 'replace')[-220:]))
                problems.append(name)
                io.open(SRC, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG)
                continue

            rr = run_exe()
            out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
            t = totals(out)
            fails = re.findall(r'^FAIL!\s*:\s*(\S+)', out, re.M)
            if t is None:
                print('  [夹具错误] %-52s 没有 Totals 行（崩溃？rc=%d）'
                      % (name, rr.returncode))
                problems.append(name)
            elif t[1] > 0:
                caught += 1
                print('  %-52s 抓到 ✓ (%d 条: %s)'
                      % (name, t[1], ', '.join(sorted(set(fails))[:3])))
            else:
                print('  *** %-52s 没抓到（全绿）' % name)
                problems.append(name)

            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG)

        print()
        print('--- 对照（必须全绿，不能误报）---')
        for item in CONTROL:
            name, old, new = item[0], item[1], item[2]
            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG.replace(old, new, 1))
            rb = build('desktop_test_widget')
            if rb.returncode != 0:
                print('  *** %-52s 构建失败（对照本身有问题）' % name)
                problems.append(name)
                io.open(SRC, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG)
                continue
            rr = run_exe()
            out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
            t = totals(out)
            if t is None or t[1] != 0:
                print('  *** %-52s 误报（Totals=%r）' % (name, t))
                problems.append(name)
            else:
                print('  %-52s 全绿 ✓' % name)
            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG)

        print()
        print('--- 已判定不可观测的退化（必须抓不到）---')
        for item in UNDETECTABLE:
            name, old, new = item[0], item[1], item[2]
            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG.replace(old, new, 1))
            rb = build('desktop_test_widget')
            if rb.returncode != 0:
                print('  *** %-52s 构建失败（不可再自称不可观测）' % name)
                problems.append(name)
                io.open(SRC, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG)
                continue
            rr = run_exe()
            out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
            t = totals(out)
            if t is not None and t[1] > 0:
                print('  *** %-52s 竟然被抓到了（%d 条 FAIL）—— 应提升为真变异'
                      % (name, t[1]))
                problems.append(name)
            else:
                print('  %-52s 确认抓不到 ✓（如实记录限制）' % name)
            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG)
    finally:
        io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)

    same = read_src() == _ORIG
    print()
    print('还原后重建并复核...')
    build('desktop_test_widget')
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
