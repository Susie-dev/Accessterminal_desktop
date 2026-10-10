#!/usr/bin/env python3
"""
静态一致性校验：在没有编译器/Qt 的环境下，尽可能发现重构引入的机械性错误。

检查项：
  1. 所有本地 #include "..." 都能解析到实际文件（含 src/ 为根的搜索路径）
  2. CMakeLists.txt / .pro 的源文件列表与实际文件一一对应（无遗漏、无幽灵文件）
  3. res.qrc 引用的资源全部存在
  4. .ui 文件的 objectName 与代码中 ui->xxx 的引用一致
  5. 每个 .ui 都能被 Qt 的 uic 规则覆盖（列在 FORMS/APP_FORMS 中）
  6. 括号/花括号/引号粗平衡
  7. 检测重构前的旧标识符残留

用法：python verify.py <项目根目录>
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

FAIL = []
WARN = []


def fail(msg):
    FAIL.append(msg)


def warn(msg):
    WARN.append(msg)


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def find_files(root, exts):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 跳过构建目录与版本库
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "build", "build-t113", "docs", "deploy")]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in exts:
                out.append(os.path.join(dirpath, fn))
    return out


def check_includes(root, src_root):
    """
    本地 #include 必须可解析：相对当前文件目录，或相对 src/ 根。
    ui_*.h 由 Qt 的 uic 在构建时生成，源码树中不存在，属正常情况。
    """
    pattern = re.compile(r'^\s*#include\s+"([^"]+)"', re.M)
    for path in find_files(src_root, {".cpp", ".h", ".hpp"}):
        text = read(path)
        base = os.path.dirname(path)
        for inc in pattern.findall(text):
            # uic/moc 生成物，构建期才出现
            if os.path.basename(inc).startswith(("ui_", "moc_", "qrc_")):
                continue
            cand = [os.path.join(base, inc), os.path.join(src_root, inc)]
            if not any(os.path.isfile(c) for c in cand):
                fail(f"[include] {os.path.relpath(path, root)} -> 无法解析 \"{inc}\"")


def check_build_lists(root, src_root):
    """CMake/pro 里列出的源文件必须存在；实际源文件必须被列出。"""
    cmake = os.path.join(root, "CMakeLists.txt")
    pro = os.path.join(root, "smartpro.pro")

    listed = set()
    if os.path.isfile(cmake):
        text = read(cmake)
        for m in re.finditer(r"^\s*(src/[\w/]+\.(?:cpp|h|ui|qrc))\s*$", text, re.M):
            listed.add(m.group(1).replace("/", os.sep))
        for m in re.finditer(r"^\s*(src/[\w/]+\.(?:cpp|h|ui|qrc))", text, re.M):
            listed.add(m.group(1).replace("/", os.sep))
    if os.path.isfile(pro):
        text = read(pro)
        for m in re.finditer(r"^\s*(src/[\w/]+\.(?:cpp|h|ui|qrc))\s*\\?$", text, re.M):
            listed.add(m.group(1).replace("/", os.sep))

    normalized = set()
    for item in listed:
        normalized.add(os.path.normpath(item))

    # 实际存在的、应当被列出的源文件
    actual = set()
    for path in find_files(src_root, {".cpp", ".h", ".ui", ".qrc"}):
        rel = os.path.relpath(path, root)
        normalized_rel = os.path.normpath(rel)
        actual.add(normalized_rel)

    missing_in_build = sorted(a for a in actual if a not in normalized)
    ghost = sorted(n for n in normalized if not os.path.isfile(os.path.join(root, n)))

    for m in missing_in_build:
        fail(f"[build] 源文件未列入构建脚本: {m}")
    for g in ghost:
        fail(f"[build] 构建脚本列出了不存在的文件: {g}")


def check_qrc(root, src_root):
    """res.qrc 引用的资源必须实际存在（相对 qrc 所在目录）。"""
    for qrc in find_files(src_root, {".qrc"}):
        base = os.path.dirname(qrc)
        text = read(qrc)
        for ref in re.findall(r"<file>([^<]+)</file>", text):
            ref = ref.strip()
            target = os.path.join(base, ref.replace("/", os.sep))
            if not os.path.isfile(target):
                fail(f"[qrc] {os.path.relpath(qrc, root)} 引用缺失资源: {ref}")


def check_ui_objectnames(root, src_root):
    """代码中的 ui->xxx 必须在对应 .ui 的 objectName 中定义。"""
    ui_files = find_files(src_root, {".ui"})
    for uipath in ui_files:
        try:
            tree = ET.parse(uipath)
        except ET.ParseError as e:
            fail(f"[ui] XML 解析失败 {os.path.relpath(uipath, root)}: {e}")
            continue

        names = set()
        for el in tree.iter():
            n = el.get("name")
            if n:
                names.add(n)

        stem = os.path.splitext(os.path.basename(uipath))[0]
        # 找到引用该 ui 的 cpp（同目录同名，或 include "ui_xxx.h"）
        for cpp in find_files(src_root, {".cpp"}):
            text = read(cpp)
            if f"ui_{stem}.h" not in text and os.path.splitext(os.path.basename(cpp))[0] != stem:
                continue
            # 仅在确实使用 Ui::<Stem> 时校验
            if f"Ui::{stem}" not in text and "setupUi" not in text:
                continue
            used = set(re.findall(r"\bui->([A-Za-z_]\w*)", text))
            # setupUi/retranslateUi 是 uic 生成的方法，不是控件
            used -= {"setupUi", "retranslateUi"}
            unknown = sorted(u for u in used if u not in names)
            for u in unknown:
                fail(f"[ui] {os.path.relpath(cpp, root)} 引用了 "
                     f"{os.path.basename(uipath)} 中不存在的控件: ui->{u}")


def check_balance(root, src_root):
    """粗粒度符号平衡（忽略字符串与注释会过度复杂，这里只做整体计数）。"""
    for path in find_files(src_root, {".cpp", ".h"}):
        text = read(path)
        # 去掉行注释与字符串字面量，减少误报
        stripped = re.sub(r"//[^\n]*", "", text)
        stripped = re.sub(r'"(?:\\.|[^"\\])*"', '""', stripped)
        stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.S)
        for op, cl, label in (("{", "}", "花括号"), ("(", ")", "圆括号")):
            a, b = stripped.count(op), stripped.count(cl)
            if a != b:
                fail(f"[balance] {os.path.relpath(path, root)} {label}不平衡: {op}={a} {cl}={b}")


def strip_comments_and_strings(text):
    """
    去掉注释与字符串字面量，避免把注释里的示例当作真实代码。
    先处理块注释与字符串，最后处理行注释，避免相互干扰。
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    text = re.sub(r"'(?:\\.|[^'\\])*'", "''", text)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def check_legacy_identifiers(root, src_root):
    """重构后的源码不应再出现旧路径/旧标识符（忽略注释与字符串）。"""
    legacy = [
        (r'/home/meetyoo', "旧开发机绝对路径"),
        (r'camera/v4l2camera\.h', "旧 include 路径"),
        (r'camera_udp_server\.h', "旧 include 路径"),
        (r'camera_push_thread\.h', "旧 include 路径"),
        (r'#include\s+"appconfig\.h"', "旧配置头 appconfig.h"),
        (r'#include\s+"HailinFingerprint\.h"', "旧头文件名"),
        (r'QString::SkipEmptyParts', "Qt5-only API（应为 Qt::SkipEmptyParts）"),
        (r'QVector<[^>]+>::fromStdVector', "Qt6 已移除的 API"),
        (r'getFingerprint\(\)', "旧 Widget 访问器"),
        (r'getNextFingerId\(\)', "旧 Widget 访问器"),
    ]
    for path in find_files(src_root, {".cpp", ".h", ".pro"}):
        raw = read(path)
        text = strip_comments_and_strings(raw) if not path.endswith(".pro") else raw
        for pat, desc in legacy:
            if re.search(pat, text):
                fail(f"[legacy] {os.path.relpath(path, root)} 仍含{desc}: {pat}")


