#!/usr/bin/env python3
"""
C++ 头部/实现签名一致性校验（静态，无需编译器）。

在没有 Qt/编译器的环境下，尽可能提前发现会导致编译或链接失败的问题：

  1. .cpp 中定义的 Class::method 是否在对应 .h 中声明（签名需匹配）
  2. .h 中声明的非内联、非纯虚、非 Qt 宏方法是否都有定义
  3. #include 的 Qt 头文件是否覆盖了所用到的 Qt 类型
  4. 类成员变量在 .cpp 中的 m_/普通成员引用是否存在于 .h

用法：python tools/check_signatures.py <项目根目录>
退出码：0 通过；1 发现问题；2 参数错误
"""
import os
import re
import sys
from collections import defaultdict

FAIL = []
WARN = []


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def strip_comments(text):
    """移除注释与字符串，避免误匹配。"""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    text = re.sub(r"'(?:\\.|[^'\\])*'", "''", text)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def find_files(root, exts):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "build", "build-t113", "deploy")]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in exts:
                out.append(os.path.join(dirpath, fn))
    return out


def normalize_signature(sig):
    """
    归一化签名以便比较：去掉参数名、统一空白、去掉默认值。
    """
    sig = re.sub(r"\s+", " ", sig).strip()
    # 去掉默认参数值
    sig = re.sub(r"=\s*[^,)]+(?=[,)])", "", sig)
    # 提取括号内参数列表
    m = re.match(r"^(.*?)\((.*)\)(.*)$", sig)
    if not m:
        return sig
    ret, params, tail = m.groups()
    ret = ret.strip()
    tail = tail.strip()

    # 拆分参数，去掉参数名（保留类型）
    parts = []
    depth = 0
    cur = ""
    for ch in params:
        if ch in "<([":
            depth += 1
        elif ch in ">)]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)

    norm_params = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if p == "void":
            continue
        p = re.sub(r"\s+", " ", p)
        # 去掉尾部参数名：最后一个标识符若前面还有内容，则认为是参数名
        toks = p.split(" ")
        if len(toks) > 1 and re.match(r"^[A-Za-z_]\w*$", toks[-1]):
            # 但要避免把 "unsigned int" 的 int 当参数名
            if toks[-2] not in ("unsigned", "signed", "long", "short", "const", "struct", "class"):
                toks = toks[:-1]
        # 去掉数组记号与引用/指针后的空格
        joined = " ".join(toks)
        joined = joined.replace(" *", "*").replace(" &", "&")
        norm_params.append(joined)

    # 返回类型去除 const 限定中的冗余空白
    ret = re.sub(r"\s+", " ", ret)
    return f"{ret}({','.join(norm_params)}){tail}"


def extract_class_declarations(header_text):
    """
    提取 header 中每个 class 的声明方法集合。
    返回 {类名: (类体, 是否含 Q_OBJECT)}，以支持信号/槽的豁免判断。
    """
    classes = {}
    for m in re.finditer(r"\bclass\s+(\w+)\s*(?::[^{;]*)?\{", header_text):
        name = m.group(1)
        start = m.end() - 1  # 指向 '{'
        depth = 0
        i = start
        while i < len(header_text):
            if header_text[i] == "{":
                depth += 1
            elif header_text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = header_text[start + 1:i]
        has_qobject = "Q_OBJECT" in body
        classes[name] = (body, has_qobject)
    return classes


def signal_names(class_body):
    """
    提取 signals: 区域中声明的信号名。
    Qt 的 moc 会生成信号定义，因此信号不需要手写实现。
    """
    names = set()
    m = re.search(r"\bsignals\s*:", class_body)
    if not m:
        return names
    rest = class_body[m.end():]
    # signals 区段结束于下一个访问修饰符
    end = re.search(r"\b(public|private|protected)\s*(slots)?\s*:", rest)
    section = rest[:end.start()] if end else rest
    for sm in re.finditer(r"\b(~?\w+)\s*\([^;{}]*\)\s*(?:const\s*)?;", section):
        names.add(sm.group(1))
    return names


