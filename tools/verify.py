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


def check_subproject_cmake_is_selfcontained(root, src_root):
    """
    可独立构建的子工程 CMakeLists.txt（tests/、tests/interop/ 等）必须自带
    `cmake_minimum_required` / `project()`，并有 `enable_testing()` 与
    `CMAKE_AUTOMOC`（当测试文件 `#include "*.moc"` 时）。

    背景（真实缺陷，本轮修复）：
    `tests/CMakeLists.txt` 的文件头一直写着可以独立构建：

        cmake -S tests -B /tmp/t113-tests && cmake --build ... && ctest ...

    但它只有 `find_package` + `add_executable` + `add_test`，这三样原本由主
    CMakeLists.txt 提供。于是独立构建实际上**从来没有成功过**，且失败方式
    很有迷惑性：

      1. 缺 cmake_minimum_required -> 配置阶段直接失败
         "No cmake_minimum_required command is present"
      2. 缺 project() -> 同上（CMake 要求脚本模式之外必须有 project）
      3. 缺 enable_testing() -> **配置和构建都成功**，但 ctest 报
         "No tests were found!!!" —— 看起来构建通过了，实际一个用例都没跑
      4. 缺 AUTOMOC -> 测试文件末尾 `#include "test_xxx.moc"` 找不到

    第 3 种尤其危险：CI 里若只看构建退出码，会以为测试通过了。
    而"独立构建"恰恰是没有 ALSA/libgpiod 的开发机上唯一能跑单元测试的用法
    （主工程根 CMakeLists 需要 ALSA，开发机通常没有）。

    判定：子目录里的 CMakeLists.txt（排除顶层那一个）若含 add_test/add_executable
    却没有 cmake_minimum_required 或 project -> 报错；
    若含 add_test 却没有 enable_testing -> 报错；
    若同目录下的 .cpp 里出现 `#include "*.moc"` 却没有 AUTOMOC -> 报错。
    """
    top = os.path.join(root, "CMakeLists.txt")
    for dp, dns, fns in os.walk(root):
        if ".git" in dp.split(os.sep) or "build" in dp.split(os.sep):
            continue
        if "CMakeLists.txt" not in fns:
            continue
        p = os.path.join(dp, "CMakeLists.txt")
        if os.path.normpath(p) == os.path.normpath(top):
            continue  # 顶层工程由主 CMakeLists 负责
        rel = os.path.relpath(p, root)
        text = read(p)
        if "add_test" not in text and "add_executable" not in text:
            continue

        if not re.search(r"^\s*cmake_minimum_required\s*\(", text, re.M):
            fail("[cmake-selfcontained] {} 含 add_executable/add_test 却没有 "
                 "cmake_minimum_required()：独立执行 `cmake -S {}` 会直接报 "
                 "\"No cmake_minimum_required command is present\" 而无法配置。"
                 .format(rel, os.path.dirname(rel) or "."))
        if not re.search(r"^\s*project\s*\(", text, re.M):
            fail("[cmake-selfcontained] {} 缺少 project()：独立构建时 CMake 要求"
                 "顶层脚本必须有 project()，否则配置失败。".format(rel))
        if "add_test" in text and not re.search(
                r"^\s*enable_testing\s*\(", text, re.M):
            fail("[cmake-selfcontained] {} 注册了 add_test 却没有 "
                 "enable_testing()：独立构建会**配置成功、构建成功**，但 ctest "
                 "报 \"No tests were found!!!\" —— 一个用例都不会执行，"
                 "只看构建退出码会误判为通过。".format(rel))
        # 同目录 .cpp 里有 #include "*.moc" 就必须开 AUTOMOC
        has_moc_include = False
        for f in fns:
            if not f.endswith(".cpp"):
                continue
            if re.search(r'#include\s+"[\w]+\.moc"', read(os.path.join(dp, f))):
                has_moc_include = True
                break
        if has_moc_include and not re.search(r"AUTOMOC\s+ON", text):
            fail("[cmake-selfcontained] {} 同目录的测试文件里有 "
                 "#include \"*.moc\"，却没有 set(CMAKE_AUTOMOC ON)：会报 "
                 "fatal error: test_xxx.moc: No such file or directory。"
                 .format(rel))

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
            raw = read(cpp)
            if f"ui_{stem}.h" not in raw and os.path.splitext(os.path.basename(cpp))[0] != stem:
                continue
            # 仅在确实使用 Ui::<Stem> 时校验
            if f"Ui::{stem}" not in raw and "setupUi" not in raw:
                continue
            # 只看真实代码：注释/字符串里的 `ui->xxx`（例如说明文字、被注释掉的
            # 旧代码）不是对控件的引用，否则会产生误报。
            text = strip_comments_and_strings(raw)
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

    注意：被删除的片段若跨多行，必须**保留其中的换行符**，否则删除后的文本
    行号会整体前移，所有基于 `text.count("\\n", 0, pos)` 的报错行号都会指向
    错误位置。这里对块注释保留换行、其余字符换成空格；对字符串/字符字面量
    保留首尾定界符与换行，仅清空内容（与既有行为一致）。
    """
    def blank_keep_newlines(m):
        return re.sub(r"[^\n]", " ", m.group(0))

    def empty_string_keep_newlines(m):
        s = m.group(0)
        # 保留首尾定界符与内部换行，其余内容清空（与把字符串替换为 "" 等效）。
        return s[0] + re.sub(r"[^\n]", "", s[1:-1]) + s[-1]

    text = re.sub(r"/\*.*?\*/", blank_keep_newlines, text, flags=re.S)
    text = re.sub(r'"(?:\\.|[^"\\])*"', empty_string_keep_newlines, text)
    text = re.sub(r"'(?:\\.|[^'\\])*'", empty_string_keep_newlines, text)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def split_top_level_args(call):
    """
    按**顶层逗号**切分一个调用/参数列表文本，返回实参列表。

    为什么需要它：`connect()` 的实参里经常出现 `->` 与 `>`，
    `ui->addface, &QPushButton::clicked, this, &Cls::S`。

    一个常见的错误写法是把 `>` 也当成"需要配对的括号"：

        if ch in "(<[": depth += 1
        elif ch in ")>]": depth -= 1        # 错！`->` 里的 `>` 会误减

    这样每遇到一个 `->`，depth 就偏负一次，于是**顶层逗号再也分不出来**，
    整个实参列表被当成 1 个实参。后果是静默的：按索引取第 2/第 4 个实参的
    检查会因为 `len(args) < 2` 而直接 `continue`，**跳过所有首实参含 `->`
    的 connect**（例如 `connect(ui->addface, ...)`），既不报错也不提示。

    这里只让真正的 `(`/`)`、`[`/`]`、`{`/`}` 参与配对，`<`/`>` 仅在
    **成对尖括号模板**的常见形态下计数（用于 `QVector<int>` 这类逗号），
    并且要求 `<` 前是标识符、`>` 后不是 `>`（排除 `->` 与 `>>`）。
    """
    args, depth, cur = [], 0, ""
    i, n = 0, len(call)
    while i < n:
        ch = call[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "<":
            # 仅把 `标识符<` 视作模板起始；`a < b` 会同时匹配，但这类比较在
            # connect 实参里几乎不出现，且退化为不计数也只是保守（少切分）。
            if i > 0 and (call[i - 1].isalnum() or call[i - 1] == "_"):
                depth += 1
        elif ch == ">":
            # `->` 与 `>>` 不参与配对
            if i > 0 and call[i - 1] == "-":
                pass
            elif i + 1 < n and call[i + 1] == ">":
                pass
            else:
                depth -= 1
        if ch == "," and depth == 0:
            args.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    if cur.strip():
        args.append(cur)
    return args


def enclosing_call_text(text, open_paren_idx):
    """给定左括号下标，返回配对右括号之前的完整调用文本。"""
    depth, i = 0, open_paren_idx
    while i < len(text):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return text[open_paren_idx + 1:i]


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

        # 数值型字段还要做**取值**校验：随包发布的示例配置本身不能带
        # 端口 0 / 音量越界这类值（取值出口的兜底见
        # check_config_value_sanity()，两者互补）。
        # 注意 bool 是 int 的子类，需显式排除，否则 true 会被当成合法整数。
        ranges = [
            (("network", "signaling_port"), 1, 65535),
            (("media", "ringtone_volume"), 0, 100),
        ]
        for keys, lo, hi in ranges:
            node = data
            ok = True
            for k in keys:
                if not isinstance(node, dict) or k not in node:
                    ok = False
                    break
                node = node[k]
            if not ok or isinstance(node, bool) or not isinstance(node, (int, float)):
                continue  # 缺失/类型错误已在上面的 checks 中报过
            if not (lo <= node <= hi):
                fail(f"[json] {name} 字段 {'.'.join(keys)} 取值 {node} "
                     f"越界，允许范围 [{lo}, {hi}]")


def check_config_value_sanity(root, src_root):
    """
    数值型配置的取值出口必须做范围兜底。

    背景：配置（JSON 文件、环境变量）是不可信输入。环境变量经
    QString::toInt()/toUShort() 解析时，**非法文本会静默返回 0**；
    JSON 里也可以写 0、负数或超出 quint16 的值。这些值一旦直接进入
    端口绑定、音量设置等位置，就会出现“端口 0 → 绑定随机端口，门口机
    永远连不上”，或 setVolume 传入越界值。

    门口机那边同一模式已经造成真实崩溃：重构前是硬编码
    `const int detect_interval = 10;`，改成 cfg.faceDetectInterval() 后，
    配置为 0 就在 `++detectCounter % cfg.faceDetectInterval()` 处触发
    整数除零（SIGFPE，进程崩溃）。本规则与门口机的同名检查保持对称。

    做法：
      A) 所有 int/double/quint16 型配置访问器都必须被 clampInt()/
         clampDouble() 包住；
      B) 若某处直接用配置取值做除数，该访问器同样必须被兜底。
    """
    header = os.path.join(src_root, "config", "app_config.h")
    if not os.path.isfile(header):
        fail("[config-sanity] 找不到 src/config/app_config.h")
        return
    htext = strip_comments_and_strings(read(header))

    getter_re = re.compile(
        r'\b(?:int|double|quint16|qint16|qint32|quint32|long|short)\s+'
        r'(\w+)\s*\(\s*\)\s*const\s*\{([^{}]*)\}')
    # 必须匹配 `return clampInt(` 这种调用形态，避免被裸子串误命中。
    clamp_call_re = re.compile(r'\breturn\b[^;]*\bclamp(?:Int|Double)\s*\(')
    numeric_getters = {}
    for name, body in getter_re.findall(htext):
        numeric_getters[name] = bool(clamp_call_re.search(body))

    if not numeric_getters:
        fail("[config-sanity] 未在 app_config.h 中解析到任何数值型访问器"
             "（检查器已失效，请更新正则）")
        return

    unprotected = sorted(n for n, ok in numeric_getters.items() if not ok)
    if unprotected:
        fail("[config-sanity] 这些数值型配置访问器未做范围兜底: "
             + ", ".join(unprotected)
             + "（配置值可为 0/负数，用于端口或除数时行为异常）")

    # ---- B) 用配置取值做除数的地方 ----
    divisor_re = re.compile(
        r'[%\/]\s*(?:cfg|AppConfig::instance\(\))\s*\.\s*(\w+)\s*\(\s*\)')

    for path in find_files(src_root, {".cpp", ".h"}):
        text = strip_comments_and_strings(read(path))
        for m in divisor_re.finditer(text):
            getter = m.group(1)
            line = text.count("\n", 0, m.start()) + 1
            rel = os.path.relpath(path, root)
            if getter not in numeric_getters:
                warn(f"[config-sanity] {rel}:{line} 用 cfg.{getter}() 做除数，"
                     f"但未在 app_config.h 找到数值型访问器，请人工确认")
                continue
            if not numeric_getters[getter]:
                fail(f"[config-sanity] {rel}:{line} 用未兜底的配置值 "
                     f"cfg.{getter}() 做除数，配置为 0 时会除零崩溃")


def check_config_knobs_are_used(root, src_root):
    """
    配置里公开的每个开关都必须真的生效，否则它就是「假旋钮」。

    背景（门口机真实缺陷，重构引入）：config/appconfig.json 提供了
    behavior.face_confidence_threshold，app_config.h 也提供了访问器，
    但 FaceManager::recognize() 里仍是重构前的硬编码 `confidence < 90`。
    现场把该配置从 90 调到 60，行为毫无变化 —— 配置被读取、被文档化，
    却从不生效。这类缺陷不崩溃、不告警，只会让「调参」永远无效，是最难
    被发现的一类重构退化。本检查与门口机保持对称。

    判据（要比「访问器有没有人调」更准确）：
    配置值的流向是 JSON/环境变量 -> m_xxx -> 使用者。因此一个开关生效的
    充要条件是：访问器 `xxx()` 在 app_config.* 之外被调用，**或**它背后的
    成员 `m_xxx` 在**加载代码之外**被读取。

    两个容易误判的点，本实现都做了处理：
      1. 只看访问器调用点会误判 pcmDir() 这种：它无人调用，但 pcmFile()
         内部直接读了 m_pcmDir，配置其实完全有效。
      2. 加载代码里的成员读取不算「消费」。例如
             m_x = jsonInt(o, "x", m_x);   // 读，但只是回退实参
         若不剔除加载函数，假旋钮会被误判为生效（该缺陷最初就是这样漏掉的）。

    输出分两级：
      - 成员从未在加载之外被读取 -> fail（真·假旋钮，配置改了没用）
      - 成员有读取但访问器无人调用 -> warn（冗余访问器，可清理）
    """
    # 故意不读的访问器及理由。新增条目必须附理由，否则就是遗漏。
    ALLOWED_DEAD = {
        # 纯诊断用：main.cpp 直接使用 load() 的返回值判断配置来源，
        # 本访问器没有任何调用点。保留是为了给调试器/日志留一个查询入口，
        # 它不影响任何运行时行为，故不计入「假旋钮」。
        "loadedFromFile",
    }
    # 生命周期/单例/工厂方法不是配置项，不参与本检查。
    NOT_KNOBS = {"instance", "load", "configPath", "AppConfig", "operator"}

    header = os.path.join(src_root, "config", "app_config.h")
    impl = os.path.join(src_root, "config", "app_config.cpp")
    if not os.path.isfile(header) or not os.path.isfile(impl):
        fail("[config-knobs] 找不到 src/config/app_config.{h,cpp}")
        return

    htext = strip_comments_and_strings(read(header))
    ctext = strip_comments_and_strings(read(impl))

    # 无参 const 访问器及其内联函数体
    getter_re = re.compile(
        r'^\s*(?:const\s+)?[\w:<>]+(?:\s*[*&])?\s+(\w+)\s*\(\s*\)\s*const\s*'
        r'([;{])', re.M)
    knobs = []          # (accessor_name, member_name or None)
    for m in getter_re.finditer(htext):
        name, brace = m.group(1), m.group(2)
        if name in NOT_KNOBS or name in ALLOWED_DEAD:
            continue
        member = None
        if brace == "{":
            depth, i = 0, m.end() - 1
            while i < len(htext):
                if htext[i] == "{":
                    depth += 1
                elif htext[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            body = htext[m.end() - 1:i + 1]
            found = re.findall(r'\b(m_\w+)\b', body)
            if len(set(found)) == 1:
                member = found[0]
        knobs.append((name, member))

    if not knobs:
        fail("[config-knobs] 未在 app_config.h 中解析到任何无参访问器"
             "（检查器已失效，请更新正则）")
        return

    # app_config.* 之外的访问器调用点
    called = set()
    for path in find_files(src_root, {".cpp", ".h"}):
        if os.path.basename(path) in ("app_config.h", "app_config.cpp"):
            continue
        body = strip_comments_and_strings(read(path))
        for name, _ in knobs:
            if re.search(r'\b' + name + r'\s*\(\s*\)', body):
                called.add(name)

    def strip_loading_code(text):
        """
        剔除加载代码（load/applyDefaults/applyEnvironment），只留真正的消费者。

        加载函数里也会读成员，但那不代表配置生效——最典型的是把当前值当作
        回退实参：m_x = jsonInt(o, "x", m_x)。整体剔除后，剩下的 m_xxx
        读取才是真正的派生使用（例如 lightCommand() 读 m_lightCommands）。
        """
        loading_fns = ("load", "applyDefaults", "applyEnvironment")
        out = text
        for fn in loading_fns:
            for m in re.finditer(
                    r'\b[\w:<>]+\s+AppConfig::' + fn + r'\s*\([^;{]*\)\s*\{',
                    out):
                depth, i = 0, m.end() - 1
                while i < len(out):
                    if out[i] == "{":
                        depth += 1
                    elif out[i] == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    i += 1
                out = out[:m.start()] + "\n" * out[m.start():i + 1].count("\n") \
                    + out[i + 1:]
        return out

    consumed_text = strip_loading_code(ctext)

    def member_is_read(member):
        t = consumed_text
        t = re.sub(r'\b' + member + r'\s*=(?!=)', '', t)
        return re.search(r'\b' + member + r'\b', t) is not None

    fake, redundant = [], []
    for name, member in knobs:
        if name in called:
            continue
        if member is not None and member_is_read(member):
            redundant.append("%s()（配置经 %s 仍生效）" % (name, member))
        else:
            fake.append("%s()" % name if member is None
                        else "%s()/%s" % (name, member))

    if fake:
        fail("[config-knobs] 这些配置开关从未被读取，属于「假旋钮」"
             "（配置可读可调但永不生效）: " + ", ".join(sorted(fake))
             + "；若确为有意保留，请加入 check_config_knobs_are_used 的 "
               "ALLOWED_DEAD 并写明理由")
    if redundant:
        warn("[config-knobs] 访问器无人调用，但配置经成员变量仍然生效"
             "（冗余访问器，可考虑清理）: " + ", ".join(sorted(redundant)))


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

    注意：门口机（T113）另有一条互补规则 check_blocking_poll_has_handle()，
    覆盖“非 QWidget / 不会 close() 的常驻轮询器也必须持有句柄”的情形——
    不是为了防空转，而是为了能与其他共用同一硬件资源的流程互斥。
    本工程当前没有该形态的代码，为保持两端规则一致而同样注册了这条检查。
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


def check_blocking_poll_has_handle(root, src_root):
    """
    任何「周期性定时器 + 阻塞式读串口/读 socket」的轮询器，句柄必须是类成员。

    背景（真实缺陷，来自门口机 baseline，本轮修复）：

        void FingerprintManager::startIdentify()
        {
            QTimer* timer = new QTimer(this);    // 局部变量，无成员句柄
            connect(timer, &QTimer::timeout, this, [=]() mutable {
                fingerprint->sendPacket(pkt);
                QByteArray resp = fingerprint->readPacket(500);  // 阻塞读
                ...
            });
            timer->start(500);
        }

    为什么这是缺陷：识别轮询与注册流程读写的是**同一个串口**，

        识别轮询：  send(CMD_GET_IMAGE) → readPacket(500)   ← 抢应答
        注册流程：  send(CMD_GET_IMAGE) → readPacket(2000)  ← 抢应答

    两者互为对方之应答源：识别轮询会把注册流程正在等待的应答从串口缓冲里
    取走，注册流程拿到空字节数组，判为“采集图像失败”静默返回；反之亦然。
    要互斥就必须能**暂停识别轮询**，而暂停的前提是拿得到句柄。此外阻塞读
    跑在 GUI 线程上，每 500ms 会冻结界面一次。

    判定规则：在 .cpp 中找到被 start(...) 周期化的 QTimer，若其创建点是
    局部变量（非 m_xxx 成员、未放入容器、未 setSingleShot(true)），且回调
    体内出现阻塞读调用，则报错。要求改为成员句柄并给出停止/暂停入口。

    与 check_unqueued_poll_timers() 互补：后者只覆盖「继承 QWidget 且会
    close()」的类（防界面隐藏后定时器空转）；本规则覆盖其余常驻轮询器
    （防无法与共用同一硬件的流程互斥）。本工程当前无该形态代码，本条为
    预防性对称检查，与门口机保持一致。
    """
    blocking = (
        "readPacket", "waitForReadyRead", "waitForBytesWritten",
        "waitForDisconnected", "waitForConnected",
    )
    for path in find_files(src_root, {".cpp"}):
        text = strip_comments_and_strings(read(path))
        rel = os.path.relpath(path, root)
        if "new QTimer" not in text:
            continue

        header = path[:-4] + ".h"
        if not os.path.isfile(header):
            continue
        htext = strip_comments_and_strings(read(header))
        members = set(re.findall(r'\b(m_\w+)\s*(?:=|;|\))', htext))

        for m in re.finditer(r'\bQTimer\s*\*\s*(\w+)\s*=\s*new\s+QTimer\b', text):
            var = m.group(1)
            if not re.search(re.escape(var) + r'\s*->\s*start\s*\(', text):
                continue
            if var in members:
                continue
            if re.search(r'\b\w+\s*(?:\.append|<<)\s*\(\s*' + re.escape(var), text):
                continue
            if re.search(re.escape(var) + r'\s*->\s*setSingleShot\s*\(\s*true\s*\)',
                         text):
                continue

            conn = re.search(re.escape(var) + r'\s*,\s*&QTimer::timeout', text)
            if not conn:
                continue
            body = text[conn.end():conn.end() + 4000]
            depth = 0
            started = False
            end = len(body)
            for i, ch in enumerate(body):
                if ch == '{':
                    depth += 1
                    started = True
                elif ch == '}':
                    depth -= 1
                    if started and depth == 0:
                        end = i
                        break
            body = body[:end]
            if not any(b in body for b in blocking):
                continue

            line = text.count("\n", 0, m.start()) + 1
            fail("[poll-handle] {}:{} 周期性定时器 '{}' 的回调里有阻塞读（每轮会冻结"
                 "调用线程一次），却没有成员句柄保存它 → 外部无法暂停/停止。"
                 "若该轮询与其他流程共用同一设备（如串口），对方将与之互相抢读应答。"
                 "请改为成员变量并提供 setSuspended()/stop 入口。"
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


def check_datagram_read_returns(root, src_root):
    """
    所有 UDP 收包都必须检查 readDatagram() / recvfrom() 的返回值。

    背景（真实缺陷，本轮修复）：
    `CallSession::onAudioDataReady()` 与 `onVideoDataReady()` 原本写成

        QByteArray datagram;
        datagram.resize(socket->pendingDatagramSize());
        socket->readDatagram(datagram.data(), datagram.size(), ...);   // 返回值被丢弃

    两个后果：
      1) `QByteArray::resize()` **不清零**新分配的字节。若实际读到的字节数
         少于 `pendingDatagramSize()`，尾部就是未初始化内存（或上一轮循环的
         残留字节）。音频路径下它会被 append 后直接喂给声卡（噪声），
         视频路径下会交给 `loadFromData()` 解码（垃圾数据/解码器崩溃）。
      2) 返回 -1 表示读取失败，此时 `readDatagram` 不会填充
         sender/senderPort 出参。音频路径若不判就赋值，会把“回传目标地址”
         改成未初始化/上一次的地址，导致上行语音发错地方。

    `pendingDatagramSize()` 返回 qint64 而非 int，因此这里统一要求：
      - 抓到变量名，检查同函数内该变量有 `< 0` / `== -1` 之类的失败分支；
      - 若读取时用了出参（&sender / &port），失败必须 `continue`/`return`
        而不能继续使用出参。

    只做“返回值是否被接收并判负”的结构检查，不推断语义。
    """
    for path in find_files(src_root, {".cpp"}):
        text = strip_comments_and_strings(read(path))
        rel = os.path.relpath(path, root)

        # 逐个函数体检查
        for fm in re.finditer(
                r'^[\w:<>,\s\*&]+\b\w+\s*::\s*(\w+)\s*\([^;]*?\)\s*(?:const\s*)?\{',
                text, re.M):
            b0 = fm.end() - 1
            depth, i = 0, b0
            while i < len(text):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            body = text[b0:i + 1]
            line0 = text.count("\n", 0, b0) + 1

            for m in re.finditer(
                    r'(?:(?:const\s+)?\w+\s+(\w+)\s*=\s*)?'
                    r'(\w+(?:->|\.)readDatagram\s*\(|(?<!\w)recvfrom\s*\()',
                    body):
                assignee, call = m.group(1), m.group(2)
                call_line = line0 + body.count("\n", 0, m.start())
                fn_name = fm.group(1)
                if not assignee:
                    fail("[datagram-ret] {}:{} 函数 {}() 调用了 {} 但丢弃了返回值；"
                         "QByteArray::resize() 不清零，尾部可能是未初始化字节，"
                         "且失败(-1)时出参未被填充。必须接收并检查返回值。"
                         .format(rel, call_line, fn_name, call.strip()))
                    continue
                # 该赋值变量在后续是否被判负
                tail = body[m.end():]
                if not re.search(re.escape(assignee) + r'\s*(?:<\s*0|==\s*-1|!=\s*\w*\s*[!=])',
                                 tail):
                    fail("[datagram-ret] {}:{} 函数 {}() 接收了 {} 的返回值 '{}' "
                         "但未见 <0 / ==-1 之类的失败判断。"
                         .format(rel, call_line, fn_name, call.strip(), assignee))


def check_connect_signal_is_signal(root, src_root):
    """
    connect() 的第二个实参必须是**信号**。

    背景：Qt5 的 PMF 版 connect 会把第二个实参（成员指针）交给
    `QObject::connectImpl()`，后者用 `QMetaObject::IndexOfMethod()` 反查信号索引，
    而 moc **只为 `signals:` 区的成员生成信号索引**（槽/普通成员索引为 -1）。
    把一个槽或普通成员当作信号源连接，运行期必然失败：Qt 打印
    `QObject::connect: signal not found in <类名>`、connect 返回 false，
    对应的槽永远不会被调用，那段业务逻辑是死代码。

    注意：`connect(btn, &QPushButton::clicked, this, &Cls::someSlot)` 是完全正常的
    （槽只需可调用，不必是信号）。所以本检查**只看第二个实参**：只有当
    `&Cls::name` 中的 Cls 是本工程某个含 Q_OBJECT 的类、且 name 在该类的
    **非 signals 区**被显式声明时，才判定为错误。

    只看结构，不做语义推断；继承自基类的信号不予判定。
    """
    sig_re = r'^\s*(?:(?:public|private|protected)\s+)?(?:signals|Q_SIGNALS)\s*:'
    slot_re = r'^\s*(?:(?:public|private|protected)\s+)?(?:slots|Q_SLOTS)\s*:'
    acc_re = r'^\s*(?:public|private|protected)\s*:'
    mem_re = r'^(?:[\w:<>,\*&\s]+?\s)?~?(\w+)\s*\('
    skip = ("if", "for", "while", "switch", "return", "emit", "connect", "catch")

    # 1) 收集所有含 Q_OBJECT 的类的成员分区
    classes = {}
    for hpath in find_files(src_root, {".h", ".hpp"}):
        htext = strip_comments_and_strings(read(hpath))
        for cm in re.finditer(r'\bclass\s+(\w+)\s*(?::[^{;]*)?\{', htext):
            cname = cm.group(1)
            start = cm.end() - 1
            depth, i = 0, start
            while i < len(htext):
                if htext[i] == "{":
                    depth += 1
                elif htext[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            body = htext[start + 1:i]
            if "Q_OBJECT" not in body:
                continue
            signals, others = set(), set()
            cur = others
            for line in body.split("\n"):
                if re.match(sig_re, line):
                    cur = signals
                    continue
                if re.match(slot_re, line) or re.match(acc_re, line):
                    cur = others
                    continue
                m = re.match(mem_re, line.strip())
                if m and m.group(1) not in skip:
                    cur.add(m.group(1))
            classes[cname] = (signals, others)

    if not classes:
        return

    # 2) 扫描 connect() 的第二个实参
    for path in find_files(src_root, {".cpp"}):
        text = strip_comments_and_strings(read(path))
        rel = os.path.relpath(path, root)
        for m in re.finditer(r'\bconnect\s*\(', text):
            args = split_top_level_args(
                enclosing_call_text(text, m.end() - 1))
            if len(args) < 2:
                continue

            mm = re.search(r'&\s*(\w+)\s*::\s*(\w+)', args[1])
            if not mm:
                continue
            cname, name = mm.group(1), mm.group(2)
            if cname not in classes:
                continue
            signals, others = classes[cname]
            if name in signals or name not in others:
                continue
            line = text.count("\n", 0, m.start()) + 1
            fail("[connect-sig] {}:{} connect() 的第二个实参 &{}::{}() 不是信号"
                 "（它声明在非 signals 区）；moc 不会为它生成信号索引，运行期 "
                 "connect 必然失败并打印 \"signal not found in {}\"，"
                 "对应槽是死代码。"
                 .format(rel, line, cname, name, cname))


def check_declared_signal_is_emitted(root, src_root):
    """
    声明在 `signals:` 下的信号必须真的会被发射。

    背景（门口机侧的真实缺陷，本轮同步建立本检查）：
    `AudioSenderThread::connectionLost()` 被声明、被 Widget 连接、并且那段
    connect 的注释明确写着用途——

        // 采集线程报告连接丢失时立即挂断，避免通话卡死。
        connect(m_audioSenderThread, &AudioSenderThread::connectionLost,
                this, &Widget::hangUpCall);

    ——但**全工程从未 emit 过它**。于是这条兜底是死的：sendto 失败后采集循环
    break、线程结束，再无任何帧发往室内机，通话已单向静音，而界面依旧显示
    “通话中”，用户只能手动挂断。

    室内机当前无此问题（0 个死信号），本检查在此作为**回归防护**存在：
    `handleCall()`/`reply()` 这条链路依赖的 `accepted`/`answered`/
    `hangupClicked` 等信号一旦被改成“只声明不发射”，通话将静默失效。

    判定一个信号“真的会触发”只有两种途径：
      1. 被显式发射：`emit S(...)` 或直接调用 `S(...)`；
      2. 作为 connect 的**第 4 个实参**出现 —— 这是 Qt 的信号→信号链式连接
         （`connect(btn, &QPushButton::clicked, this, &Cls::S)`），源信号
         触发时 Qt 会自动发射 S。漏掉这一条会把链式目标误判为死信号。

    不判定经由 `QMetaObject::invokeMethod("name")` 触发的槽（本工程无此用法），
    也不判定字符串形式的 `SIGNAL()`（本工程已全部清除）。继承自基类的信号
    不在声明集合内，天然不参与判定。
    """
    sig_re = r'^\s*(?:(?:public|private|protected)\s+)?(?:signals|Q_SIGNALS)\s*:'
    slot_re = r'^\s*(?:(?:public|private|protected)\s+)?(?:slots|Q_SLOTS)\s*:'
    acc_re = r'^\s*(?:public|private|protected)\s*:'
    mem_re = r'^(?:[\w:<>,\*&\s]+?\s)?~?(\w+)\s*\('

    # 1) 收集每个含 Q_OBJECT 的类在 signals: 区声明的信号
    declared = {}
    for hpath in find_files(src_root, {".h", ".hpp"}):
        htext = strip_comments_and_strings(read(hpath))
        for cm in re.finditer(r'\bclass\s+(\w+)\s*(?::[^{;]*)?\{', htext):
            cname = cm.group(1)
            start = cm.end() - 1
            depth, i = 0, start
            while i < len(htext):
                if htext[i] == "{":
                    depth += 1
                elif htext[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            body = htext[start + 1:i]
            if "Q_OBJECT" not in body:
                continue
            cur = False
            for line in body.split("\n"):
                if re.match(sig_re, line):
                    cur = True
                    continue
                if re.match(slot_re, line) or re.match(acc_re, line):
                    cur = False
                    continue
                if cur:
                    m = re.match(mem_re, line.strip())
                    if m:
                        declared.setdefault(
                            (cname, m.group(1)), os.path.relpath(hpath, root))

    if not declared:
        return

    # 2) 收集 emit 目标、以及 connect 第 4 实参构成的链式目标
    emitted, chained = set(), set()
    for path in find_files(src_root, {".cpp"}):
        text = strip_comments_and_strings(read(path))
        for m in re.finditer(r'\bemit\s+(\w+)\s*\(', text):
            emitted.add(m.group(1))
        # 无 emit 关键字的直接调用（信号也是普通成员函数，可以直呼）
        for (cname, sig) in list(declared):
            if re.search(r'(?<![\w:.>&])' + re.escape(sig) + r'\s*\(', text):
                emitted.add(sig)

        for m in re.finditer(r'\bconnect\s*\(', text):
            args = split_top_level_args(
                enclosing_call_text(text, m.end() - 1))
            # 只需第 4 个实参（索引 3）作为链式发射目标
            if len(args) >= 4:
                m4 = re.search(r'&\s*(\w+)\s*::\s*(\w+)', args[3])
                if m4:
                    chained.add((m4.group(1), m4.group(2)))

    # 3) 判定
    for (cname, sig), rel in sorted(declared.items()):
        if sig in emitted or (cname, sig) in chained:
            continue
        fail("[dead-signal] {}: 信号 {}::{}() 声明在 signals: 区，但全工程既未 "
             "emit 它，也不是任何 connect 的链式发射目标 —— 它是一个永远不会"
             "触发的死信号。若有代码 connect 到它，那条连接与对应槽都是死代码"
             "（门口机曾因此丢掉 \"采集线程连接丢失即挂断\" 的兜底）。"
             .format(rel, cname, sig))


def check_abandoned_async_tasks(root, src_root):
    """
    用 `QtConcurrent::run` 启动、且把结果只赋给**单个变量**的异步任务，
    必须在同一函数里把 future 收集进容器，否则上一次任务会被"丢弃仍在运行"。

    背景（门口机的真实缺陷，本轮同步建立本检查）：
    `AudioManager::playAsync()` 每次播放都做三件事：

        stop();                                       // 置旧标志
        interruptFlag = std::make_shared<std::atomic<bool>>(false);
        playFuture = QtConcurrent::run([=]() { ... 捕获 this ... });

    而 **`QFuture` 赋值不会等待上一个任务结束**（只转移内部 d 指针的引用，
    `~QFuture()` 也不阻塞）。于是上一次播放若尚未结束，它就成了"被丢弃但仍在
    运行"的任务：

      - 它捕获的 `flag` 已不再是 `interruptFlag` 指向的对象，`stop()` 再也
        打不断它；
      - 析构若只 `waitForFinished()` 最后一个 future，旧任务完全不被等待，
        析构返回后它仍在 emit 信号、读成员 —— use-after-free。

    本工程当前未使用 QtConcurrent / QFuture，条规则作为**回归防护**存在：
    一旦有人为天气请求或媒体播放引入 QtConcurrent，这类"每次覆盖同一个
    QFuture"的写法会立刻被拦下。

    判定规则：某函数内出现 `X = QtConcurrent::run(...)`，且整个函数体内
    **没有任何** future 收集动作（`isRunning()` 过滤后 `append` 到容器），
    即判定为缺陷。

    不误伤"即发即忘"用法（`QtConcurrent::run(...)` 不赋给任何变量）：那类任务
    自带 QPointer 守卫，没有"被覆盖丢弃"的问题。
    """
    for path in find_files(src_root, {".cpp"}):
        text = strip_comments_and_strings(read(path))
        rel = os.path.relpath(path, root)
        if "QtConcurrent::run" not in text:
            continue

        funcs = list(re.finditer(
            r'^[\w:<>,\s\*&]+\b(\w+)\s*::\s*(\w+)\s*\([^;]*?\)\s*(?:const\s*)?\{',
            text, re.M))
        for fm in funcs:
            body_start = fm.end() - 1
            depth, i = 0, body_start
            while i < len(text):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            body = text[body_start:i + 1]
            if "QtConcurrent::run" not in body:
                continue

            assigned = re.findall(
                r'\b(\w+)\s*=\s*QtConcurrent\s*::\s*run\s*\(', body)
            if not assigned:
                continue  # 即发即忘，不判定

            # 收集动作：先把已完成的滤掉，再把仍在运行的收进容器。
            collects = bool(re.search(r'\.\s*append\s*\(', body)) and \
                bool(re.search(r'\bisRunning\s*\(', body))
            if collects:
                continue

            line = text.count("\n", 0, fm.start()) + 1
            fail("[abandoned-task] {}:{} {}() 里由 QtConcurrent::run 启动的异步"
                 "任务被直接赋给 \"{}\" 且未收集进容器。QFuture 赋值不会等待"
                 "上一个任务，故上一次仍在运行的任务会被丢弃：它捕获的 this 在"
                 "析构时不被等待会变成 use-after-free，它捕获的中断标志也不再受"
                 "stop() 影响。应把未完成的 future 收集起来，并在析构时逐个 "
                 "waitForFinished()。"
                 .format(rel, line, fm.group(2), "/".join(sorted(set(assigned)))))


def check_hex_parse_is_validated(root, src_root):
    """
    `QByteArray::fromHex()` 的输入必须先逐字符校验为纯十六进制。

    背景（真实缺陷，本轮修复）：
    `parseHexBytes()` 原来只检查"清洗后非空"与"长度为偶数"就调用 fromHex。

    而 fromHex() **不会**因非法字符而失败 —— 它**跳过**非法字符，把剩下的
    合法字符**重新两两配对**。已用真实 Qt 5.15.19 实测确认（见
    tests/test_app_config.cpp 中的可执行断言）：

        "FD0G4C12045DDF" (14, 偶数) -> 0f d0 4c 12 04 5d df   （内容全错）
        "XX034C12045DDF" (14, 偶数) ->    03 4c 12 04 5d df   （错位，少一字节）

    于是只要字符数是偶数，解码总是"成功"，`!bytes.isEmpty()` 完全拦不住，
    一条写错的灯控指令会被原样写进串口，灯只表现为"没反应"。

    判定规则：若某函数把**变量**（而非字符串字面量）传给 fromHex，且该函数
    体内没有显式的十六进制字符校验（isHexOnly 之类的调用，或逐字符比较
    '0'~'9'/'a'~'f'/'A'~'F'），即报错。

    传给 fromHex 的**字面量**（如 applyDefaults() 里的
    `QByteArray::fromHex("FD034C12045DDF")`）不受影响：字面量的合法性由
    人眼与测试保证。本工程当前唯一的变量用法是 parseHexBytes()。
    """
    # 显式校验的形态。两点约束来自故障注入自检：
    #  1. strip_comments_and_strings() 会把字符字面量清空（'0' -> ''），
    #     所以**不能**用 QChar('0') / c >= '0' 这类基于字符字面量的模式。
    #  2. 不能只写死少数几个函数名，否则换个名字（如 validateHexOnly）就
    #     漏判；这里用"名字里含 hex 的校验型函数调用"这一宽模式。
    hexcheck_re = re.compile(
        r"\b\w*(?:is|check|validate|verify|ensure|assert)\w*hex\w*\s*\("
        r"|\b\w*hex\w*(?:is|check|validate|verify|only|ok|valid)\w*\s*\("
        r"|\bisxdigit\b", re.I)
    for path in find_files(src_root, {".cpp"}):
        text = strip_comments_and_strings(read(path))
        rel = os.path.relpath(path, root)
        if "fromHex" not in text:
            continue
        # 同时覆盖 "Class::method(...)" 与**自由函数** "ret name(...)"。
        # 真实缺陷就在匿名命名空间里的自由函数 parseHexBytes()，若只匹配
        # Class::method 便完全漏判 —— 这正是本检查首版自检抓出来的问题。
        funcs = list(re.finditer(
            r'^[^\n{};#]*?\b(\w+)\s*\([^;{}]*\)\s*(?:const\s*)?\{',
            text, re.M))
        for fm in funcs:
            if fm.group(1) in ("if", "while", "for", "switch", "catch",
                               "else", "do", "return"):
                continue
            start = fm.end() - 1
            depth, i = 0, start
            while i < len(text):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            body = text[start:i + 1]
            if "fromHex" not in body:
                continue
            if hexcheck_re.search(body):
                continue
            # 提取 fromHex 的实参时**必须按括号配平扫描**，不能用
            # `fromHex\s*\(([^()]*)\)`：真实写法是
            #     QByteArray::fromHex(compact.toLatin1())
            # 实参里含有嵌套括号 `toLatin1()`，`[^()]*` 根本匹配不到右括号，
            # 于是整个 fromHex 调用被静默跳过、缺陷漏判。
            # （本检查首版正是如此，靠故障注入自检才暴露。）
            for m in re.finditer(r"fromHex\s*\(", body):
                open_idx = m.end() - 1
                depth, j = 0, open_idx
                while j < len(body):
                    if body[j] == '(':
                        depth += 1
                    elif body[j] == ')':
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                arg = body[open_idx + 1:j].strip()
                if not arg:
                    continue
                # 字面量：内容由代码显式写出，不判定
                if arg.startswith('"'):
                    continue
                line = text.count("\n", 0, fm.start()) + 1
                fail("[hex-parse] {}:{} {}() 把变量 \"{}\" 直接传给 "
                     "QByteArray::fromHex 而未先校验其为纯十六进制。"
                     "fromHex 遇到非法字符不会报错，而是跳过非法字符并把剩余"
                     "字符重新配对——偶数长度下总是\"成功\"、内容全错，"
                     "`!bytes.isEmpty()` 拦不住。请先用逐字符校验"
                     "（如 isHexOnly）拒绝含非十六进制字符的输入。"
                     .format(rel, line, fm.group(1), arg[:40]))


def check_load_state_reset(root, src_root):
    """
    配置载入函数必须在**每次调用开头**复位"是否已载入"状态。

    背景（真实缺陷，本轮修复）：
    `AppConfig` 是单例且 `load()` 可被多次调用。原实现只在成功分支里写
    `m_loadedFromFile = true`，却在函数末尾 `return m_loadedFromFile;`。
    applyDefaults() 只重置各字段，**不复位该标志**，于是：

        load(好文件) -> true
        load(坏文件) -> 解析失败走 continue，标志仍是 true -> **返回 true**
        load(不存在) -> 同样返回 true，configPath() 还指向早已失效的旧路径

    实测（真实 Qt）确认：load(bad) 返回 true 且 configPath 仍是上一个文件。
    调用方会据此认为"配置已按文件生效"，实际用的是内置默认值。

    判定规则：若某函数名形如 load/readConfig/parseConfig，体内有
    "<成员> = true/false" 这类标志赋值，且**末尾 return 该成员**，但函数开头
    （首个赋值之前）没有把它复位为 false，即报错。

    门口机侧使用**函数局部** `bool fileLoaded = false;`，天然无此问题 ——
    正是这个不对称让室内机的缺陷一直没被发现，故两仓库都保留本检查。
    """
    for path in find_files(src_root, {".cpp"}):
        text = strip_comments_and_strings(read(path))
        rel = os.path.relpath(path, root)
        funcs = list(re.finditer(
            r'^[^\n{};#]*?\b(\w+)\s*\([^;{}]*\)\s*(?:const\s*)?\{', text, re.M))
        for fm in funcs:
            name = fm.group(1)
            if name.lower() not in ("load", "readconfig", "parseconfig",
                                    "reload", "loadconfig"):
                continue
            start = fm.end() - 1
            depth, i = 0, start
            while i < len(text):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            body = text[start:i + 1]
            line = text.count("\n", 0, fm.start()) + 1
            # 末尾 return 的是某个成员（m_xxx）
            mret = re.search(r'return\s+(m_\w+)\s*;', body)
            if not mret:
                continue
            member = mret.group(1)
            # 该成员被赋过值
            assigns = list(re.finditer(
                r'\b' + re.escape(member) + r'\s*=\s*(true|false)\s*;', body))
            if not assigns:
                continue
            # 以**首个赋值为 true** 的位置为界，看它之前有没有复位为 false。
            # 注意不能拿"第一个赋值"当界——那样复位语句本身就成了界，
            # head 恒为空，规则会把正确代码也判为缺陷（首版正是这个错误，
            # 由故障注入的"开头复位(真阴性)"用例抓出）。
            set_true = None
            for a in assigns:
                if a.group(1) == "true":
                    set_true = a
                    break
            if set_true is None:
                continue  # 从未置 true，不存在残留问题
            head = body[:set_true.start()]
            if re.search(r'\b' + re.escape(member) + r'\s*=\s*false\s*;', head):
                continue
            fail("[load-state] {}:{} {}() 末尾 return {}，但函数开头没有把它"
                 "复位为 false。该成员是单例状态，多次调用 load() 时失败路径"
                 "不会清零它，于是 load(坏文件) 会返回 true（上一次成功的残留），"
                 "调用方误以为配置已生效。请在函数开头显式复位"
                 "（并一并清理 configPath 之类的状态）。"
                 .format(rel, line, name, member))


def check_narrowing_cast_of_config(root, src_root):
    """
    配置整数转窄类型前必须先夹取，不能直接 static_cast。

    背景（真实缺陷，本轮修复）：
    `m_signalingPort = static_cast<quint16>(jsonInt(..., "signaling_port", ...))`
    —— `static_cast` 到 quint16 是**取模截断**而不是夹取。实测（真实 Qt）：

        65536  -> 0      （=> QTcpServer 绑定随机临时端口）
        999999 -> 16959
        -1     -> 65535
        -5     -> 65531

    用户写 65536/-1 这类"明显想表达边界"的值时，得到的是能成功监听的**错误
    端口**：门口机连不上，而日志显示监听正常。必须在 cast 之前用 clampInt。

    判定规则：`static_cast<quint16|quint8|qint16|qint8|char|short>(...)` 的实参
    里若直接调用 jsonInt/toInt/toUShort/toUInt 等**未夹取**的读取函数，即报错。
    传入 clampInt(...) 的写法不受影响。
    """
    narrow = r'(?:quint16|quint8|qint16|qint8|uint16_t|uint8_t|int16_t|int8_t|char|short|unsigned\s+short)'
    readfn = r'(?:jsonInt|jsonDouble|toInt|toUInt|toUShort|toULongLong|toLongLong)'
    for path in find_files(src_root, {".cpp"}):
        text = strip_comments_and_strings(read(path))
        rel = os.path.relpath(path, root)
        for m in re.finditer(r'static_cast\s*<\s*' + narrow + r'\s*>\s*\(', text):
            open_idx = m.end() - 1
            depth, j = 0, open_idx
            while j < len(text):
                if text[j] == '(':
                    depth += 1
                elif text[j] == ')':
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            arg = text[open_idx + 1:j]
            if not re.search(r'\b' + readfn + r'\s*\(', arg):
                continue
            if re.search(r'\bclampInt\s*\(|\bclampDouble\s*\(', arg):
                continue
            line = text.count("\n", 0, m.start()) + 1
            fail("[narrow-cast] {}:{} static_cast 到窄整型前没有夹取：{}"
                 "static_cast 是**取模截断**而非夹取（65536 -> 0、-1 -> 65535、"
                 "999999 -> 16959），越界配置会变成\"能用的错误值\"，比直接报错"
                 "更难发现。请先 clampInt(..., lo, hi) 再转换。"
                 .format(rel, line, text[m.start():j + 1][:90]))


WIRE_FORMAT_CONSTANTS = (
    "kAudioSampleRate",
    "kAudioChannels",
    "kAudioBytesPerSample",
    "kAudioFramesPerPacket",
    "kSignalingPort",
    "kAudioPort",
    "kVideoPort",
    "kPreviewPort",
)


def check_wire_format_constants_are_pinned(root, src_root):
    """
    影响线上字节格式的协议常量必须在 tests/ 里被断言。

    注：本规则由 T113 仓库移植而来。两个仓库共享同一份 protocol.h，
    室内机是 UDP 12345 的接收方，若包长/采样率常量被改动而测试无反应，
    同样只表现为"声音不对"且不报错，所以这里也要钉住。

    背景（真实的测试盲区，本轮补上）：
    AudioSenderThread 决定 UDP 12345 的**字节格式**（裸 PCM、S16_LE、
    16000 Hz、单声道、每包 320 帧 = 640 字节、**无包头**），室内机按包直接
    喂给 ALSA，所以包长或字节序错一点，现场只表现为"声音不对/有杂音"，
    **不报任何错误**。

    它此前从未被真正验证过：tools/devstubs 的 sendto() 只"返回 len"、不留
    痕迹，其 inet_pton() 还**永远返回 0**，导致 run() 在建连阶段就 return，
    根本走不到发送代码——测试即使"绿"着，发送逻辑一行都没执行。

    所以本检查要求：这些常量名必须出现在 tests/ 的源码里。它不能证明断言
    写得好，但能保证"改了这些值而测试毫无反应"这种情况不会悄悄发生。
    """
    proto = os.path.join(src_root, "core", "net", "protocol.h")
    if not os.path.isfile(proto):
        FAIL.append(f"[wire-format] 找不到 {proto}")
        return

    text = strip_comments_and_strings(read(proto))
    declared = set()
    for m in re.finditer(r"constexpr\s+[\w:]+\s+(k\w+)\s*=", text):
        declared.add(m.group(1))

    tests_root = os.path.join(root, "tests")
    if not os.path.isdir(tests_root):
        FAIL.append("[wire-format] 找不到 tests 目录，无法验证协议常量是否被钉住")
        return

    test_text = []
    for path in find_files(tests_root, (".cpp", ".h", ".hpp", ".c")):
        test_text.append(strip_comments_and_strings(read(path)))
    blob = "\n".join(test_text)

    missing = [c for c in WIRE_FORMAT_CONSTANTS if c in declared and c not in blob]
    if missing:
        FAIL.append(
            "[wire-format] 下列协议常量决定了线上字节格式，却没有任何测试断言它们："
            + ", ".join(missing)
            + " —— 改动它们不会让任何测试失败（详见 README 第 22 条）"
        )


def top_level_function_ranges(text):
    """
    返回 [(函数体起止下标, 函数体文本)]，只认**花括号深度为 0** 的函数定义。

    为什么不用"由内向外回溯"：那条路要往前找上一个 `;`/`}`/`{` 作为签名起点，
    而 `for (int i = 0; i < N; ++i)` 这类**头部含分号**的控制语句会把签名截断成
    `++i)`，于是被误判成函数签名、函数体只截到内层块。第 18 轮的
    `snd_pcm_writei` 正好包在这样一个 for 里，导致规则整处漏报（自检 4/6）。

    只看深度 0 的块就能彻底避开这个问题：函数体一定是一个深度 0 的块，
    块内嵌套的 for/if/lambda 都在深度 >= 1，不会被误认。
    """
    out = []
    depth = 0
    i = 0
    opens = []
    while i < len(text):
        c = text[i]
        if c == "{":
            if depth == 0:
                opens.append(i)
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and opens:
                start = opens.pop()
                out.append((start, i + 1, text[start:i + 1]))
            if depth < 0:
                depth = 0
        i += 1
    return out


def enclosing_function_body(text, pos):
    """返回包含 text[pos] 的**最内层顶层函数体**；找不到返回 None。"""
    best = None
    for start, end, body in top_level_function_ranges(text):
        if start <= pos < end:
            if best is None or start > best[0]:
                best = (start, end, body)
    return best[2] if best else None


def top_level_function_ranges(text):
    """
    返回 [(函数体起止下标, 函数体文本)]，只认**花括号深度为 0** 的函数定义。

    为什么不用"由内向外回溯"：那条路要往前找上一个 `;`/`}`/`{` 作为签名起点，
    而 `for (int i = 0; i < N; ++i)` 这类**头部含分号**的控制语句会把签名截断成
    `++i)`，于是被误判成函数签名、函数体只截到内层块。第 18 轮的
    `snd_pcm_writei` 正好包在这样一个 for 里，导致规则整处漏报（自检 4/6）。

    只看深度 0 的块就能彻底避开这个问题：函数体一定是一个深度 0 的块，
    块内嵌套的 for/if/lambda 都在深度 >= 1，不会被误认。
    """
    out = []
    depth = 0
    i = 0
    opens = []
    while i < len(text):
        c = text[i]
        if c == "{":
            if depth == 0:
                opens.append(i)
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and opens:
                start = opens.pop()
                out.append((start, i + 1, text[start:i + 1]))
            if depth < 0:
                depth = 0
        i += 1
    return out


def enclosing_function_body(text, pos):
    """返回包含 text[pos] 的**最内层顶层函数体**；找不到返回 None。"""
    best = None
    for start, end, body in top_level_function_ranges(text):
        if start <= pos < end:
            if best is None or start > best[0]:
                best = (start, end, body)
    return best[2] if best else None


def check_nonblock_pcm_handles_eagain(root, src_root):
    """
    以 SND_PCM_NONBLOCK 打开的 PCM 句柄，必须把 -EAGAIN 与真错误区分开。

    背景（真实缺陷，第 18 轮修复）：
    `AudioReceiverThread::run()` 里

        snd_pcm_open(&pcm_handle, PCM_DEVICE,
                     SND_PCM_STREAM_PLAYBACK, SND_PCM_NONBLOCK);

    设备是**非阻塞**打开的，因此 `snd_pcm_writei` 返回 -EAGAIN（播放缓冲区
    暂时满）是**完全可达的**正常情况，不是错误。原实现只特判 -EPIPE，其余
    负值一律走 `rcw < 0` 分支 → emit errorMsg + 结束播放线程。
    现场表现是**通话中途突然单向无声**，而 errorMsg 只打日志、界面毫无察觉。
    对照实验（探针，600 ms 窗口）：修复前 connectionLost 发射 3410 次且线程
    仍在运行；修复后恰好 1 次且线程结束。

    反向也危险：`AudioSenderThread` 以同样方式打开**采集**句柄，
    `snd_pcm_readi` 在缓冲区暂时没数据时同样返回 -EAGAIN；若把它当致命错误，
    上行音频会随录音间隙中断（该线程已有处理，见 tests/test_audio_sender.cpp）。

    判定：对每个 `snd_pcm_readi/writei` 调用，取其**所属函数体**；若该函数体内
    以 SND_PCM_NONBLOCK 打开了 PCM 句柄，则该函数体内必须出现 EAGAIN 或
    EWOULDBLOCK 字样。这是"有没有区分"的下限检查，不判断处理是否正确。
    """
    for path in find_files(src_root, (".cpp", ".cc", ".cxx")):
        rel = os.path.relpath(path, root)
        text = strip_comments_and_strings(read(path))
        if "SND_PCM_NONBLOCK" not in text:
            continue
        for m in re.finditer(r"\b(snd_pcm_(?:readi|writei))\s*\(", text):
            fn = m.group(1)
            body = enclosing_function_body(text, m.start())
            if body is None:
                continue
            if "SND_PCM_NONBLOCK" not in body:
                continue
            if "EAGAIN" in body or "EWOULDBLOCK" in body:
                continue
            fail("[nonblock-pcm] {} 里以 SND_PCM_NONBLOCK 打开 PCM 句柄后调用 {}，"
                 "却没有在同一个函数体内处理 -EAGAIN/-EWOULDBLOCK。"
                 "非阻塞句柄在缓冲区满/空时**必然**返回 -EAGAIN，把它当致命错误会"
                 "让通话中途单向无声（下行）或随录音间隙中断（上行）。"
                 "该值是可恢复的，应重试或丢弃本包后继续，而不是结束线程。"
                 .format(rel, fn))


def check_gated_wire_paths_have_resume_test(root, src_root):
    """
    用布尔闸门控制推流的通路，必须测试"停止后能再次开始"。

    背景（真实覆盖盲区，第 20 轮对照实验发现）：
    `CameraUdpServer::onReadyRead` 的 stop 分支里有 `sending = false;`。
    实测把它整行删掉后，**所有原有测试仍然通过** —— 因为"停止"由
    `sendTimer->stop()` 独立完成，而 `sendFrame()` 开头的 `if (!sending) return;`
    又使其线上不可见。也就是说这行赋值对"停止"是**冗余**的。

    它真正的作用在**恢复**路径：若停止时没有把 sending 置回 false，
    再次收到 `getframe` 时 `if (!sending) { sending = true; sendTimer->start(); }`
    不成立，定时器不会重新启动，**第二次监看永远看不到画面**，而且不报任何错。

    因此对"仅在请求后才工作、且可停止"的通路，测试必须覆盖完整序列：
      开始 -> 收到数据 -> 停止 -> 再次开始 -> 必须能再次收到数据

    判定（下限检查）：若某个源文件里同时存在
      - 形如 `if (!X) { ... X = true; ... start(); }` 的闸门，且
      - 形如 `X = false; ... stop();` 的停止分支，
    则认为该通路有闸门；此时 tests/ 的源码里必须出现"恢复"语义的标记
    （resume / reopened / restart / 恢复 等）。不要求精确匹配用例名，
    但要求有人显式测过这条序列。
    """
    gate_files = []
    for path in find_files(src_root, (".cpp", ".cc", ".cxx")):
        text = strip_comments_and_strings(read(path))
        # 闸门：if (!flag) { ... flag = true; ... .start(); }
        for m in re.finditer(
                r"if\s*\(\s*!\s*(\w+)\s*\)\s*\{[^{}]*?"
                r"\b\1\s*=\s*true\b[^{}]*?\bstart\s*\(\s*\)\s*;",
                text, re.S):
            flag = m.group(1)
            # 停止分支：`flag = false;` 之后不远处有 `stop()`。
            # 注意不能用 `false\s*;[^;]*;[^;]*?stop` 这种写法 —— 它要求
            # `sending = false;` 与 `stop()` 之间**再出现一个分号**，而实际
            # 代码是紧邻的两条语句 `sending = false;\n sendTimer->stop();`
            # （第二个分号在 stop() 之后），于是匹配数为 0，整条规则变成空转
            # （自检里表现为"没有恢复语义"这一真阳性用例漏报）。
            # 改用有界窗口即可。
            if re.search(r"\b" + re.escape(flag) + r"\s*=\s*false\s*;"
                         r"[\s\S]{0,120}?\bstop\s*\(\s*\)\s*;", text):
                gate_files.append((os.path.relpath(path, root), flag))

    if not gate_files:
        return

    tests_root = os.path.join(root, "tests")
    if not os.path.isdir(tests_root):
        fail("[gated-resume] 存在带闸门的推流通路，却找不到 tests 目录")
        return
    blob = "\n".join(strip_comments_and_strings(read(p))
                     for p in find_files(tests_root, (".cpp", ".h", ".hpp", ".c")))
    # 原始文本也要看：中文注释是常见写法，strip 会把注释清掉。
    raw_blob = "\n".join(read(p)
                         for p in find_files(tests_root, (".cpp", ".h", ".hpp", ".c")))

    markers = ("resume", "Resume", "reopen", "Reopen", "restart", "Restart",
               "恢复", "再次", "重新开始")
    # 去掉注释后仍要能看出"再次开始"的语义
    if any(mk in blob for mk in markers) or any(mk in raw_blob for mk in markers):
        return

    for rel, flag in gate_files:
        fail("[gated-resume] {} 用布尔闸门 `{}` 控制推流（开始/停止各一处），"
             "但 tests/ 里没有任何『停止后再次开始』的用例。"
             "这类通路的停止分支常有一行把闸门置回初始值的赋值，它对"
             "'停止'本身是冗余的、线上不可见，删掉后任何只测停止的用例都会通过；"
             "而少了它，再次请求时条件判断不成立，第二次使用永远起不来且不报错。"
             "请补一条 开始->停止->再次开始->能再次收到 的用例。".format(rel, flag))


def check_fingerprint_ack_tag_is_validated(root, src_root):
    """
    指纹应答在被当作"成功"之前，应校验**包标识**（0x07 = PKT_ACK）。

    背景（跨层契约不一致，第 21 轮发现）：
    同一个 `fingerprint_hailin.cpp` 里的两条解析路径判据不同：
      - `autoIdentify()` 显式校验 `(quint8)resp[6] != PKT_ACK` 后才解析；
      - `stepRegister()` / `stepIdentify()` 只判 `resp.size() < 12 || resp[9] != 0`；
      - `FingerprintManager` 的识别轮询回调同样只看
        `resp.size() >= 12 && (quint8)resp[9] == 0x00`。

    后果：串口上任何 "byte[9]==0x00 但包标识不是 0x07" 的字节流
    （噪声、命令回显、错位后重新同步出的伪帧）都会被误判为"手指已按下"，
    于是界面直接跳到采集步骤，而实际上根本没有手指。

    为什么只报 WARNING 而不是失败：
    收紧判据会**改变现场行为**，而本项目对协议的要求是"与 baseline 逐字节
    兼容"。这不是一个可以单方面由静态检查决定的修复，需要显式决策；
    当前行为已由 tests/test_fingerprint_manager.cpp 的
    `commandTagFrameIsNotAValidAck` 钉住，避免被无意改动。

    判定：若某个访问 `resp[N]`（N 为常量）的函数里，读到了确认码语义
    的下标 9，却没有任何对 `resp[6]` 的包标识比较，则给出警告。
    """
    hits = []
    for path in find_files(src_root, {".cpp"}):
        text = strip_comments_and_strings(read(path))
        rel = os.path.relpath(path, root)
        if "resp" not in text:
            continue
        funcs = list(re.finditer(
            r'^[\w:<>,\s\*&]+\b(\w+)\s*::\s*(\w+)\s*\([^;]*?\)\s*(?:const\s*)?\{',
            text, re.M))
        for fi, fm in enumerate(funcs):
            body_start = fm.end() - 1
            depth = 0
            i = body_start
            while i < len(text):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            body = text[body_start:i + 1]
            fname = fm.group(2)

            # 该函数是否在"读确认码"
            reads_confirm = re.search(r'\b(resp\w*)\s*\[\s*9\s*\]', body)
            if not reads_confirm:
                continue
            var = reads_confirm.group(1)
            # 是否校验了包标识：var[6] 与某个 PKT_ACK / 0x07 比较
            has_tag_check = re.search(
                r'\b' + re.escape(var) + r'\s*\[\s*6\s*\]', body)
            if has_tag_check:
                continue
            # 反过来：是否校验了"某个东西的[6]"，写法可能是 pkt[6] 等
            if re.search(r'\[\s*6\s*\]\s*!=\s*PKT_ACK', body):
                continue
            line = text.count("\n", 0, body_start) + 1
            hits.append((rel, line, fname, var))

    for rel, line, fname, var in hits:
        warn("[fp-ack-tag] {}:{} `{}()` 把 {}[9] 当作确认码，但没有校验包标识 "
             "{}[6]==0x07(PKT_ACK)。串口噪声或命令回显（byte[9]==0 但标识不是 "
             "应答）会被误判为『手指已按下』，界面会直接进入采集步骤。"
             "同文件的 autoIdentify() 是校验了的，两条路径判据不一致。"
             "收紧判据会改变现场行为，需显式决策，故此处仅告警。"
             .format(rel, line, fname, var, var))



def _norm_metatype(name):
    r"""
    把类型名规范化为"最后一段限定名 + 指针后缀"，用于跨命名空间比较。

    为什么需要：测试文件顶部常有 `using namespace accessterminal;`，于是断言
    写成 `value<protocol::Signal>()`，而注册写成
    `qRegisterMetaType<accessterminal::protocol::Signal>()`。
    两者是**同一个类型**，按字面比较会误报 —— 我在真实仓库上实测到了这一点。

      protocol::Signal                    -> Signal
      accessterminal::protocol::Signal    -> Signal
      QTcpSocket*                         -> QTcpSocket*
      QList<int>                          -> QList<int>   （保持原样）

    局限：若两个不同命名空间的同名类型同时在一个文件里被使用，会漏报。
    对当前仓库不成立，且本规则是告警级启发式，接受此局限。
    """
    t = " ".join(str(name).split())
    stars = "*" if t.endswith("*") else ""
    base = t.rstrip("*").strip()
    base = base.split("::")[-1].strip()
    return base + stars


def check_signalspy_types_are_registered(root, src_root):
    r"""
    测试用 QSignalSpy 断言自定义类型时，必须显式 qRegisterMetaType。

    背景（第 22 轮实测，非推测）：
    `Q_DECLARE_METATYPE` 只让 `QVariant::value<T>()` **编译**通过；跨越队列
    投递传递自定义类型还需要**运行时注册**，否则 Qt 打印
    "Cannot queue arguments of type ..." 并把参数丢成默认构造值 ——
    spy 里拿到的是 Unknown / nullptr，断言失败的样子**像被测代码的 bug**。

    实测边界（逐项变异确认，不可笼统概括）：
      - 只去掉 Signal 的注册   -> 只有 receivesExactWireBytes 失败；
      - 只去掉 QTcpSocket* 注册 -> 只有 replyWritesExactWireBytes 失败；
      - 两个都去掉             -> 两条都失败。
    所以规则按**类型**分别判定，而不是"用了 QSignalSpy 就要求统一注册"。

    判定：从 `value<T>()` 这种断言落点里抽出模板实参 T，若 T 不是 Qt 内建
    类型，则该文件必须出现 `qRegisterMetaType<T>`。

    为什么从"用法"抽而不是"先枚举类型名再反查"：第一版用
    `[A-Z]\w*(?:::[A-Z]\w*)+` 枚举限定名，它要求**首段大写**，于是
    `accessterminal::protocol::Signal`（首段小写）整个漏掉了 —— 真阳性用例
    只报出 1 项却期望 2 项，被自检当场抓住。
    """
    import re as _re
    tests_root = os.path.join(root, "tests")
    if not os.path.isdir(tests_root):
        return

    # Qt 内建类型不必注册（已在 Qt 元类型系统里）。
    builtin = {
        "int", "bool", "double", "float", "char", "short", "long",
        "uint", "ushort", "ulong", "qint8", "qint16", "qint32", "qint64",
        "quint8", "quint16", "quint32", "quint64", "QString", "QVariant",
        "QByteArray", "QDateTime", "QDate", "QTime", "QPoint", "QPointF",
        "QSize", "QSizeF", "QRect", "QRectF", "QLine", "QLineF", "QUrl",
        "QChar", "QLocale", "QRegExp", "QRegularExpression", "QStringList",
        "QVariantList", "QVariantMap", "QVariantHash", "QBitArray",
        "unsigned int", "unsigned char", "unsigned short", "unsigned long",
    }

    for path in find_files(tests_root, {".cpp"}):
        text = read(path)
        if "QSignalSpy" not in text:
            continue
        rel = os.path.relpath(path, root)
        stripped = strip_comments_and_strings(text)

        # 从断言落点抽取类型：value<T>() 的 T。
        # 允许 T 里带 *、限定名、模板参数（如 QList<int>）。
        wanted = set()
        for m in _re.finditer(r'value\s*<\s*([^<>;{}]+?)\s*>\s*\(', stripped):
            t = " ".join(m.group(1).split())
            if not t:
                continue
            base = t.rstrip("*").strip()
            if base in builtin:
                continue
            wanted.add(t)

        # 注册处收集到的类型，按"规范化名"比较 —— 见下方 norm() 的说明。
        registered = set()
        for m in _re.finditer(r'qRegisterMetaType\s*<\s*([^<>;{}]+?)\s*>',
                              stripped):
            registered.add(_norm_metatype(m.group(1)))

        for t in sorted(wanted):
            if _norm_metatype(t) in registered:
                continue
            fail("[signalspy-metatype] {} 用 QSignalSpy 断言自定义类型 {}，"
                 "但没有 qRegisterMetaType<{}>()。Q_DECLARE_METATYPE 只保证"
                 "编译通过，跨队列投递还需运行时注册；否则参数会被丢成默认值，"
                 "断言失败的样子像被测代码的 bug（第 22 轮实测：缺 Signal 注册"
                 "只让 receivesExactWireBytes 失败；缺 QTcpSocket* 注册只让"
                 "replyWritesExactWireBytes 失败）。".format(rel, t, t))


def check_declared_slot_is_reachable(root, src_root):
    r"""
    声明在 `slots:` 下、但既无调用者也不是 connect 目标的成员函数 = **不可达槽**。

    背景（第 23 轮发现，baseline 同样存在，属继承死代码）：
    `FingerprintManager::startEnroll(int)` 有完整实现、有守卫、有分步状态机，
    第 21 轮我还为它写了 26 个单元测试 —— 但它在**整个工程里没有任何调用者**，
    也不是任何 connect 的目标。现场真正跑的指纹注册是 `Form_finger` 里那套
    **内联**状态机（`startFingerRegisterStep` + `doFingerCollect`），它直接
    调 `buildPacket/sendPacket/readPacket`，完全绕过 `FingerprintManager`。

    也就是说：那份测试覆盖的是**平行实现**，不是产线代码。这是
    "有测试 ≠ 被测到" 的升级版 —— 不是测试没断言到输出，而是被测对象
    根本不在执行路径上。

    同类还有 `Widget::onFingerprintEnroll` / `Widget::onFingerprintIdentify`：
    它们分别对应 `FingerprintManager::enrollResult` / `identifyResult`，
    而 `identifyResult` 已被改成 lambda 连接、`enrollResult` 只在
    `startEnroll` 里发射（那条路是死的），于是这两个槽永远不会被调用。

    为什么只报 WARNING：
      - 槽可能是**刻意保留的公开 API**（供未来接线或外部调用）；
      - `on_<对象名>_<信号>()` 由 `connectSlotsByName` 自动接线，必须排除，
        否则会把全部按钮槽误报成死代码；
      - 判定是静态的，无法覆盖 `QMetaObject::invokeMethod` 按名调用，
        也无法覆盖跨仓库（另一仓库可能调用本仓库的公开槽）。

    判定：对每个 slots: 区声明的函数，
      1. 若是 `on_<对象名>_<信号>` 命名，跳过（uic 自动接线）；
      2. 若作为 connect 的第 2 或第 4 实参出现，跳过；
      3. 若在任何 .cpp 里以 `name(` 出现，且**不是** `Cls::name(` 形式
         （即不是定义行本身），算有调用者；
      4. 三条都不满足 -> 告警。
    """
    import re as _re
    slot_re = r'^\s*(?:(?:public|private|protected)\s+)?(?:slots|Q_SLOTS)\s*:'
    sig_re = r'^\s*(?:(?:public|private|protected)\s+)?(?:signals|Q_SIGNALS)\s*:'
    acc_re = r'^\s*(?:public|private|protected)\s*:'
    mem_re = r'^(?:[\w:<>,\*&\s]+?\s)?~?(\w+)\s*\('

    slots = {}
    for hpath in find_files(src_root, {".h", ".hpp"}):
        htext = strip_comments_and_strings(read(hpath))
        for cm in _re.finditer(r'\bclass\s+(\w+)\s*(?::[^{;]*)?\{', htext):
            cname = cm.group(1)
            start = cm.end() - 1
            depth, i = 0, start
            while i < len(htext):
                if htext[i] == "{":
                    depth += 1
                elif htext[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            body = htext[start + 1:i]
            if "Q_OBJECT" not in body:
                continue
            cur = False
            for line in body.split("\n"):
                if _re.match(slot_re, line):
                    cur = True
                    continue
                if _re.match(sig_re, line) or _re.match(acc_re, line):
                    cur = False
                    continue
                if cur:
                    mm = _re.match(mem_re, line.strip())
                    if mm:
                        slots.setdefault((cname, mm.group(1)),
                                         os.path.relpath(hpath, root))
    if not slots:
        return

    texts = {}
    for path in find_files(src_root, {".cpp"}):
        texts[path] = strip_comments_and_strings(read(path))

    # connect 目标：第 2 实参（信号）与第 4 实参（槽）
    targets = set()
    for path, text in texts.items():
        for mm in _re.finditer(r'\bconnect\s*\(', text):
            args = split_top_level_args(
                enclosing_call_text(text, mm.end() - 1))
            if len(args) >= 2:
                lt = _re.findall(r'(\w+)', args[1])
                if len(lt) >= 2:
                    targets.add((lt[-2], lt[-1]))
            if len(args) >= 4:
                m4 = _re.search(r'&\s*(?:(\w+)::)?(\w+)\s*$', args[3].strip())
                if m4:
                    targets.add((m4.group(1), m4.group(2)))

    auto_re = _re.compile(
        r'^on_[A-Za-z0-9_]+_(clicked|toggled|pressed|released|'
        r'textChanged|textEdited|valueChanged|currentIndexChanged|'
        r'returnPressed|activated|editingFinished|stateChanged|'
        r'currentTextChanged|highlighted|destroyed|triggered)$')

    for (cname, slot), rel in sorted(slots.items()):
        if (cname, slot) in targets or auto_re.match(slot):
            continue
        calls = 0
        for path, text in texts.items():
            for mm in _re.finditer(r'\b' + _re.escape(slot) + r'\s*\(', text):
                ctx = text[max(0, mm.start() - 80):mm.start()]
                # 定义行：以 "Cls::" 结尾
                if _re.search(r'(^|[^\w])' + _re.escape(cname) + r'\s*::\s*$',
                              ctx):
                    continue
                calls += 1
        if calls == 0:
            warn("[dead-slot] {}: 槽 {}::{}() 既无调用者、也不是任何 connect 的"
                 "目标（已排除 uic 自动接线的 on_<对象>_<信号>）—— 它是**不可达"
                 "代码**。为它写的单元测试覆盖的是平行实现、不是产线路径；"
                 "改动它不会影响现场行为。第 23 轮实测："
                 "FingerprintManager::startEnroll 就是如此（现场跑的是 "
                 "Form_finger 的内联状态机）。若为刻意保留的公开 API，"
                 "请在注释中说明。".format(rel, cname, slot))




def check_live_fingerprint_enroll_sequence_is_pinned(root, src_root):
    r"""
    **产线真正走的**指纹注册路径的命令字节与超时必须被钉住。

    背景（第 23 轮）：
    指纹注册在工程里有**两份**实现：
      A) `FingerprintManager::startEnroll(int)` —— 有测试、**无生产调用者**；
      B) `Form_finger::startFingerRegisterStep()` + `doFingerCollect()`
         —— 内联状态机，直接读写串口，**这才是现场执行的那条**。

    两条并不等价：B 在每一步先由轮询定时器发一次 `CMD_GET_IMAGE` 探手指，
    确认后再在 `doFingerCollect()` 里**再发一次** `CMD_GET_IMAGE` 才 `GEN_CHAR`；
    A 只发一次。B 与 baseline 的 `form_finger.cpp` 逐字节一致（第 23 轮实测：
    两处各 9 个 append、序列与超时完全相同），因此 B 才是必须守住的契约。

    B 无法用单元测试覆盖：它是 UI 类，`startFingerRegisterStep` 需要经由
    `parentWidget()` 上溯到 `Widget` 才能拿到 `fingerprint()`，还要真实的
    `QTimer` 与提示音。为它造夹具比被测代码还复杂，且会引入新的"平行实现"。
    因此改用**静态契约检查**把它的线上字节钉住 —— 与
    `check_wire_format_constants_are_pinned` 同一思路。

    判定：在 `form_finger.cpp` 里按源码顺序抽取
      - `append((char)常量)` 的常量（变量如 `step`/`id >> 8` 归一为占位符）
      - `readPacket(超时)`
    与内置的期望序列逐一比较。序列变了就说明线上字节被改动过。
    """
    import re as _re
    target_rel = os.path.join("src", "ui", "form_finger.cpp")
    path = os.path.join(root, target_rel)
    if not os.path.exists(path):
        return
    text = read(path)
    # 去注释，避免注释里的 0x0N 干扰
    text = _re.sub(r'/\*[\s\S]*?\*/', '', text)
    text = _re.sub(r'//[^\n]*', '', text)

    def func_body(s, sig):
        try:
            i = s.index(sig)
        except ValueError:
            return ""
        j = s.index('{', i)
        depth, k = 0, j
        while k < len(s):
            if s[k] == '{':
                depth += 1
            elif s[k] == '}':
                depth -= 1
                if depth == 0:
                    break
            k += 1
        return s[j:k + 1]

    def seq(body):
        out = []
        for m in _re.finditer(
                r'append\s*\(\s*\(char\)\s*([^)]+?)\s*\)'
                r'|readPacket\s*\(\s*(\d+)\s*\)', body):
            if m.group(1) is not None:
                v = " ".join(m.group(1).split())
                # 变量归一为占位符（它们的取值在别的断言里管）
                if not v.startswith("0x") and not v.isdigit():
                    v = "<var>"
                out.append("B:" + v)
            else:
                out.append("T:" + m.group(2))
        return out

    got = []
    for sig in ('void Form_finger::startFingerRegisterStep(',
                'void Form_finger::doFingerCollect('):
        got += seq(func_body(text, sig))

    # 期望序列（第 23 轮实测，与 baseline form_finger.cpp 逐字节一致）
    #   轮询探手指 GET_IMAGE(500)
    #   采集   GET_IMAGE(2000) -> GEN_CHAR(step)(2000)
    #   合并   REG_MODEL(2000)
    #   存储   STORE_CHAR(1,id_hi,id_lo)(2000)
    want = [
        "B:0x01", "T:500",
        "B:0x01", "T:2000",
        "B:0x02", "B:<var>", "T:2000",
        "B:0x05", "T:2000",
        "B:0x06", "B:1", "B:<var>", "B:<var>", "T:2000",
    ]
    if got != want:
        fail("[fp-live-seq] {} 的指纹注册命令序列与钉住的契约不一致。\n"
             "        期望: {}\n        实际: {}\n"
             "        这是**产线真正执行**的注册路径（Form_finger 内联状态机，"
             "不是 FingerprintManager::startEnroll —— 那条没有调用者）。"
             "命令字节/超时是指纹模块的硬契约，改动后模块不会按预期响应。"
             .format(target_rel, " ".join(want), " ".join(got)))



def check_coverage_denominator_is_declared(root, src_root):
    r"""
    覆盖率必须连**分母**一起声明，否则数字本身具有误导性。

    背景（第 24 轮首次量化覆盖率时发现）：
    本工程第一次跑 gcov 得到 "94.4%" —— 看上去产线代码几乎都被测过。
    但那个分母只含**被链接进测试目标的 17 个文件**。另有 20 个产线源文件
    （约 2093 行，含 ui/widget.cpp 678 行、hal/fingerprint_hailin.cpp 332 行、
    ui/form_finger.cpp 162 行）从未被任何测试目标链接，根本不出现在 gcov
    数据里，分母被悄悄缩小。把未测文件折进分母后，真实覆盖率约 **22%**。

    这与第 30 条"被测对象不在执行路径上"是同一类错误的不同表现：
    前者是测试没落在产线代码上，后者是**统计口径**没把未测代码算进去。
    数字正确、口径错误，比没数字更危险 —— 它会让人停止寻找缺口。

    判定：tools/coverage_report.py 必须
      1. 存在；
      2. 显式列出"从未被任何测试目标链接的产线源文件"；
      3. 给出把未测文件折进分母后的总覆盖率（而不是只报已测文件的百分比）。

    这三条保证任何人都无法只引用那个漂亮的小分母数字。
    """
    import re as _re
    rep = os.path.join(root, "tools", "coverage_report.py")
    if not os.path.exists(rep):
        fail("[coverage-denominator] 缺少 tools/coverage_report.py —— "
             "覆盖率必须可复现，不能只在会话里手算。")
        return
    text = read(rep)
    checks = [
        (r"从未被任何测试目标链接", "未列出'从未被链接'的产线文件清单"),
        (r"不自我美化的总覆盖率", "未给出折入未测文件后的真实总覆盖率"),
        (r"近似总覆盖率", "未输出真实总覆盖率数值"),
    ]
    for pat, why in checks:
        if not _re.search(pat, text):
            fail("[coverage-denominator] tools/coverage_report.py {}。"
                 "只报'已测文件'的百分比会让人误以为产线代码已被覆盖 —— "
                 "第 24 轮实测：小分母下是 94.4%，真实值约 22%。".format(why))



def check_fake_fingerprint_builds_same_bytes(root, src_root):
    r"""
    链接期替身里的报文构造必须与**生产实现**逐字节一致。

    背景（第 25 轮）
    ----------------
    第 20/21 轮用"链接期替身"测指纹流程，前提是"替身里 buildPacket() 是真实
    算法的逐字节拷贝 —— 报文字节是唯一不能换的契约"。但那个前提**从未被自动
    验证**，后果有二：

      1. 生产的 buildPacket() 覆盖率是 **0**（它从未被链接进任何测试目标），
         报文字节实际上没有被任何运行时测试直接验证过；
      2. 契约被复制成**两份**（生产一份、替身一份），却没有一条检查盯着
         "两份还一样吗"。有人改了生产的校验和起始下标或长度字段，替身不跟着
         变，测试照样全绿，而真机报文已经错了。

    这是第 23 轮"平行实现"教训的又一种形态：同一契约的多份副本之间没有契约。
    本规则把两份实现的**字节写入操作序列**抽出来做归一化比较，任一处不同即失败。

    注意：本规则不是替代单元测试，而是补上"两份副本相互一致性"这一维度 ——
    单元测试只看替身，看不到生产实现已经漂移。
    """
    import re as _re

    prod = os.path.join(root, "src", "hal", "fingerprint_hailin.cpp")
    fake = os.path.join(root, "tests", "fake_fingerprint_device.cpp")
    if not os.path.exists(prod) or not os.path.exists(fake):
        return  # 该仓库没有指纹代码（如桌面端）

    def _strip(text):
        text = _re.sub(r"/\*[\s\S]*?\*/", "", text)
        text = _re.sub(r"//[^\n]*", "", text)
        return text

    def _body(text, sig):
        i = text.index(sig)
        j = text.index("{", i)
        depth, k = 0, j
        while k < len(text):
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        return text[j:k + 1]

    def _ops(body):
        out = []
        for m in _re.finditer(
                r"(\w+)\s*\.\s*append\s*\(\s*(?:\(char\)\s*)?([^;]+?)\s*\)\s*;",
                body):
            expr = " ".join(m.group(2).split())
            expr = _re.sub(r"\bPKT_CMD\b", "0x01", expr)
            out.append(expr)
        for m in _re.finditer(r"(?:quint16|const quint16)\s+\w+\s*=\s*([^;]+);",
                              body):
            # static_cast<quint16>(x) 与 x 语义等价（payload 远小于 65536）
            e = " ".join(m.group(1).split())
            e = _re.sub(r"static_cast<quint16>\s*\(\s*(.*?)\s*\)$", r"\1", e)
            out.append("LEN=" + e)
        for m in _re.finditer(
                r"for\s*\(\s*int\s+\w+\s*=\s*(\d+)\s*;[^;]*;\s*([^)]*)\)",
                body):
            out.append("LOOP from=%s step=%s" % (m.group(1),
                                                 " ".join(m.group(2).split())))
        return out

    try:
        ps = _strip(read(prod))
        fs = _strip(read(fake))
        po = _ops(_body(ps, "HailinFingerprint::buildPacket("))
        fo = _ops(_body(fs, "QByteArray buildFrame("))
    except (ValueError, OSError) as exc:
        fail("[fake-wire] 无法抽取报文构造实现做比对: %s" % exc)
        return

    if po != fo:
        for i in range(max(len(po), len(fo))):
            a = po[i] if i < len(po) else "<缺失>"
            b = fo[i] if i < len(fo) else "<缺失>"
            if a != b:
                fail("[fake-wire] 替身 tests/fake_fingerprint_device.cpp 的 "
                     "buildFrame() 与生产 src/hal/fingerprint_hailin.cpp 的 "
                     "buildPacket() **已经漂移**：第 %d 步 生产=%r 替身=%r。"
                     "单元测试只跑替身，看不到生产实现已漂移 —— 真机报文会错，"
                     "而所有指纹测试仍然全绿。" % (i, a, b))


def check_fingerprint_checksum_logic_is_not_duplicated(root, src_root):
    r"""
    校验和逻辑在同一个文件里**有两份**，且其中一份是死代码 —— 必须显式记录。

    第 25 轮实测：`HailinFingerprint::calcChecksum()` 在生产代码里**零调用者**，
    而 `buildPacket()` 自己内联了同一个累加循环：

        for (int i = 6; i < pkt.size(); ++i) sum += (quint8)pkt[i];

    实测 baseline（`terminal/smartpronew/HailinFingerprint.cpp`）同样零调用者，
    所以这是**继承来的**，不是重构引入的缺陷，本轮不改行为。

    但它是一个真实的可维护性隐患：两份拷贝可以各自漂移。第 25 轮的故障注入
    实测证实了后果 —— 只把 `calcChecksum` 的起始下标从 6 改成 0，**18 个
    指纹用例全部照常通过**（因为没人调用它）；而若有人"顺手修好"这个死函数
    并开始调用它，报文校验和就会与 `buildPacket()` 不一致。

    本规则只做**告警并要求显式记录**，不改变行为（改它是否属于"修缺陷"需要
    产品决策）。已有的 buildPacket 单元测试钉住了实际生效的那一份契约。
    """
    import re as _re

    prod = os.path.join(root, "src", "hal", "fingerprint_hailin.cpp")
    if not os.path.exists(prod):
        return
    text = read(prod)
    loop = "for (int i = 6; i < pkt.size(); ++i) sum += (quint8)pkt[i];"
    n = text.count(loop)
    if n < 2:
        return

    # calcChecksum 是否有调用者？（定义行本身不算）
    callers = 0
    for path in find_files(src_root, {".cpp", ".h"}):
        body = read(path)
        for m in _re.finditer(r"calcChecksum\s*\(", body):
            line = body[body.rfind("\n", 0, m.start()) + 1:
                        body.find("\n", m.start())]
            if "quint16 HailinFingerprint::calcChecksum" in line:
                continue          # 定义
            if _re.match(r"\s*(quint16\s+)?calcChecksum\s*\([^;]*\)\s*;", line):
                if "HailinFingerprint::" not in line and ":" not in line.split(
                        "calcChecksum")[0]:
                    continue      # 头文件里的声明
            callers += 1
    if callers == 0:
        warn("[dup-checksum] src/hal/fingerprint_hailin.cpp 里校验和累加循环出现 "
             "%d 次，但 HailinFingerprint::calcChecksum() **零调用者** —— "
             "第二份是死代码。baseline 亦然（继承而来，本轮不改行为）。"
             "隐患：两份拷贝可各自漂移；故障注入实测「只改死的那份」时 18 个"
             "指纹用例全部照常通过。若将来启用它，必须与 buildPacket() 的"
             "累加范围保持一致（自下标 6 起算、不含包头与设备地址）。" % n)



def check_tool_scripts_are_console_encoding_safe(root, src_root):
    r"""
    tools/ 下的自检脚本必须能在本机控制台编码（GBK）下安全输出。

    背景（第 25 轮，代价是两轮误诊）
    -------------------------------
    两个故障注入自检脚本里用了 `✓`（U+2713）。本机控制台是 GBK，于是脚本在
    **打印"已按预期失败 ✓"那一行**抛：

        UnicodeEncodeError: 'gbk' codec can't encode character '\u2713'

    危险之处在于**它伪装成通过**：报告前面的检查结果已经正常输出，看上去一切
    正常；而 rc=1，若调用方忽略返回码或只看尾部输出，就会被读成"全绿"。

    第 24 轮我遇到同一现象时误诊为"多余参数"问题（因为我当时用 pwsh 且设了
    `PYTHONIOENCODING=utf-8` 去测，掩盖了真正的编码问题），打了个治症状的补丁。
    第 25 轮才查出真因。

    规则：脚本要么(a)把 stdout/stderr `reconfigure(encoding="utf-8",
    errors="replace")`，要么(b)不包含 GBK 编不出来的字符。逐个删符号不算修好 ——
    下次加一个新符号就会复发。
    """
    tools = os.path.join(root, "tools")
    if not os.path.isdir(tools):
        return

    seen = 0
    for fn in sorted(os.listdir(tools)):
        if not fn.endswith(".py"):
            continue
        path = os.path.join(tools, fn)
        text = read(path)
        seen += 1

        if 'reconfigure(encoding="utf-8"' in text:
            continue

        bad = set()
        for ch in text:
            if ord(ch) < 128:
                continue
            try:
                ch.encode("gbk")
            except UnicodeEncodeError:
                bad.add(ch)
        if bad:
            fail("[tool-encoding] tools/%s 含本机 GBK 控制台**无法编码**的字符 "
                 "%r，且没有把 stdout 重配为 utf-8。脚本会在打印结果时抛 "
                 "UnicodeEncodeError —— 而前面的输出看起来一切正常，"
                 "极易被误读成「通过」。修法：加 "
                 "sys.stdout.reconfigure(encoding='utf-8', errors='replace')，"
                 "不要逐个删符号（下次加新符号会复发）。"
                 % (fn, "".join(sorted(bad))))
    if seen == 0:
        warn("[tool-encoding] tools/ 下没有找到任何 .py 脚本？")



def check_coverage_separates_dead_from_untested(root, src_root):
    r"""
    覆盖率必须把"未覆盖行"拆成「静态不可达」与「可达未测」。

    背景（第 26 轮）
    ---------------
    `fingerprint_hailin.cpp` 报 17.9%，像个大洞。拆开一看：

        可执行行 285
          零调用者（静态不可达，且 baseline 亦然）  204 行 = 71.6%
          有调用者（真的没测到）                     81 行，其中未执行 30 行

    只报一个百分比会**同时误导两个方向**：既把基线就没接线的死代码算成
    "待补缺口"（为它写测试只会测到『平行实现』，见第 30 条），又把真正可补的
    那几十行淹没在噪声里。

    本工程有大量这类方法：`HailinFingerprint::autoIdentify/autoEnroll/cancel/
    stepRegister/stepIdentify` 五个入口**在生产代码里零调用者**，且实测
    baseline 同样零调用者 —— 继承而来，既不是缺陷也不该算作待办。

    规则：`tools/coverage_report.py` 必须输出未覆盖行的可达性分类，并明确
    指出"待办看可达未测那一列"。判定依据是"所在成员函数在生产代码里有无调用点"。

    附带要求（第 25 轮约定的一体两面）：脚本必须在**目标控制台编码**下可输出，
    即含 `reconfigure(encoding="utf-8"`，否则分类报告可能在打印时崩掉。

    能力边界（如实记录，避免高估本规则）
    ----------------------------------
    这是一条"**能力存在性 + 分类标签存在性**"检查，它验证的是：
    分类函数在、且报告里两个类别都显式输出。它**不能**发现"函数还在但
    被掏空成 `return {}`"这类问题 —— 那需要运行脚本来验证。

    因此本规则与"跑一次 coverage_report.py 看输出"是**互补**的，不是替代。
    故障注入实测：一致地改名（行为不变）时本规则通过是**正确**的 ——
    它检查的是能力是否存在，不是"有没有被改动"。
    """
    rep = os.path.join(root, "tools", "coverage_report.py")
    if not os.path.exists(rep):
        return          # check_coverage_denominator_is_declared 已负责报缺失
    text = read(rep)

    if "classify_uncovered" not in text:
        fail("[coverage-reachability] tools/coverage_report.py 没有把未覆盖行按"
             "可达性分类。只报『未覆盖 N 行』无法指导行动：第 26 轮实测 "
             "fingerprint_hailin.cpp 的 234 行未覆盖里，204 行是**零调用者的"
             "死代码**（baseline 亦然），只有 30 行真的可补。不分类就会把死代码"
             "当成待办、把真缺口淹没。")
        return

    for pat, why in [
        ("不可达", "未标注『不可达』这一类"),
        ("可达未测", "未标注『可达未测』这一类"),
    ]:
        if pat not in text:
            fail("[coverage-reachability] tools/coverage_report.py %s —— "
                 "两类必须都显式输出，否则读者无法区分『基线没接线』与"
                 "『有测试但没跑到』。" % why)



def check_password_log_regression_is_enforced(root, src_root):
    r"""
    密码日志安全必须由**运行期测试**守住，且该测试的断言不得为空。

    背景（第 27 轮）
    ---------------
    baseline 的 `checkPassword()` 把用户输入、正确密码、以及两者 hex 全打进
    qDebug（已核对 baseline 源码）。门口机是实体门禁设备，密码是物理准入凭据，
    qDebug 在嵌入式 Linux 上落 stderr/journal、跨重启留存 —— 输错一次就把
    密码交了出去。

    重构已修掉，但此前只有一条**静态文本规则**在守。静态规则可能被绕过
    （改名、拼串、经辅助函数转一手），所以必须有运行期测试。

    而运行期测试有它自己的失效方式 —— **断言恒真**。第 27 轮实测踩到：
    用环境变量注入非 ASCII 哨兵，而 `AppConfig::toQString()` 是
    `QString::fromLocal8Bit()`；本机 GBK 下 13 个码元进去、16 个出来，
    于是"日志里不含哨兵前缀"在比较两个不同的串，**恒真**。是故障注入
    发现"前缀脱敏"变异抓不到才暴露的。

    因此本规则要求三件事同时存在：
      1. 测试被接进 tests/CMakeLists.txt（否则写了不跑）；
      2. **阳性对照** —— 断言非敏感日志确实被捕获（捕获管道坏了要先炸）；
      3. **夹具自证** —— 断言哨兵原样到达被测代码（跨编码边界必须先证明）。

    能力边界：这是形态检查，**不能**替代真跑一次（"断言写了但写反了"看不出）。
    它与 tools/verify_password_log_test.py 的故障注入互补。
    """
    # 本仓库不适用则直接返回：室内机不持有门禁凭据。
    # 若照搬门口机那版，会因为找不到 tests/test_password_manager.cpp 而误报。
    if not os.path.exists(os.path.join(src_root, "managers",
                                      "password_manager.cpp")):
        return

    tests_dir = os.path.join(root, "tests")
    tf = os.path.join(tests_dir, "test_password_manager.cpp")
    cm = os.path.join(tests_dir, "CMakeLists.txt")

    if not os.path.exists(tf):
        fail("[password-log] 缺少 tests/test_password_manager.cpp —— 门禁密码的"
             "日志安全只由静态文本规则守着。静态规则可能被绕过（改名/拼串/"
             "经辅助函数转一手），必须有一个运行期测试真的抓日志来断言。")
        return

    if os.path.exists(cm):
        if "test_password_manager.cpp" not in read(cm):
            fail("[password-log] tests/test_password_manager.cpp 没有接进 "
                 "tests/CMakeLists.txt —— 写了但不会跑，等于没有。")

    text = read(tf)

    # 2) 阳性对照：必须有"捕获管道确实工作"的断言。
    if "MsgCapture::count() > 0" not in text:
        fail("[password-log] test_password_manager.cpp 缺少**阳性对照**：没有"
             "断言『确实捕获到了日志』。若消息处理器没装上或日志走了别的通道，"
             "所有『不包含密码』的断言会一起假成立 —— 测试看着很严，实则零验证。")

    # 3) 夹具自证：哨兵必须原样到达被测代码。
    #
    # 注意别把这里写成"永远不触发"的规则（第 22 轮的教训）。第一版写成
    #     if "Fixture" not in text and "哨兵必须原样" not in text:
    # 而测试文件的头部注释里恰好含"哨兵必须原样到达被测代码" —— 外层恒 False，
    # 真正的断言检查永远不可达。**守卫条件不能引用被守卫内容里会出现的字符串。**
    # 现在直接检查断言本体，并要求它落在一个具名用例里。
    if "doorPassword(), pwd" not in text:
        fail("[password-log] test_password_manager.cpp 缺少**夹具自证**：没有"
             "断言哨兵原样到达被测代码（缺 `doorPassword(), pwd` 这一断言）。"
             "第 27 轮实测：经环境变量注入非 ASCII 哨兵时，AppConfig 用 "
             "fromLocal8Bit() 解码，GBK 代码页下 13 个码元进、16 个出，导致"
             "『日志不含哨兵前缀』恒真 —— 断言在，却什么都没验证。凡夹具跨过一次"
             "编码边界，必须先断言它没变形。")

    # 4) 前缀脱敏也算泄漏：断言必须覆盖多个前缀，而不是只查一个固定长度。
    if "password.left(4)" in text or ".left(4) +" in text:
        pass
    if "for (int n = 1; n <= secret.size(); ++n)" not in text:
        warn("[password-log] test_password_manager.cpp 未逐一断言密码的**每个**"
             "前缀。只查一个固定长度（如 left(4)）会漏掉 left(2)、mid(0,n) 等"
             "其它脱敏写法，而前缀脱敏对短密码等于全泄。")

    # 5) 故障注入夹具必须在（证明这些断言真的会失败）。
    fx = os.path.join(root, "tools", "verify_password_log_test.py")
    if not os.path.exists(fx):
        fail("[password-log] 缺少 tools/verify_password_log_test.py —— 没有故障"
             "注入就无法证明这些安全断言**真的会失败**。不失败的回归测试"
             "没有价值。")



def check_gpio_failure_paths_are_testable(root, src_root):
    r"""
    硬件封装（GpioLine）的“硬件出错”分支必须有**可编程假实现**覆盖。

    背景（第 28 轮）
    ---------------
    `GpioLine` 管的是门口机**物理门锁/补光**那条线（PE5 = 线号 133，开锁与
    补光共用，见 widget.cpp:224-226）。它此前从未被链接进任何测试目标，而它的
    危险分支全在硬件出错上：打不开 chip / 拿不到线 / 请求失败 / 读失败。
    处理错的后果是“该开门时不开”，或**请求泄漏把线占死**（下次开锁 EBUSY）。

    真机 gpiochip 无法按需制造这些失败，开发机也没有 gpiochip，因此必须靠
    可编程假实现。本轮补齐时夹具自造过两次假象，本规则把它们的结构性前提钉住：

      1. 线号上限必须覆盖实际线号。第一版设每 chip 64 条，而工程用 132/133，
         于是所有正常用例失败 —— 是夹具错了，不是生产代码。
      2. 内存所有权必须对齐 libgpiod 1.x：线对象**由 chip 拥有**
         （get_line 返回 chip 内部的数组元素），release 不释放内存、close 才
         释放。第一版让两者各自 new/delete，于是生产代码在请求失败路径里先
         release 再 close 时被误报成 release:unknown。

    能力边界：形态检查，不能替代真跑（断言写反了看不出），
    与 tools/verify_gpio_test.py 的故障注入互补。
    """
    src = os.path.join(src_root, "hal", "gpio.cpp")
    if not os.path.exists(src):
        return          # 本仓库没有 GPIO 封装，规则不适用

    tests_dir = os.path.join(root, "tests")
    hdr = os.path.join(tests_dir, "fake_gpiod.h")
    impl = os.path.join(tests_dir, "fake_gpiod.cpp")
    tf = os.path.join(tests_dir, "test_gpio.cpp")
    cm = os.path.join(tests_dir, "CMakeLists.txt")

    for p, why in ((hdr, "假 libgpiod 头文件"),
                   (impl, "假 libgpiod 实现"),
                   (tf, "GpioLine 测试")):
        if not os.path.exists(p):
            fail("[gpio-test] 缺少 " + os.path.basename(p) + "（" + why + "）。"
                 "GpioLine 的硬件出错分支无法被执行 —— 真机 gpiochip 不能按需"
                 "失败，开发机也没有 gpiochip，没有假实现这些分支就永远是死代码。")
            return

    if os.path.exists(cm):
        c = read(cm)
        for needle, why in (("test_gpio.cpp", "测试源文件未链接"),
                            ("fake_gpiod.cpp", "假实现未链接"),
                            ("hal/gpio.cpp", "被测的生产实现未链接")):
            if needle not in c:
                fail("[gpio-test] tests/CMakeLists.txt 缺少 " + needle
                     + "（" + why + "）—— 写了但不会跑，等于没有。")

    h = read(hdr)
    i = read(impl)

    # 现场度量：仍持有有效请求的线数。
    if "busyLineCount" not in h or "busyLineCount" not in i:
        fail("[gpio-test] 假 libgpiod 未提供 busyLineCount()。只数对象个数发现"
             "不了**请求泄漏** —— 泄漏的请求会让线一直 busy，下次开锁直接 "
             "EBUSY，这才是现场的故障度量。")

    # 调用序列：断言“先 release 后 close”的前提。
    if "callLog" not in h or "callLog" not in i:
        fail("[gpio-test] 假 libgpiod 未记录调用序列（callLog）。只数次数发现"
             "不了**释放顺序颠倒** —— 而 gpio.cpp 明确声明了先释放线、再关闭"
             "chip 这一契约。")

    # 线号上限必须覆盖工程实际线号。
    if "kMaxLines" not in i:
        fail("[gpio-test] 假 libgpiod 没有显式的线号上限（kMaxLines）。第一版"
             "设成 64 而工程使用 132/133，导致所有正常用例失败 —— 那是夹具"
             "自造的假象。必须显式声明并覆盖实际线号。")
    else:
        m = re.search(r"kMaxLines\s*=\s*(\d+)", i)
        if not m or int(m.group(1)) < 1024:
            fail("[gpio-test] 假 libgpiod 的线号上限过小（"
                 + (m.group(1) if m else "未找到") + "），必须 >= 1024 才能覆盖"
                 "工程实际使用的 PE4=132 / PE5=133。")

    # 内存所有权模型。
    if "requested" not in i or "ownerOf" not in i:
        warn("[gpio-test] 假 libgpiod 未体现 libgpiod 1.x 的内存所有权模型"
             "（线对象由 chip 拥有、release 只清请求状态）。若让 get_line 各自 "
             "new、release 各自 delete，生产代码在请求失败路径里先 release 再 "
             "close 会被误报成 release:unknown。")

    # 故障注入夹具必须在。
    fx = os.path.join(root, "tools", "verify_gpio_test.py")
    if not os.path.exists(fx):
        fail("[gpio-test] 缺少 tools/verify_gpio_test.py —— 没有故障注入就无法"
             "证明这些资源生命周期断言**真的会失败**。不失败的回归测试没有价值。")



def check_face_gate_hazard_is_documented(root, src_root):
    r"""
    人脸门禁的隐患必须被测试**显式钉住**，且"唯一判据"这一事实不能丢失。

    背景（第 29 轮）
    ---------------
    FaceManager 决定**门开不开**（widget.cpp:889 检出人脸后调用 recognize()，
    recognizeResult 决定是否开门）。它此前从未被链接进任何测试目标。

    写断言前先做了临时探针，量到三条决定性事实：

      1. 模型未训练时 predict() 抛 cv::Exception
         （"This LBPH model is not computed yet"）。而 recognize() 的守卫是
         `registeredFaces.size() < collectTarget` —— 数**样本数**，不是
         "模型已训练"。两者在"填满样本但跳过 train()"时不相等，此时异常会
         从 UI 线程的槽里逃出事件循环，直接终止进程。
         当前不可达（唯一调用点 widget.cpp:767-768 填满即 train()），
         但属**隐患**：一旦有人加了别的调用路径就会爆。
      2. **单 label 时 `predictedLabel == 1` 恒为真**（训练 labels 全是 1），
         因此 `confidence < threshold` 是**门禁的唯一判据**。
      3. 我原本怀疑的"越界裁剪 -> 空样本 -> train 抛异常"链**不成立**
         （实测 QImage::copy() 传越界矩形不返回空图），该猜测已被推翻。

    本规则钉住：
      - 门禁测试存在且接进构建；
      - "唯一判据"这条断言存在（丢了它，门禁安全就没人守）；
      - 上述隐患被测试**显式**记录（丢了它，隐患会静默变成缺陷）；
      - 故障注入夹具存在（不失败的回归测试没有价值）；
      - 阈值无范围约束 -> warn（安全相关，见下）。

    关于阈值的 warn
    ---------------
    探针证实门禁安全**完全取决于**该阈值，而它只被读取、**没有任何范围
    约束**（app_config.cpp 里 qBound/clamp 调用总数为 0）。配置成 1e9 会让
    任何陌生人像都判"通过"，门锁形同虚设。这不是崩溃类缺陷，故只告警；
    是否加约束属行为变化，需要单独决定。
    """
    impl = os.path.join(src_root, "managers", "face_manager.cpp")
    if not os.path.exists(impl):
        return          # 本仓库没有 FaceManager，规则不适用

    tests_dir = os.path.join(root, "tests")
    tf = os.path.join(tests_dir, "test_face_manager.cpp")
    cm = os.path.join(tests_dir, "CMakeLists.txt")
    fx = os.path.join(root, "tools", "verify_face_manager_test.py")

    if not os.path.exists(tf):
        fail("[face-gate] 缺少 tests/test_face_manager.cpp。FaceManager 决定门开"
             "不开，而它此前从未被链接进任何测试目标 —— 探针已证实未训练的 "
             "LBPH predict() 会抛 cv::Exception，异常逃出 UI 事件循环即终止进程。")
        return

    if os.path.exists(cm):
        c = read(cm)
        for needle, why in (("test_face_manager.cpp", "测试源文件未链接"),
                            ("managers/face_manager.cpp", "被测的生产实现未链接")):
            if needle not in c:
                fail("[face-gate] tests/CMakeLists.txt 缺少 " + needle
                     + "（" + why + "）—— 写了但不会跑，等于没有。")

    t = read(tf)

    # "唯一判据"这条断言必须存在。
    # 用词元边界而非子串：改名成 "...SingleLabel_removed()" 会躲过子串检查，
    # 因为原名是改后名的前缀（故障注入实测抓到了这一点）。
    if "thresholdIsTheOnlyGateWithSingleLabel(" not in t:
        fail("[face-gate] 门禁测试里没有『阈值是唯一判据』的断言。探针已证实"
             "单 label 时 predictedLabel == 1 恒为真，因此 confidence < "
             "threshold 是**唯一的门**；丢了这条断言，门禁安全就没人守。")

    # 隐患必须被显式记录，而不是被默默"修好"。
    # 同上：要求**完整符号名**，改短名即消失。
    if "samplesWithoutTrainingMakeRecognizeThrow_documentedHazard" not in t:
        fail("[face-gate] 门禁测试没有记录『样本填满但未训练时 recognize() 抛"
             "异常』这一隐患。该路径当前不可达（widget.cpp 填满即 train()），"
             "但一旦有人加了别的调用路径就会终止进程。必须显式钉住现状，"
             "使『是否改为检查模型训练状态』成为一个显式决定。")

    if not os.path.exists(fx):
        fail("[face-gate] 缺少 tools/verify_face_manager_test.py —— 没有故障注入"
             "就无法证明这些门禁断言**真的会失败**。不失败的回归测试没有价值。")

    # 阈值没有范围约束 -> 告警（安全相关，但属行为变化，需单独决定）。
    cfg = os.path.join(src_root, "config", "app_config.cpp")
    if os.path.exists(cfg):
        ctext = read(cfg)
        if "faceConfidenceThreshold" in ctext:
            clamped = re.search(
                r"qBound|std::clamp|std::min|std::max|qMax|qMin", ctext)
            if not clamped:
                warn("[face-gate] behavior.face_confidence_threshold 没有任何范围"
                     "约束，而探针证实**门禁安全完全取决于它**（单 label 时"
                     "predictedLabel == 1 恒真）。配置成 1e9 会让任何陌生人像都"
                     "判『通过』，门锁形同虚设；误配置成 900（少写一个 0）会"
                     "静默失去门禁作用。是否加约束属行为变化，需单独决定 —— "
                     "当前仅告警。")



def check_cross_repo_test_targets_are_unique(root, extra_root):
    """
    两个仓库的测试目标名必须互不冲突，否则**超级工程无法配置**。

    背景（真实缺陷，本轮修复）：
    门口机与室内机各自有 tests/CMakeLists.txt，目标名原本都是 test_protocol、
    test_app_config。单独构建时看不出问题，但把两个仓库作为子目录放进同一个
    CMake 工程（跨仓库集成、或 IDE 一次性载入）时，CMake 直接报错：

        add_executable cannot create target "test_protocol" because another
        target with the same name already exists.

    实测：修复前 configure_rc=1，两个 add_executable 全都失败；加仓库前缀后
    5/5 用例通过。ctest 的**用例名**同理（add_test(NAME ...)）：重名会让
    `ctest -R` 一次选中两个，输出也难以区分。

    判定规则：分别收集两个仓库 tests/ 下的 add_executable 与 add_test 名字，
    有交集即报错。
    """
    if not extra_root:
        return
    roots = [("本仓库", root),
             ("另一仓库", os.path.abspath(extra_root))]

    collected = {}
    for label, repo in roots:
        p = os.path.join(repo, "tests", "CMakeLists.txt")
        if not os.path.isfile(p):
            continue
        text = strip_comments_and_strings(read(p))
        collected[label] = (
            set(re.findall(r'add_executable\s*\(\s*([\w.-]+)', text)),
            set(re.findall(r'add_test\s*\(\s*NAME\s+([\w.-]+)', text)))

    if len(collected) < 2:
        return

    items = list(collected.items())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            la, (ta, ca) = items[i]
            lb, (tb, cb) = items[j]
            dup_t = ta & tb
            if dup_t:
                fail("[cross-target] {} 与 {} 的测试可执行目标重名: {}。"
                     "把两个仓库放进同一个 CMake 工程时会直接配置失败"
                     "（add_executable cannot create target ...）。"
                     "请给目标名加仓库前缀（如 t113_/desktop_）。"
                     .format(la, lb, ", ".join(sorted(dup_t))))
            dup_c = ca & cb
            if dup_c:
                fail("[cross-target] {} 与 {} 的 ctest 用例名重名: {}。"
                     "重名会让 ctest -R 一次选中两个、输出难以区分。"
                     "请给用例名加仓库前缀。".format(la, lb, ", ".join(sorted(dup_c))))

def main():
    if len(sys.argv) < 2:
        print("用法: python verify.py <项目根目录> [另一仓库根目录]")
        return 2
    root = os.path.abspath(sys.argv[1])
    src_root = os.path.join(root, "src")
    if not os.path.isdir(src_root):
        print(f"找不到 src 目录: {src_root}")
        return 2

    check_includes(root, src_root)
    check_build_lists(root, src_root)
    check_subproject_cmake_is_selfcontained(root, src_root)
    check_qrc(root, src_root)
    check_ui_objectnames(root, src_root)
    check_balance(root, src_root)
    check_legacy_identifiers(root, src_root)
    check_qt5_portability(root, src_root)
    check_forward_declarations(root, src_root)
    check_media_gated_by_answer(root, src_root)
    check_deleted_on_close_members(root, src_root)
    check_unqueued_poll_timers(root, src_root)
    check_blocking_poll_has_handle(root, src_root)
    check_datagram_read_returns(root, src_root)
    check_connect_signal_is_signal(root, src_root)
    check_json_configs(root)
    check_config_value_sanity(root, src_root)
    check_config_knobs_are_used(root, src_root)
    check_declared_signal_is_emitted(root, src_root)
    check_abandoned_async_tasks(root, src_root)
    check_hex_parse_is_validated(root, src_root)
    check_load_state_reset(root, src_root)
    check_narrowing_cast_of_config(root, src_root)
    check_wire_format_constants_are_pinned(root, src_root)
    check_nonblock_pcm_handles_eagain(root, src_root)
    check_fingerprint_ack_tag_is_validated(root, src_root)
    check_signalspy_types_are_registered(root, src_root)
    check_declared_slot_is_reachable(root, src_root)
    check_live_fingerprint_enroll_sequence_is_pinned(root, src_root)
    check_coverage_denominator_is_declared(root, src_root)
    check_tool_scripts_are_console_encoding_safe(root, src_root)
    check_coverage_separates_dead_from_untested(root, src_root)
    check_password_log_regression_is_enforced(root, src_root)
    check_gpio_failure_paths_are_testable(root, src_root)
    check_face_gate_hazard_is_documented(root, src_root)
    check_fake_fingerprint_builds_same_bytes(root, src_root)
    check_fingerprint_checksum_logic_is_not_duplicated(root, src_root)
    check_gated_wire_paths_have_resume_test(root, src_root)
    check_cross_repo_test_targets_are_unique(
        root, sys.argv[2] if len(sys.argv) > 2 else None)

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
