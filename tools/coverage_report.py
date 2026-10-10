# -*- coding: utf-8 -*-
"""覆盖率报告器（gcov 直读，不依赖 lcov/gcovr）。

为什么要它
----------
前 23 轮我能说"T113 9/9、桌面 3/3 通过"，但**从未量化过这些测试到底执行了
多少产线代码**。第 21/23 轮的教训（"有测试 ≠ 被测到"、"被测对象不在执行
路径上"）说明：用例数量与绿灯数都不是覆盖度证据。

本机只有 gcov（GCC 16.2.0），没有 lcov/gcovr/genhtml，所以直接解析
`gcov -j -t` 的 JSON v2 输出。

口径说明（重要，避免自欺）
  - 只统计**本仓库 src/ 下**的文件；Qt 头文件、标准库头文件一律排除。
    否则模板实例化会把覆盖率数字稀释到无意义。
  - 同一文件会被链接进多个测试目标（如 app_config.cpp 出现在 6 个目标里），
    每个目标各有一份 .gcda。按行取**所有目标的最大命中数**合并 —— 这正是
    "整套测试合起来覆盖了什么"的口径。
  - 只统计可执行行（gcov 给出的 line 记录）；`block_ids: []` 的纯声明行
    gcov 也算，但其 count 无意义，故跳过。

用法：
  coverage_report.py <repo_root> --build <dir> [--build <dir2>] [--json out.json] [--quiet]
"""
from __future__ import print_function

import glob
import io
import json
import os
import subprocess
import sys


def run_gcov(gcda, gcov_bin):
    """跑 gcov -j -t，返回解析后的 JSON（失败返回 None）。"""
    try:
        p = subprocess.run([gcov_bin, "-j", "-t", "-b", gcda],
                           capture_output=True)
    except Exception:
        return None
    if p.returncode != 0:
        return None
    out = p.stdout
    # 某些 gcov 版本会在 JSON 前后混入提示行，从第一个 { 开始截取
    i = out.find(b"{")
    if i < 0:
        return None
    try:
        return json.loads(out[i:].decode("utf-8", "replace"))
    except Exception:
        return None


def collect(repo_root, build_dir, gcov_bin):
    """build_dir 可以是单个目录，也可以是目录列表（把互操作等独立工程一起算）。"""
    src_root = os.path.join(repo_root, "src")
    # 文件 -> {行号: 最大命中数}
    lines = {}
    seen_gcda = set()
    gcda_list = []
    for bd in (build_dir if isinstance(build_dir, list) else [build_dir]):
        gcda_list += glob.glob(os.path.join(bd, "**", "*.gcda"), recursive=True)
    for gcda in gcda_list:
        real = os.path.realpath(gcda)
        if real in seen_gcda:
            continue
        seen_gcda.add(real)
        data = run_gcov(gcda, gcov_bin)
        if not data:
            continue
        for fobj in data.get("files", []):
            fname = os.path.normpath(fobj.get("file", ""))
            if not fname.startswith(os.path.normpath(src_root)):
                continue
            rel = os.path.relpath(fname, repo_root)
            bucket = lines.setdefault(rel, {})
            for ln in fobj.get("lines", []):
                if not ln.get("block_ids"):
                    continue          # 纯声明行，命中数无意义
                n = ln.get("line_number")
                c = ln.get("count", 0)
                if n is None:
                    continue
                if c > bucket.get(n, -1):
                    bucket[n] = c
    return lines