def check_qt5_portability(root, src_root):
    """
    Qt5 版本可移植性检查。

    目标 SDK（Tina Linux）常见为 Qt 5.9~5.12，而开发机可能是 5.15。
    仅在新版本存在的 API 会让交叉编译在旧 SDK 上失败，这里静态拦截。
    """
    # 这些符号在 Qt 5.15 才引入，旧 SDK 上不存在。
    too_new = [
        (r'\bQAbstractSocket::errorOccurred\b',
         "QAbstractSocket::errorOccurred 需要 Qt 5.15+，"
         "旧写法 QOverload<QAbstractSocket::SocketError>::of(&QTcpSocket::error)"),
        (r'\bQTcpSocket::errorOccurred\b',
         "QTcpSocket::errorOccurred 需要 Qt 5.15+，请改用 QOverload 取 error 重载"),
        (r'\bQNetworkReply::errorOccurred\b',
         "QNetworkReply::errorOccurred 需要 Qt 5.15+"),
        (r'\bQSerialPort::errorOccurred\b',
         "QSerialPort::errorOccurred 需要 Qt 5.15+，请改用 QOverload 取 error 重载"),
        (r'\bQProcess::errorOccurred\b',
         "QProcess::errorOccurred 需要 Qt 5.15+"),
        (r'\bQStringView\b', "QStringView 需要 Qt 5.10+，旧 SDK 可能没有"),
        (r'\bQMetaType::fromType\b', "QMetaType::fromType 需要 Qt 6"),
        (r'\bQAudioSink\b|\bQAudioSource\b', "QAudioSink/QAudioSource 是 Qt 6 API，Qt5 用 QAudioOutput/QAudioInput"),
        (r'\bQMediaPlayer::PlaybackState\b', "QMediaPlayer::PlaybackState 是 Qt 6 API，Qt5 用 QMediaPlayer::State"),
        # Qt6 用 setSource(QUrl)，Qt5 是 setMedia(QMediaContent)；
        # 实际写法通常是 player->setSource(...)，故匹配成员调用形式。
        (r'(?:->|\.)setSource\s*\(', "QMediaPlayer::setSource 是 Qt 6 API，Qt5 用 setMedia"),
        (r'\bQLibraryInfo::path\b', "QLibraryInfo::path 是 Qt 6 API，Qt5 用 QLibraryInfo::location"),
        (r'\bQColorSpace\b', "QColorSpace 需要 Qt 5.14+"),
    ]
    # C++14/17 特性：本工程为 C++11
    cpp_too_new = [
        (r'^\s*inline\s+(?:constexpr|const)\s', "C++17 inline 变量"),
        (r'\bif\s+constexpr\b', "C++17 if constexpr"),
        # 结构化绑定形如 auto [a, b] = ...；必须带声明关键字，
        # 否则会把 lambda 捕获列表 [this, conn](...) 误判。
        (r'\b(?:const\s+)?auto\s*(?:&|&&)?\s*\[[^\]\n]+\]\s*[=(]',
         "C++17 结构化绑定"),
        (r'\bstd::optional\b', "C++17 std::optional"),
        (r'\bstd::string_view\b', "C++17 std::string_view"),
        (r'\bstd::make_unique\b', "C++14 std::make_unique"),
        (r'\bstd::filesystem\b', "C++17 std::filesystem"),
    ]

    for path in find_files(src_root, {".cpp", ".h"}):
        raw = read(path)
        text = strip_comments_and_strings(raw)
        rel = os.path.relpath(path, root)
        for pat, desc in too_new:
            if re.search(pat, text):
                fail(f"[qt5] {rel} 使用了过高版本的 Qt API: {desc}")
        for pat, desc in cpp_too_new:
            if re.search(pat, text, re.M):
                fail(f"[cxx11] {rel} 使用了 {desc}，本工程为 C++11")


