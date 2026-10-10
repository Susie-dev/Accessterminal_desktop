# -*- coding: utf-8 -*-
"""对第 32 轮新增的 check_weather_service_contract_is_pinned 做故障注入自检。"""
import io
import os
import re
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

D = r'C:\Users\user\Desktop\linux_ai\Accessterminal_desktop'
T = r'C:\Users\user\Desktop\linux_ai\Accessterminal_T113'
PY = r'C:\Users\user\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
VERIFY = os.path.join(D, 'tools', 'verify.py')
WS = os.path.join(D, 'src', 'core', 'weather', 'weather_service.cpp')
WSH = os.path.join(D, 'src', 'core', 'weather', 'weather_service.h')


def read(p):
    return io.open(p, encoding='utf-8', errors='replace').read()


_ORIG = {p: read(p) for p in (WS, WSH)}


def sub(p, old, new, count=1):
    s = _ORIG[p]
    n = s.count(old)
    if n != count:
        raise AssertionError('%s 锚点出现 %d 次（期望 %d）: %r'
                             % (os.path.basename(p), n, count, old[:60]))
    return s.replace(old, new, count)


MUT = [
    # 顺序契约
    ("去掉 disconnect（abort 会同步重入）",
     WS, '    disconnect(reply, nullptr, this, nullptr);\n', ''),

    ("不摘除成员 m_reply",
     WS, '    m_reply = nullptr; // 先摘除成员，后续重入也看不到它\n', ''),

    ("不调用 abort()",
     WS, '    reply->abort();\n', ''),

    ("abort 提到最前（先 abort 再 disconnect/摘成员）",
     WS,
     '    QNetworkReply* reply = m_reply;\n'
     '    m_reply = nullptr; // 先摘除成员，后续重入也看不到它\n'
     '    disconnect(reply, nullptr, this, nullptr);\n'
     '    reply->abort();\n',
     '    QNetworkReply* reply = m_reply;\n'
     '    reply->abort();\n'
     '    m_reply = nullptr; // 先摘除成员，后续重入也看不到它\n'
     '    disconnect(reply, nullptr, this, nullptr);\n'),

    # 析构
    ("析构不丢弃在途请求",
     WS, 'WeatherService::~WeatherService()\n{\n    abandonReply();\n}',
     'WeatherService::~WeatherService()\n{\n}'),

    # 文案
    ("文案丢了『今日天气』",
     WS, 'QStringLiteral("%1，今日天气%2，\\n高温%3，低温%4，\\n%5\\n每日提醒：%6")',
     'QStringLiteral("%1，%2，\\n高温%3，低温%4，\\n%5\\n每日提醒：%6")'),

    ("文案丢了『每日提醒：』",
     WS, 'QStringLiteral("%1，今日天气%2，\\n高温%3，低温%4，\\n%5\\n每日提醒：%6")',
     'QStringLiteral("%1，今日天气%2，\\n高温%3，低温%4，\\n%5\\n%6")'),

    ("文案 arg 顺序接错（high/low 互换）",
     WS, '.arg(city, type, high, low, wind, notice);',
     '.arg(city, type, low, high, wind, notice);'),

    ("文案 arg 顺序接错（type/wind 互换）",
     WS, '.arg(city, type, high, low, wind, notice);',
     '.arg(city, wind, high, low, type, notice);'),

    # 边界
    ("去掉 url 空判断",
     WS, '    if (url.isEmpty()) {\n'
         '        qDebug() << "[天气] 未配置天气接口，跳过刷新";\n'
         '        return;\n'
         '    }\n', ''),

    ("去掉 forecast 空判断",
     WS, '    if (forecast.isEmpty()) {\n'
         '        emit errorOccurred(QStringLiteral("天气数据缺少预报内容"));\n'
         '        return;\n'
         '    }\n', ''),

    ("去掉 doc.isObject 判断",
     WS, '    if (!doc.isObject()) {\n'
         '        emit errorOccurred(QStringLiteral("天气响应不是 JSON 对象"));\n'
         '        return;\n'
         '    }\n', ''),
]

CTRL = [
    ("加无关注释（文件末尾）", WS,
     '} // namespace accessterminal',
     '// 无关注释\n} // namespace accessterminal'),
    ("改 qDebug 文案", WS,
     'qDebug() << "[天气] 未配置天气接口，跳过刷新";',
     'qDebug() << "[weather] no url, skip";'),
]


def run_verify():
    return subprocess.run([PY, VERIFY, D, T], capture_output=True, cwd=D)


def main():
    problems = []
    try:
        r = run_verify()
        print('基线 rc = %d' % r.returncode)
        if r.returncode != 0:
            print('*** 基线就不过')
            print((r.stdout + r.stderr).decode('utf-8', 'replace')[-2500:])
            return 2
        print()

        for item in MUT:
            name, p, old, new = item[0], item[1], item[2], item[3]
            try:
                text = sub(p, old, new)
            except AssertionError as e:
                print('  [夹具错误] %-46s %s' % (name, e))
                problems.append(name)
                continue
            io.open(p, 'w', encoding='utf-8', newline='\n').write(text)
            if read(p) == _ORIG[p]:
                print('  [夹具错误] %-46s 文件未变' % name)
                problems.append(name)
                io.open(p, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG[p])
                continue

            r = run_verify()
            out = (r.stdout + r.stderr).decode('utf-8', 'replace')
            hits = re.findall(r'^\s*X (\[weather\][^\n]*)', out, re.M)
            if r.returncode != 0 and hits:
                print('  %-46s 被抓到 ✓ %s' % (name, hits[0][:56]))
            else:
                print('  %-46s *** 未被抓到（假绿）rc=%d'
                      % (name, r.returncode))
                problems.append(name)

            io.open(p, 'w', encoding='utf-8', newline='\n').write(_ORIG[p])

        print()
        for name, p, old, new in CTRL:
            try:
                text = sub(p, old, new)
            except AssertionError as e:
                print('  [夹具错误] %-46s %s' % (name, e))
                problems.append(name)
                continue
            io.open(p, 'w', encoding='utf-8', newline='\n').write(text)
            r = run_verify()
            out = (r.stdout + r.stderr).decode('utf-8', 'replace')
            if r.returncode == 0:
                print('  %-46s 通过 ✓（不误报）' % name)
            else:
                print('  %-46s *** 误报 rc=%d' % (name, r.returncode))
                print(out[-700:])
                problems.append(name)
            io.open(p, 'w', encoding='utf-8', newline='\n').write(_ORIG[p])
    finally:
        for p in (WS, WSH):
            io.open(p, 'w', encoding='utf-8', newline='\n').write(_ORIG[p])

    same = all(read(p) == _ORIG[p] for p in (WS, WSH))
    print()
    print('还原逐字节一致:', same)
    r = run_verify()
    for l in (r.stdout + r.stderr).decode('utf-8', 'replace').split('\n'):
        if '结论' in l:
            print('还原后:', l.strip())
    print()
    print('变异 %d 个，对照 %d 个，致命问题 %d 个'
          % (len(MUT), len(CTRL), len(problems)))
    if problems:
        print('问题清单:', problems)
    return 1 if (problems or not same) else 0


if __name__ == '__main__':
    sys.exit(main())
