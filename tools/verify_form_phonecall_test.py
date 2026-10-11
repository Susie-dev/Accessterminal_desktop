# -*- coding: utf-8 -*-
"""Form_phonecall 测试的故障注入自检（跨平台）。

用法：python3 tools/verify_form_phonecall_test.py [<仓库根>]
返回码 0 表示：每个危险退化都被抓到，对照未误报，且源码被逐字节还原。

要证明的核心命题
----------------
`tests/test_form_phonecall.cpp` 的价值全在"能不能抓到
`src/ui/form_phonecall.cpp` 的**交互状态机**与**会话生命周期**的退化"。
每个变异都朝真实的危险退化去改，并要求对应用例失败；抓不到的要么修测试，
要么如实列入 UNDETECTABLE。

为什么这些变异值得单独钉
------------------------
  - "拖到底才算接听"的阈值一旦写错，用户就**永远接不通**（或轻轻一碰就接通）；
  - `accepted` / `answered` 少发一个，`Widget` 就不会回 `accept\n`，
    门口机一直停在"呼叫中"；
  - 挂断按钮少发 `hangupClicked`，线上就不会有 `recstop\n`，门口机不断线；
  - 接通后不 `start()` / 关闭时不 `stop()`，socket 与声卡不释放；
  - `playRing=false` 时若仍建播放器，"离线不响铃"就成了摆设。

变异（全部是真实危险的退化）
  1.  engageCall 不发 accepted
  2.  engageCall 不发 answered
  3.  接通判定恒为假（拖到底也接不通）
  4.  未拖到底时不把滑块弹回起点
  5.  挂断按钮不发 hangupClicked
  6.  挂断按钮不关闭窗口
  7.  closeEvent 不 stop 通话通道
  8.  engageCall 不 start 通话通道
  9.  engageCall 根本不创建通话通道
  10. onVideoFrameReady 丢掉空帧门控
  11. onVideoFrameReady 不把画面设到 label_image
  12. 响铃不再循环（StoppedState 时不重播）
  13. playRing=false 时仍创建播放器（离线也响铃）
  14. 按下鼠标不进入拖拽态
  15. 接听阈值被放大到不可能达到

  ---- slidehintwidget.cpp（本目标也链接并覆盖了它）----
  16. 流光控件不再忽略鼠标事件（接听滑块会拖不动）
  17. 流光动画定时器不启动
  18. 流光位置不再推进（动画卡死）
  19. paintEvent 不再画流光

对照（必须通过）
  C1. 只加无关注释
  C2. 改 qDebug 文案（不影响语义）

**故意不测的变异（如实记录限制）**
  - 析构里不再显式 `stopRing()`：QMediaPlayer 是以 `this` 为父建的子对象，
    `~QObject` 仍会销毁它，"播放器被释放"这个可观测量不变，故不列为变异。
  - 析构里不再显式 `delete session;`：CallSession 同样是以 `this` 为父建的
    子对象（`new accessterminal::CallSession(this)`），`~QObject` 仍会销毁它，
    `destroyed` 计数与 `stopCalls` 都不变 —— 实测确认抓不到。那句 delete 只是
    让指针立刻置空，属防御性写法。
  - 不再设置流光引导控件 `hint` 的几何：没有任何断言涉及它，观测不到。
  上面几条由 UNDETECTABLE 列表**反向**守住：一旦它们某天变得可观测，
  说明测试或代码变了，那时应当把它提升为真变异。
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
SRC = os.path.join(D, 'src', 'ui', 'form_phonecall.cpp')
# 本测试目标也链接并覆盖 `slidehintwidget.cpp`（流光引导控件），
# 因此夹具要能对**两个**源文件做变异：变异条目可选第 4 个元素指定源文件。
HINT_SRC = os.path.join(D, 'src', 'ui', 'slidehintwidget.cpp')

CMAKE = shutil.which('cmake')
BUILD = os.path.join(tempfile.gettempdir(), 'fi_form_phonecall')
_EXE_SUFFIX = '.exe' if os.name == 'nt' else ''
EXE = os.path.join(BUILD, 'desktop_test_form_phonecall' + _EXE_SUFFIX)

ENV = dict(os.environ)
ENV['QT_QPA_PLATFORM'] = 'offscreen'

CREATE_SESSION_BLOCK = (
    '    if (!session) {\n'
    '        session = new accessterminal::CallSession(this);\n'
    '        connect(session, &accessterminal::CallSession::videoFrameReady,\n'
    '                this, &Form_phonecall::onVideoFrameReady);\n'
    '    }\n')
FRAME_GUARD = '    if (frame.isNull() || !ui->label_image) {\n'
DESTRUCTOR_TAIL = '    stopRing();\n    delete ui;\n'

MUT = [
    ("engageCall 不发 accepted",
     '    emit accepted();\n', ''),

    ("engageCall 不发 answered",
     '    emit answered();\n', ''),

    ("接通判定恒为假（拖到底也接不通）",
     '            if (ui->label_slider->x() > threshold) {',
     '            if (false) {'),

    ("未拖到底时不把滑块弹回起点",
     '                ui->label_slider->move(0, ui->label_slider->y());\n',
     ''),

    ("挂断按钮不发 hangupClicked",
     '        emit hangupClicked();\n', ''),

    ("挂断按钮不关闭窗口",
     '        close();\n', ''),

    ("closeEvent 不 stop 通话通道",
     '    if (session) {\n        session->stop();\n    }\n', ''),

    ("engageCall 不 start 通话通道",
     '    session->start();\n', ''),

    ("engageCall 根本不创建通话通道",
     CREATE_SESSION_BLOCK, ''),

    ("onVideoFrameReady 丢掉空帧门控",
     FRAME_GUARD,
     '    if (!ui->label_image) {\n'),

    ("onVideoFrameReady 不把画面设到 label_image",
     '    ui->label_image->setPixmap(pix.copy(targetRect));\n', ''),

    ("响铃不再循环（StoppedState 时不重播）",
     '                        ringPlayer->play();\n', ''),

    ("playRing=false 时仍创建播放器（离线也响铃）",
     '    if (playRing) {\n', '    if (true) {\n'),

    ("按下鼠标不进入拖拽态",
     '        dragging = true;\n', ''),

    ("接听阈值被放大到不可能达到",
     'ui->widget_slider_area->width() - ui->label_slider->width() - 10;',
     'ui->widget_slider_area->width() - ui->label_slider->width() + 1000;'),

    # ---- slidehintwidget.cpp（第 4 个元素指定另一份源文件）----
    ("流光控件不再忽略鼠标事件（接听滑块会拖不动）",
     '    setAttribute(Qt::WA_TransparentForMouseEvents, true); // 不拦截鼠标事件\n',
     '', HINT_SRC),

    ("流光动画定时器不启动",
     '    timer->start(10);\n', '', HINT_SRC),

    ("流光位置不再推进（动画卡死）",
     '        pos += 5; // 速度加快\n', '', HINT_SRC),

    ("paintEvent 不再画流光",
     '    p.drawRoundedRect(lightRect, lightRadius, lightRadius);\n', '', HINT_SRC),
]

CONTROL = [
    ("C1 只加无关注释",
     'const QSize btnSize(64, 64);',
     'const QSize btnSize(64, 64); // C1 无关注释'),

    ("C2 改 qDebug 文案（不影响语义）",
     'qDebug() << "[通话] 挂断按钮点击";',
     'qDebug() << "[通话] hangup clicked";'),
]

UNDETECTABLE = [
    ("析构不再显式 stopRing()（子对象仍会被 ~QObject 销毁）",
     DESTRUCTOR_TAIL,
     '    delete ui;\n'),

    ("析构不再显式 delete session（子对象仍会被 ~QObject 销毁）",
     '    delete session;\n', ''),

    ("不再设置流光引导控件的几何",
     '    hint->setGeometry(ui->widget_slider_area->rect());\n',
     ''),
]


def read_src(path=None):
    return io.open(path or SRC, encoding='utf-8', errors='replace').read()


_ORIGS = {SRC: read_src(SRC), HINT_SRC: read_src(HINT_SRC)}
# `_ORIG` / `SRC` 是"当前正在变异的那份文件"的原始内容与路径，循环里会重绑，
# 这样下面的循环体可以原样使用 read_src() / _ORIG，不必逐处判断文件。
_ORIG = _ORIGS[SRC]


def item_src(item):
    """变异条目可选第 4 个元素指定源文件；缺省是 form_phonecall.cpp。"""
    return item[3] if len(item) > 3 else SRC


# ---------------------------------------------------------------------------
# 崩溃安全：本夹具**就地改写真实源码**再还原。若还原只写在循环末尾，
# 一旦中途抛异常，异常会穿出循环，还原那行永远执行不到，**变异态被永久留在
# 工作区**。详见 tools/verify_monitor_client_test.py 里同一段说明。
# ---------------------------------------------------------------------------
def restore_src():
    for path, orig in _ORIGS.items():
        try:
            current = read_src(path)
        except Exception:
            continue
        if current != orig:
            try:
                io.open(path, 'w', encoding='utf-8',
                        newline='\n').write(orig)
                print('\n[崩溃安全] 已把 %s 还原为运行前的原始内容'
                      % os.path.relpath(path, D))
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
    m = re.search(r'Totals:\s*(\d+) passed,\s*(\d+) failed', out)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def main():
    # 循环里会重绑这两个全局量（用来切换到不同源文件），必须显式声明。
    global SRC, _ORIG

    if not CMAKE:
        print('找不到 cmake，无法运行自检')
        return 2

    for item in MUT + CONTROL + UNDETECTABLE:
        name, old = item[0], item[1]
        n = _ORIGS[item_src(item)].count(old)
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

    rb = build('desktop_test_form_phonecall')
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
            # 切到该变异所属的源文件（缺省 form_phonecall.cpp）。
            SRC = item_src(item)
            _ORIG = _ORIGS[SRC]
            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG.replace(old, new, 1))
            if read_src() == _ORIG:
                print('  [夹具错误] %-52s 文件未变' % name)
                problems.append(name)
                io.open(SRC, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG)
                continue
            rb = build('desktop_test_form_phonecall')
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
            # 切到该变异所属的源文件（缺省 form_phonecall.cpp）。
            SRC = item_src(item)
            _ORIG = _ORIGS[SRC]
            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG.replace(old, new, 1))
            rb = build('desktop_test_form_phonecall')
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
            # 切到该变异所属的源文件（缺省 form_phonecall.cpp）。
            SRC = item_src(item)
            _ORIG = _ORIGS[SRC]
            io.open(SRC, 'w', encoding='utf-8',
                    newline='\n').write(_ORIG.replace(old, new, 1))
            rb = build('desktop_test_form_phonecall')
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
        for _p, _o in _ORIGS.items():
            io.open(_p, 'w', encoding='utf-8', newline='\n').write(_o)

    same = all(read_src(p) == o for p, o in _ORIGS.items())
    print()
    print('还原后重建并复核...')
    build('desktop_test_form_phonecall')
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