def check_forward_declarations(root, src_root):
    """
    前置声明一致性检查。

    背景（真实缺陷，曾在 T113 侧出现）：重构后 widget.h 里前置声明的
    类名与工程实际定义的类名不一致（如声明 VideoPushThread，实际定义
    CameraPushThread）。前置声明本身不报错，直到 .cpp 里 new/调用成员
    才报 "invalid use of incomplete type"，报错位置离根因很远，容易被
    误判成缺少 include。这里提前静态拦截。
    """
    candidates = {}
    for path in find_files(src_root, {".h", ".cpp"}):
        text = strip_comments_and_strings(read(path))
        for m in re.finditer(r'^\s*class\s+([A-Za-z_]\w*)\s*;', text, re.M):
            name = m.group(1)
            if re.search(r'\b(?:class|struct)\s+' + re.escape(name) +
                         r'\b[^;{]*\{', text):
                continue
            candidates.setdefault(name, []).append(os.path.relpath(path, root))

    defined = set()
    for path in find_files(src_root, {".h", ".cpp"}):
        text = strip_comments_and_strings(read(path))
        for m in re.finditer(r'\b(?:class|struct)\s+([A-Za-z_]\w*)\b\s*(?::[^;{]*)?\{',
                             text):
            defined.add(m.group(1))

    for name, where in sorted(candidates.items()):
        if name in defined:
            continue
        if name.startswith('Q') or name.startswith('Ui') or name in (
                'timeval', 'sockaddr', 'sockaddr_in'):
            continue
        fail("[fwd] {} 前置声明了未在本工程定义的类型 '{}'；"
             "若这是一个真实使用的成员类型，编译期会报 incomplete type"
             .format(', '.join(sorted(set(where))), name))