def summarize(lines):
    rows = []
    for rel, ln in sorted(lines.items()):
        total = len(ln)
        hit = sum(1 for c in ln.values() if c > 0)
        miss = [n for n, c in sorted(ln.items()) if c == 0]
        rows.append({
            "file": rel.replace("\\", "/"),
            "lines": total,
            "covered": hit,
            "pct": (100.0 * hit / total) if total else 100.0,
            "uncovered_lines": miss,
        })
    return rows


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    repo_root = os.path.abspath(sys.argv[1])
    # 构建目录用**可重复的 --build 标志**给出，例如：
    #   coverage_report.py <repo> --build /tmp/tests --build /tmp/interop
    # 不用 ';' 分隔：MSYS/git-bash 会把含分隔符的参数当路径列表做转换
    # （实测报 "Is a directory"），且 Windows 的 os.pathsep 与 MSYS 的 ':' 冲突。
    build_dir = []
    rest = sys.argv[2:]
    i = 0
    while i < len(rest):
        if rest[i] == "--build" and i + 1 < len(rest):
            build_dir.append(os.path.abspath(rest[i + 1]))
            i += 2
            continue
        if build_dir == [] and not rest[i].startswith("--"):
            # 兼容旧式第二个位置参数
            build_dir.append(os.path.abspath(rest[i]))
        i += 1
    quiet = "--quiet" in rest
    json_out = None
    if "--json" in rest:
        json_out = rest[rest.index("--json") + 1]
    if not build_dir:
        print(__doc__)
        return 2

    src_root = os.path.join(repo_root, "src")
    gcov_bin = os.environ.get("GCOV", "gcov")
    lines = collect(repo_root, build_dir, gcov_bin)
    if not lines:
        print("未找到任何 src/ 覆盖率数据（build_dir=%s）"
              % ", ".join(build_dir))
        print("提示：需用 -DCMAKE_CXX_FLAGS='--coverage -O0 -g' 配置并跑过测试。")
        return 1

    rows = summarize(lines)
    tot_l = sum(r["lines"] for r in rows)
    tot_c = sum(r["covered"] for r in rows)
    overall = (100.0 * tot_c / tot_l) if tot_l else 0.0

    if not quiet:
        print("=" * 78)
        print("产线代码行覆盖率（仅 src/，同一文件多目标取最大命中）")
        print("=" * 78)
        print("%-52s %7s %7s %7s" % ("文件", "可执行行", "已覆盖", "覆盖率"))
        print("-" * 78)
        for r in sorted(rows, key=lambda x: (x["pct"], x["file"])):
            print("%-52s %7d %7d %6.1f%%" % (
                r["file"][:52], r["lines"], r["covered"], r["pct"]))
        print("-" * 78)
        print("%-52s %7d %7d %6.1f%%" % ("合计", tot_l, tot_c, overall))

        zero = [r for r in rows if r["covered"] == 0 and r["lines"] > 0]
        if zero:
            print()
            print("产线文件已链接进测试、但一行都没执行（%d 个）：" % len(zero))
            for r in zero:
                print("   %s  (%d 行)" % (r["file"], r["lines"]))

        # 最重要的输出：根本没被测过的产线文件。
        # 上面的百分比只统计"被测到的文件"，未被任何测试目标链接的文件不会
        # 出现在 gcov 数据里 —— 不显式列出来，"94% 覆盖率"就会被误读成
        # "产线代码几乎都被测过"。
        linked = set(lines.keys())
        allsrc = []
        for dp, dn, fn in os.walk(src_root):
            for f in fn:
                if f.endswith((".cpp", ".h", ".hpp")):
                    rel = os.path.relpath(os.path.join(dp, f), repo_root)
                    allsrc.append(rel.replace("\\", "/"))
        unlinked = sorted(x for x in allsrc
                          if x not in {r["file"] for r in rows})
        if unlinked:
            print()
            print("从未被任何测试目标链接的产线源文件（%d 个）：" % len(unlinked))
            for x in unlinked:
                print("   %s" % x)
            print()
            # 用与 gcov 同口径的近似值把未测文件折进分母，给出一个
            # **不会自我美化**的总覆盖率。近似可执行行 = 非空、非注释行。
            approx = 0
            for rel in unlinked:
                fp = os.path.join(repo_root, rel.replace("/", os.sep))
                try:
                    txt = io.open(fp, encoding="utf-8",
                                  errors="replace").read()
                except Exception:
                    continue
                for line in txt.split("\n"):
                    t = line.strip()
                    if not t or t.startswith("//") or t.startswith("/*") \
                            or t.startswith("*"):
                        continue
                    approx += 1
            denom = tot_l + approx
            real = (100.0 * tot_c / denom) if denom else 0.0
            print("   覆盖率分母不含这些文件，故上表总百分比只描述"
                  "被测到的那部分。")
            print()
            print("   【不自我美化的总覆盖率】把未测文件按近似可执行行折进分母：")
            print("       已测文件 %d 行（覆盖 %d）+ 未测文件约 %d 行 = 分母 %d"
                  % (tot_l, tot_c, approx, denom))
            print("       近似总覆盖率 = %.1f%%   （上表那个 %.1f%% 仅描述"
                  "已测文件）" % (real, overall))

    if json_out:
        with io.open(json_out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({
                "overall_pct": round(overall, 2),
                "total_lines": tot_l,
                "covered_lines": tot_c,
                "files": rows,
            }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
