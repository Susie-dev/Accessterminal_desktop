# -*- coding: utf-8 -*-
"""check_nonblock_pcm_handles_eagain 的故障注入自检（两仓库通用）。

用法: verify_nonblock_pcm.py <verify.py> <本仓库根>

自足设计：不再依赖本仓库里恰好存在某个 .cpp。真阳性/真阴性用例都在临时
仓库副本里**新建**合成源文件来构造，因此桌面端（目前完全没有 ALSA 代码）
也能得到有意义的自检。

合成夹具覆盖规则最容易判错的两点：
  - 必须按**函数体**判定，不能整文件判定（同文件别处有 EAGAIN 不算数）
  - 函数体判定必须扛得住头部含分号的多行 for（第 18 轮真实踩过的坑）
"""
import importlib.util
import os
import shutil
import sys
import tempfile

VERIFY = os.path.abspath(sys.argv[1])
REPO = os.path.abspath(sys.argv[2])
FAILED = 0
TOTAL = 0

MEDIA = os.path.join("src", "core", "media")


def load():
    spec = importlib.util.spec_from_file_location("v", VERIFY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def safe_copytree(src, dst):
    """拷贝仓库做变形；跳过不稳定/不可读的目录。"""
    def ig(_d, names):
        drop = set()
        for n in names:
            if n in (".git", "build") or n.startswith("build-"):
                drop.add(n)
        return drop
    shutil.copytree(src, dst, ignore=ig)


def run_case(name, expect_fail, build):
    global FAILED, TOTAL
    TOTAL += 1
    tmp = tempfile.mkdtemp(prefix="nb_")
    try:
        root = os.path.join(tmp, "repo")
        safe_copytree(REPO, root)
        build(root)
        m = load()
        m.FAIL.clear()
        m.WARN.clear()
        m.check_nonblock_pcm_handles_eagain(root, os.path.join(root, "src"))
        got = len(m.FAIL) > 0
        ok = got == expect_fail
        print("  [{}] {}  (fail={}, 期望fail={})".format(
            "PASS" if ok else "FAIL", name, got, expect_fail))
        if not ok:
            FAILED += 1
            for x in m.FAIL[:3]:
                print("        -> " + x[:170])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_fixture(root, name, body):
    d = os.path.join(root, MEDIA)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    return p


# --- 合成夹具 ---------------------------------------------------------------

# 合规：非阻塞打开 + 区分 EAGAIN，且调用点包在"头部含分号的多行 for"里
GOOD = """#include <alsa/asoundlib.h>
void good_play(snd_pcm_t* h) {
    snd_pcm_open(&h, "default", SND_PCM_STREAM_PLAYBACK, SND_PCM_NONBLOCK);
    for (int attempt = 0; attempt < 3; ++attempt) {
        int rc = snd_pcm_writei(h, 0, 320);
        if (rc == -EAGAIN || rc == -EWOULDBLOCK) {
            break;
        }
    }
}
"""

# 不合规：非阻塞打开，但只特判 -EPIPE，其余负值当致命
BAD_NO_EAGAIN = """#include <alsa/asoundlib.h>
void bad_play(snd_pcm_t* h) {
    snd_pcm_open(&h, "default", SND_PCM_STREAM_PLAYBACK, SND_PCM_NONBLOCK);
    int rc = snd_pcm_writei(h, 0, 320);
    if (rc == -EPIPE) {
        snd_pcm_prepare(h);
    } else if (rc < 0) {
        return;
    }
}
"""

# 不合规：EAGAIN 只出现在同文件的**另一个函数**里
BAD_EAGAIN_ELSEWHERE = """#include <alsa/asoundlib.h>
void helper(void) { int e = EAGAIN; (void)e; }
void bad_play2(snd_pcm_t* h) {
    snd_pcm_open(&h, "default", SND_PCM_STREAM_PLAYBACK, SND_PCM_NONBLOCK);
    int rc = snd_pcm_writei(h, 0, 320);
    if (rc < 0) {
        return;
    }
}
"""

# 合规：阻塞打开，不需要处理 EAGAIN
GOOD_BLOCKING = """#include <alsa/asoundlib.h>
void blocking_play(snd_pcm_t* h) {
    snd_pcm_open(&h, "default", SND_PCM_STREAM_PLAYBACK, 0);
    int rc = snd_pcm_writei(h, 0, 320);
    if (rc < 0) {
        return;
    }
}
"""


def add_good(root):
    write_fixture(root, "probe_good.cpp", GOOD)


def add_bad(root):
    write_fixture(root, "probe_bad.cpp", BAD_NO_EAGAIN)


def add_bad_elsewhere(root):
    write_fixture(root, "probe_bad2.cpp", BAD_EAGAIN_ELSEWHERE)


def add_good_blocking(root):
    write_fixture(root, "probe_blocking.cpp", GOOD_BLOCKING)


def remove_all_synth(root):
    """真阴性：本仓库真实源码本身必须通过（清掉可能的合成干扰）。"""
    d = os.path.join(root, MEDIA)
    for n in ("probe_good.cpp", "probe_bad.cpp", "probe_bad2.cpp",
              "probe_blocking.cpp"):
        p = os.path.join(d, n)
        if os.path.exists(p):
            os.remove(p)


print("== check_nonblock_pcm_handles_eagain 故障注入自检 ==")
run_case("当前仓库(真阴性)", False, remove_all_synth)
run_case("非阻塞但不处理 EAGAIN，且调用在含分号的 for 内(真阳性)",
         True, add_bad)
run_case("EAGAIN 只在同文件别的函数里(真阳性)", True, add_bad_elsewhere)
run_case("合规样例不得被误报(真阴性)", False, add_good)
run_case("阻塞打开则无需处理 EAGAIN(真阴性)", False, add_good_blocking)

# 真实仓库必须通过（不带任何合成夹具）
TOTAL += 1
m = load()
m.FAIL.clear()
m.check_nonblock_pcm_handles_eagain(REPO, os.path.join(REPO, "src"))
ok = len(m.FAIL) == 0
print("  [{}] 真实仓库实测  (fail={})".format("PASS" if ok else "FAIL", len(m.FAIL)))
if not ok:
    FAILED += 1
    for x in m.FAIL[:3]:
        print("        -> " + x[:170])

print("\n结果: {}/{} 通过".format(TOTAL - FAILED, TOTAL))
sys.exit(1 if FAILED else 0)