def check_json_configs(root):
    """配置文件必须是合法 JSON，且字段类型正确。"""
    import json
    for name in ("config/appconfig.json",):
        path = os.path.join(root, name.replace("/", os.sep))
        if not os.path.isfile(path):
            fail(f"[json] 缺少配置文件: {name}")
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            fail(f"[json] {name} 解析失败: {e}")
            continue
        # 关键字段的类型校验
        checks = [
            (("network", "self_ip"), str),
            (("network", "device_ip"), str),
            (("network", "signaling_port"), int),
            (("hardware", "serial_port"), str),
            (("media", "ringtone"), str),
            (("lights", "desk"), str),
        ]
        for keys, typ in checks:
            node = data
            ok = True
            for k in keys:
                if not isinstance(node, dict) or k not in node:
                    ok = False
                    break
                node = node[k]
            if not ok:
                fail(f"[json] {name} 缺少字段: {'.'.join(keys)}")
            elif not isinstance(node, typ):
                fail(f"[json] {name} 字段 {'.'.join(keys)} 类型应为 {typ.__name__}，"
                     f"实为 {type(node).__name__}")


def check_media_gated_by_answer(root, src_root):
    """
    “音视频通道只在用户接听后建立”这一约定的结构化守卫。

    背景：这是与门口机“accept 之前不建流”对称的一条硬约束。室内机在
    收到 call 时只弹出来电窗口并响铃，**不得**提前绑定 UDP 12345/23456
    或打开声卡；只有用户把滑块拖到底（engageCall()）才建立通道。

    baseline 中对应的是 Form_phonecall::startAV()，它的唯一调用点是滑块
    释放处理函数；重构后对应 CallSession::start()，唯一调用点应为
    Form_phonecall::engageCall()。

    一旦有人把 session->start() 挪到构造函数或 handleCall()，功能上看起来
    仍然能用（甚至“接听更快”），但空闲时会常驻占用音频设备与 UDP 端口，
    且没有测试会报警。这里把它变成可强制的检查。
    """
    form = os.path.join(src_root, "ui", "form_phonecall.cpp")
    if not os.path.isfile(form):
        return
    text = strip_comments_and_strings(read(form))
    rel = os.path.relpath(form, root)

    sites = [m.start() for m in re.finditer(r'\bsession\s*->\s*start\s*\(\s*\)', text)]
    if not sites:
        fail("[media-gate] {} 找不到 session->start() 调用；"
             "接听后应建立音视频通道，否则通话无画面无声音".format(rel))
        return

    # 定位 engageCall() 的函数体范围
    m = re.search(r'\bForm_phonecall\s*::\s*engageCall\s*\([^)]*\)\s*\{', text)
    if not m:
        fail("[media-gate] {} 找不到 Form_phonecall::engageCall() 的定义；"
             "它是音视频通道唯一的建立入口".format(rel))
        return
    start = text.index('{', m.end() - 1)
    depth = 0
    i = start
    while i < len(text):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                break
        i += 1
    if depth != 0:
        fail("[media-gate] {} engageCall() 花括号不配平，无法分析".format(rel))
        return

    for pos in sites:
        if not (start <= pos <= i):
            fail("[media-gate] {}:{} session->start() 位于 engageCall() 之外；"
                 "音视频通道只允许在用户接听后建立，否则空闲时占用声卡与 UDP 端口"
                 .format(rel, text.count("\n", 0, pos) + 1))