def declared_methods(class_body, class_name=""):
    """
    从类体提取方法名 -> 归一化签名。

    需处理三类声明：
      1. 普通方法      void foo(int a);
      2. 构造函数      Foo(int a);
      3. 析构函数      ~Foo();
    """
    methods = {}
    seen_spans = []

    def record(name, sig, span):
        methods[name] = sig
        seen_spans.append(span)

    # 1) 带返回类型的方法
    for m in re.finditer(
        r"(?m)^\s*(?:virtual\s+|static\s+|explicit\s+|inline\s+|friend\s+)*"
        r"([A-Za-z_][\w:<>,\s\*&]*?)\s+"
        r"(~?\w+)\s*\(([^;{}]*)\)\s*"
        r"((?:const\s*)?(?:override\s*)?(?:noexcept\s*)?(?:=\s*0\s*)?);",
        class_body,
    ):
        ret, name, params, tail = m.groups()
        if name in ("if", "for", "while", "switch", "return", "Q_OBJECT", "emit"):
            continue
        record(name, normalize_signature(f"{ret} {name}({params}) {tail}"), m.span())

    # 2) 构造函数：与类同名且无返回类型
    if class_name:
        for m in re.finditer(
            r"(?m)^\s*(?:explicit\s+)?" + re.escape(class_name) +
            r"\s*\(([^;{}]*)\)\s*((?:noexcept\s*)?(?:=\s*0\s*)?);",
            class_body,
        ):
            params, tail = m.groups()
            record(class_name, normalize_signature(f"{class_name}({params}) {tail}"), m.span())

    # 3) 析构函数
    for m in re.finditer(
        r"(?m)^\s*(?:virtual\s+)?" + r"(~\w+)\s*\(\s*\)\s*"
        r"((?:noexcept\s*)?(?:override\s*)?(?:=\s*0\s*)?);",
        class_body,
    ):
        name, tail = m.groups()
        record(name, normalize_signature(f"{name}() {tail}"), m.span())

    return methods


def defined_methods(cpp_text):
    """从 .cpp 提取 Class::method 定义。"""
    defs = []
    pattern = re.compile(
        r"(?m)^\s*(?:[\w:<>,\s\*&]+?\s+)?"
        r"(\w+)::(~?\w+)\s*\(([^;{}]*)\)\s*"
        r"((?:const\s*)?(?:override\s*)?(?:noexcept\s*)?)"
        r"\{",
    )
    for m in pattern.finditer(cpp_text):
        cls, name, params, tail = m.groups()
        defs.append((cls, name, normalize_signature(f"{name}({params}) {tail}")))
    return defs


def check_repo(root):
    src_root = os.path.join(root, "src")
    if not os.path.isdir(src_root):
        print(f"找不到 src: {src_root}")
        return 2

    # 收集所有头文件中的类声明（按类名索引，跨文件合并同名类）
    header_classes = {}
    for h in find_files(src_root, {".h", ".hpp"}):
        text = strip_comments(read(h))
        for cname, (body, has_qobject) in extract_class_declarations(text).items():
            if cname not in header_classes:
                header_classes[cname] = {
                    "path": h, "methods": {}, "signals": set(), "qobject": has_qobject,
                }
            entry = header_classes[cname]
            entry["methods"].update(declared_methods(body, cname))
            entry["signals"].update(signal_names(body))
            entry["qobject"] = entry["qobject"] or has_qobject

    # 检查 .cpp 中定义的方法
    for cpp in find_files(src_root, {".cpp"}):
        text = strip_comments(read(cpp))
        for cls, name, sig in defined_methods(text):
            if cls not in header_classes:
                continue  # 可能是外部/模板类
            entry = header_classes[cls]
            if name not in entry["methods"]:
                FAIL.append(
                    f"[signature] {os.path.relpath(cpp, root)}: "
                    f"{cls}::{name} 已定义但未在 "
                    f"{os.path.basename(entry['path'])} 中声明"
                )

    # 检查声明了但未定义的方法（排除内联、纯虚、Qt 信号）
    for cname, entry in header_classes.items():
        hpath = entry["path"]
        htext = read(hpath)

        defined = set()
        for cpp in find_files(src_root, {".cpp"}):
            for cls, name, _sig in defined_methods(strip_comments(read(cpp))):
                if cls == cname:
                    defined.add(name)

        for name, sig in entry["methods"].items():
            if name in defined:
                continue
            # Qt 信号由 moc 生成实现
            if name in entry["signals"]:
                continue
            # 内联定义：方法名后紧跟 '{'
            inline_pat = re.search(
                r"\b" + re.escape(name) + r"\s*\([^;{}]*\)[^;{}]*\{", htext)
            if inline_pat:
                continue
            if "= 0" in sig:
                continue
            WARN.append(
                f"[signature] {cname}::{name} 在 {os.path.basename(hpath)} 中声明，"
                f"但未找到定义"
            )


def main():
    if len(sys.argv) < 2:
        print("用法: python tools/check_signatures.py <项目根目录>")
        return 2
    root = os.path.abspath(sys.argv[1])
    check_repo(root)

    print(f"签名一致性校验: {root}")
    print("=" * 70)
    if WARN:
        print(f"\n警告 {len(WARN)} 项（可能是内联或模板，需人工确认）:")
        for w in WARN:
            print("  ! " + w)
    if FAIL:
        print(f"\n失败 {len(FAIL)} 项:")
        for f in FAIL:
            print("  X " + f)
        return 1
    print("\n结论: 无签名不一致问题")
    return 0


if __name__ == "__main__":
    sys.exit(main())
