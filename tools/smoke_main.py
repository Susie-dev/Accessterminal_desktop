# -*- coding: utf-8 -*-
"""main.cpp 的进程级冒烟测试。

用法：python3 tools/smoke_main.py <可执行文件路径> [<可执行文件路径2> ...]

为什么只能用"从外面跑进程"的方式
--------------------------------
`src/main.cpp` 是整个工程里**唯一**无法被链接进测试二进制的产线 .cpp ——
它自己定义了 `main()`，链接进任何 QTest 目标都会撞名。所以它的装配顺序只能
从进程外面验。这里断言三件**会真实出错**、且此前没有任何断言看着的事：

  1. 用一份隔离配置启动后，日志里必须出现
     `[信令] 服务端监听端口 <我们指定的端口>`。
     若把 `AppConfig::load()` 挪到 `Widget widget;` **之后**，信令服务端就会绑到
     内置默认的 8887，这条立刻失败 —— 这正是 main.cpp 里那句注释
     "配置须在窗口与各模块构造之前载入"所守的东西。
  2. 启动后进程必须**仍然活着**（没有崩溃、也没有立刻退出）。
     去掉 `return app.exec();` 进程会立刻以 0 退出，这条会失败。
  3. 不带配置参数启动时，日志里必须出现"内置默认值"。
     覆盖 `argc > 1` 的默认分支，避免"只有传参那条路能跑"。

退出方式：确认后发 SIGTERM，并要求它不是被**崩溃信号**带走的
（returncode 不为负）。"被 SIGTERM 结束"在这里是正常收场。
"""
import io
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

if len(sys.argv) < 2:
    print("用法: python3 tools/smoke_main.py <可执行文件路径>")
    sys.exit(2)

APPS = [os.path.abspath(p) for p in sys.argv[1:]]

# 环境隔离：不继承开发机上可能残留的 ACCESSTERMINAL_* / SMARTSERVER_*，
# 保证被测行为只来自我们写的那份配置。
ENV = dict(os.environ)
for _k in list(ENV):
    if _k.startswith("ACCESSTERMINAL_") or _k.startswith("SMARTSERVER_"):
        del ENV[_k]
ENV["QT_QPA_PLATFORM"] = "offscreen"


def pick_free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def launch(app, args, logpath):
    log = io.open(logpath, "wb")
    proc = subprocess.Popen([app] + args, stdout=log, stderr=subprocess.STDOUT,
                            env=ENV, cwd=tempfile.gettempdir())
    return proc, log


def wait_for_marker(logpath, marker, timeout=15.0):
    """轮询日志文件，直到出现 marker 或超时。"""
    deadline = time.time() + timeout
    text = ""
    while time.time() < deadline:
        try:
            text = io.open(logpath, encoding="utf-8", errors="replace").read()
        except Exception:
            text = ""
        if marker in text:
            return True, text
        time.sleep(0.1)
    return False, text


def stop(proc):
    """发 SIGTERM 停止；返回 (returncode, 是否超时未退)。"""
    if proc.poll() is None:
        proc.terminate()
    try:
        return proc.wait(timeout=10), None
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait(timeout=10), "timeout"


def crashed(rc):
    """判断 returncode 是否意味着**疑似崩溃**。

    注意：本脚本是主动用 SIGTERM 结束被测进程的，所以 returncode == -SIGTERM
    是**正常收场**，不能当成崩溃（第一版就是这么误报的）。
    只有其它负返回码（SIGSEGV=11、SIGABRT=6、SIGKILL=9 ...）才算异常。
    """
    return rc is not None and rc < 0 and rc != -signal.SIGTERM


def main():
    failures = []

    tmpdir = tempfile.mkdtemp(prefix="acc_main_smoke_")
    port = pick_free_port()

    # ---- 场景 1：带隔离配置启动 ----
    cfg = os.path.join(tmpdir, "appconfig.json")
    io.open(cfg, "w", encoding="utf-8").write(
        '{\n'
        '  "network": {"self_ip": "127.0.0.1", "device_ip": "127.0.0.2",'
        ' "signaling_port": %d},\n'
        '  "hardware": {"serial_port": "/dev/null"},\n'
        '  "weather": {"url": ""},\n'
        '  "media": {"ringtone_volume": 0}\n'
        '}\n' % port)

    for app in APPS:
        label = "场景1 %s" % os.path.basename(app)
        logpath = os.path.join(tmpdir, "log1.txt")
        proc, log = launch(app, [cfg], logpath)
        ok, text = wait_for_marker(
            logpath, "服务端监听端口 %d" % port, timeout=20.0)
        if not ok:
            # 退一步给出更有用的诊断
            if "服务端监听端口" in text:
                m = re.search(r"服务端监听端口\s*(\d+)", text)
                failures.append(
                    "%s: 监听的端口是 %s，不是配置里的 %d —— "
                    "AppConfig::load() 很可能被挪到了 Widget/模块构造之后"
                    % (label, m.group(1) if m else "?", port))
            else:
                failures.append("%s: 启动 20 秒内没有出现监听日志；输出:\n%s"
                                % (label, text[-1200:]))
        elif proc.poll() is not None:
            failures.append("%s: 进程启动后立刻退出（rc=%s）—— "
                            "是不是没有走到 app.exec()？输出:\n%s"
                            % (label, proc.returncode, text[-800:]))
        else:
            print("  %-34s 已在配置端口 %d 上监听，且进程存活 ✓"
                  % (label, port))
        rc, why = stop(proc)
        log.close()
        if why == "timeout":
            failures.append("%s: SIGTERM 后 10 秒仍未退出" % label)
        elif crashed(rc):
            failures.append("%s: 被信号 %d 杀死（疑似崩溃）" % (label, -rc))

    # ---- 场景 2：不带参数启动（默认配置分支）----
    for app in APPS:
        label = "场景2 %s" % os.path.basename(app)
        logpath = os.path.join(tmpdir, "log2.txt")
        proc, log = launch(app, [], logpath)
        ok, text = wait_for_marker(logpath, "内置默认值", timeout=20.0)
        if not ok:
            failures.append("%s: 不带参数启动时未走默认配置分支；输出:\n%s"
                            % (label, text[-1200:]))
        elif proc.poll() is not None:
            failures.append("%s: 进程启动后立刻退出（rc=%s）"
                            % (label, proc.returncode))
        else:
            print("  %-34s 走了内置默认值分支，且进程存活 ✓" % label)
        rc, why = stop(proc)
        log.close()
        if why == "timeout":
            failures.append("%s: SIGTERM 后 10 秒仍未退出" % label)
        elif crashed(rc):
            failures.append("%s: 被信号 %d 杀死（疑似崩溃）" % (label, -rc))

    print()
    if failures:
        print("main.cpp 冒烟测试失败 %d 项：" % len(failures))
        for f in failures:
            print("  - %s" % f)
        return 1
    print("main.cpp 冒烟测试全部通过（装配顺序 + 存活 + 默认配置分支）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
