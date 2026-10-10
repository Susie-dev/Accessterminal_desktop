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