def check_unqueued_poll_timers(root, src_root):
    """
    轮询定时器不得以「无句柄」的局部变量创建。

    背景（真实缺陷，来自 baseline，已修复）：Form_finger::startFingerRegisterStep()
    里写的是

        QTimer* timer = new QTimer(this);      // 局部变量，没有任何成员保存它
        connect(timer, &QTimer::timeout, this, [=]{ ... });
        timer->start(500);

    这个轮询回调里做的是**阻塞串口读**且跑在 GUI 线程。只有“检测到手指”
    那一条路径会 stop 它；用户点『退出』（onAddQuitClicked 只调 close()）时
    定时器仍在跑。由于 Form_finger 没有设 WA_DeleteOnClose，close() 只是隐藏
    窗口、对象还活着，于是：每 500ms 在 GUI 线程上阻塞一次，界面永久卡顿。

    判定规则只针对「可被 close() 隐藏、但对象仍存活」的窗口类：
      - 该类必须继承 QWidget，并且代码里出现 close() 调用；
      - 该 QTimer 在创建后调用了 start(...)（成为周期定时器）；
      - 其句柄既不是类成员，也没有放进任何容器。
    此时除回调自身外无人能停止它，而窗口已经隐藏 —— 定时器会永久空转。

    为什么把范围收窄到 QWidget：像 FingerprintManager 这样随程序存活的
    QObject，其“等待手指”轮询本来就是设计上的常驻行为（识别流程结束时
    才 stop），并非缺陷。只有「承载它的界面可能先消失」时才构成问题。
    单次触发（singleShot / setSingleShot(true)）也会自己结束，不在范围内。
    """
    for path in find_files(src_root, {".cpp"}):
        text = strip_comments_and_strings(read(path))
        rel = os.path.relpath(path, root)
        if "new QTimer" not in text:
            continue

        header = path[:-4] + ".h"
        if not os.path.isfile(header):
            continue
        htext = strip_comments_and_strings(read(header))

        # 只处理 QWidget 子类，且该文件里确实会 close()（说明能被隐藏而非销毁）
        if not re.search(r'class\s+\w+\s*:\s*public\s+QWidget\b', htext):
            continue
        if not re.search(r'\bclose\s*\(\s*\)', text):
            continue

        # 头文件里的成员变量名
        members = set(re.findall(r'\b(m_\w+)\s*(?:=|;)', htext))

        for m in re.finditer(r'\bQTimer\s*\*\s*(\w+)\s*=\s*new\s+QTimer\b', text):
            var = m.group(1)
            # 只关心“使能了周期性启动”的定时器
            if not re.search(re.escape(var) + r'\s*->\s*start\s*\(', text):
                continue
            if var in members:
                continue  # 有成员句柄，外部可停
            # 句柄是否被放进了某个容器（QList/QVector/append/<<）
            if re.search(r'\b\w+\s*(?:\.append|<<)\s*\(\s*' + re.escape(var), text):
                continue
            line = text.count("\n", 0, m.start()) + 1
            fail("[unguarded-timer] {}:{} 窗口类里的局部定时器 '{}' 被 start() 成"
                 "周期定时器却没有任何成员/容器保存句柄；除回调自身外无人能停止它。"
                 "该类会 close()（窗口被隐藏但对象仍存活，未设 WA_DeleteOnClose 时"
                 "尤其如此），定时器会在 GUI 线程上永久空转。"
                 "请改为成员变量并提供停止入口。"
                 .format(rel, line, var))


