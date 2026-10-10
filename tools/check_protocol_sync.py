#!/usr/bin/env python3
"""
跨仓库协议一致性校验。

protocol.h 在 Accessterminal_T113（门口机）与 Accessterminal_desktop
（室内机）中各存一份，两侧必须逐字节一致。本脚本用于在提交前、
CI 中或联调前快速确认这一点。

用法：
    python tools/check_protocol_sync.py <repo_a> <repo_b>
    python tools/check_protocol_sync.py                 # 用默认的两个仓库路径

退出码：0 一致；1 不一致；2 参数/路径错误。
"""
import hashlib
import os
import re
import sys

REL_PATH = os.path.join("src", "core", "net", "protocol.h")

# 两个仓库的默认位置（相对于本仓库根目录的上一级）
DEFAULT_REPOS = ["Accessterminal_T113", "Accessterminal_desktop"]

# 必须存在的协议常量及其期望值：防止"两边都改错"却依然一致。
REQUIRED_CONSTANTS = {
    "kProtocolVersion": 1,
    "kSignalingPort": 8887,
    "kAudioPort": 12345,
    "kVideoPort": 23456,
    "kPreviewPort": 50000,
    "kAudioSampleRate": 16000,
    "kAudioChannels": 1,
    "kAudioBytesPerSample": 2,
    "kAudioFramesPerPacket": 320,
    "kAudioBytesPerPacket": 640,
}

# 必须存在的信令字符串
REQUIRED_SIGNALS = ["call", "accept", "recstop", "unlock", "stopsend", "getframe", "stop"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def check_constants(path, text):
    """校验常量名与取值。"""
    problems = []
    for name, expected in REQUIRED_CONSTANTS.items():
        m = re.search(
            r"constexpr\s+\w+\s+" + re.escape(name) + r"\s*=\s*([^;]+);", text)
        if not m:
            problems.append(f"缺少常量 {name}")
            continue
        value_text = m.group(1).strip()
        # kAudioBytesPerPacket 是表达式，只校验可解析为整数的那些
        if name == "kAudioBytesPerPacket":
            continue
        try:
            actual = int(value_text, 0)
        except ValueError:
            problems.append(f"{name} 取值无法解析为整数: {value_text}")
            continue
        if actual != expected:
            problems.append(f"{name} = {actual}，期望 {expected}")

    # inline variable 需要 C++17，本工程为 C++11
    if re.search(r"^\s*inline\s+(constexpr|const)\s", text, re.M):
        problems.append("protocol.h 使用了 inline 变量（需要 C++17，本工程为 C++11）")

    for sig in REQUIRED_SIGNALS:
        if f'"{sig}"' not in text:
            problems.append(f"缺少信令字符串 \"{sig}\"")
    return problems


def main():
    if len(sys.argv) == 3:
        repo_a, repo_b = sys.argv[1], sys.argv[2]
    elif len(sys.argv) == 1:
        parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # 本脚本位于 <repo>/tools/ 下，其上一级即两个仓库的共同父目录
        parent = os.path.dirname(parent)
        repo_a = os.path.join(parent, DEFAULT_REPOS[0])
        repo_b = os.path.join(parent, DEFAULT_REPOS[1])
    else:
        print("用法: python tools/check_protocol_sync.py [<repo_a> <repo_b>]")
        return 2

    path_a = os.path.join(repo_a, REL_PATH)
    path_b = os.path.join(repo_b, REL_PATH)

    for p in (path_a, path_b):
        if not os.path.isfile(p):
            print(f"找不到 protocol.h: {p}")
            return 2

    text_a, text_b = read(path_a), read(path_b)
    hash_a, hash_b = sha256(path_a), sha256(path_b)

    ok = True
    print("跨仓库协议一致性校验")
    print("=" * 68)
    print(f"A: {path_a}")
    print(f"    SHA256 {hash_a}")
    print(f"B: {path_b}")
    print(f"    SHA256 {hash_b}")

    if hash_a == hash_b:
        print("\n[OK] 两份 protocol.h 逐字节一致")
    else:
        print("\n[X] 两份 protocol.h 内容不一致！")
        # 给出首个差异行，便于定位
        lines_a = text_a.splitlines()
        lines_b = text_b.splitlines()
        for i in range(max(len(lines_a), len(lines_b))):
            la = lines_a[i] if i < len(lines_a) else "<缺失>"
            lb = lines_b[i] if i < len(lines_b) else "<缺失>"
            if la != lb:
                print(f"    首个差异在第 {i + 1} 行：")
                print(f"      A: {la}")
                print(f"      B: {lb}")
                break
        ok = False

    # 即使两侧一致，也要确认取值正确
    for label, path, text in (("A", path_a, text_a), ("B", path_b, text_b)):
        problems = check_constants(path, text)
        if problems:
            ok = False
            print(f"\n[X] {label} 的协议常量有问题:")
            for p in problems:
                print(f"      - {p}")

    print()
    if ok:
        print("结论: 协议契约一致且取值正确")
        return 0
    print("结论: 存在问题，请同步两侧 protocol.h")
    return 1


if __name__ == "__main__":
    sys.exit(main())