def check_deleted_on_close_members(root, src_root):
    """
    WA_DeleteOnClose 窗口不得用裸指针成员跟踪。

    背景（真实缺陷，本轮由重构引入并修复）：on_btnpsswd_clicked() 创建
    Form_passwd 并设 Qt::WA_DeleteOnClose，然后把裸指针存进成员
    m_passwdForm。该窗口在用户点“确定”或直接关闭时会被 Qt 自动销毁，
    m_passwdForm 立刻成为悬垂指针；而 PasswordManager::passwordChecked
    的回调里还会 `if (m_passwdForm) m_passwdForm->close();` ——
    对已释放对象调用成员函数，use-after-free。

    这类缺陷静态上很好识别：凡是在某处 `setAttribute(Qt::WA_DeleteOnClose)`
    的对象，若其句柄被赋给「裸指针类型的成员」，就需要改造成 QPointer
    （对象销毁后自动变空）。

    注意 baseline 里这段恰好不触发：原代码写的是
        Form_passwd* passwdForm = new Form_passwd(this);
    声明了同名【局部变量】遮蔽成员，成员永远为 nullptr，所以不会悬垂，
    但代价是“密码正确后窗口不会关闭”。重构把局部改为成员时修掉了那个
    功能缺陷，却引入了悬垂——这正是本检查要防住的回归。
    """
    for path in find_files(src_root, {".cpp"}):
        text = strip_comments_and_strings(read(path))
        rel = os.path.relpath(path, root)
        if "WA_DeleteOnClose" not in text:
            continue

        # 收集「被设置了 WA_DeleteOnClose 的变量名」
        marked = set()
        for m in re.finditer(r'(\w+)\s*->\s*setAttribute\s*\(\s*'
                             r'(?:Qt::)?WA_DeleteOnClose', text):
            marked.add(m.group(1))
        # 形如 setAttribute(Qt::WA_DeleteOnClose) 的隐式 this 用法不涉及成员名

        if not marked:
            continue

        # 在头文件里找裸指针类型的成员声明
        header = path[:-4] + ".h"
        if not os.path.isfile(header):
            continue
        htext = strip_comments_and_strings(read(header))
        # 形如:  Form_passwd* m_passwdForm = nullptr;
        #        Form_passwd *m_passwdForm;
        raw_members = {}
        for m in re.finditer(r'^\s*(?:[\w:]+)\s*\*\s*(m_\w+)\s*(?:=[^;]*)?;',
                             htext, re.M):
            raw_members[m.group(1)] = m.group(0).strip()

        for var in marked:
            # 该变量是否被赋给了某个裸指针成员
            # 形如  m_xxx = var;   或   m_xxx = new ...（new 形式也查）
            for mm in re.finditer(r'\b(m_\w+)\s*=\s*' + re.escape(var) + r'\s*;',
                                  text):
                member = mm.group(1)
                if member in raw_members:
                    line = text.count("\n", 0, mm.start()) + 1
                    fail("[dtor-close] {}:{} 把设了 WA_DeleteOnClose 的 '{}' 存入"
                         "裸指针成员 '{}'（{}）；该窗口关闭时会被 Qt 自动销毁，"
                         "成员随即悬垂。请改用 QPointer<...>。"
                         .format(rel, line, var, member,
                                 raw_members[member]))


def main():
    if len(sys.argv) < 2:
        print("用法: python verify.py <项目根目录>")
        return 2
    root = os.path.abspath(sys.argv[1])
    src_root = os.path.join(root, "src")
    if not os.path.isdir(src_root):
        print(f"找不到 src 目录: {src_root}")
        return 2

    check_includes(root, src_root)
    check_build_lists(root, src_root)
    check_qrc(root, src_root)
    check_ui_objectnames(root, src_root)
    check_balance(root, src_root)
    check_legacy_identifiers(root, src_root)
    check_qt5_portability(root, src_root)
    check_forward_declarations(root, src_root)
    check_media_gated_by_answer(root, src_root)
    check_deleted_on_close_members(root, src_root)
    check_unqueued_poll_timers(root, src_root)
    check_json_configs(root)

    print(f"校验目录: {root}")
    print("=" * 70)
    if WARN:
        print(f"\n警告 {len(WARN)} 项：")
        for w in WARN:
            print("  ! " + w)
    if FAIL:
        print(f"\n失败 {len(FAIL)} 项：")
        for f in FAIL:
            print("  X " + f)
        print(f"\n结论: 存在 {len(FAIL)} 项问题")
        return 1
    print("\n结论: 全部检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
