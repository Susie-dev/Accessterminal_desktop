# -*- coding: utf-8 -*-
"""t113/desktop_test_weather_service 故障注入自检（纯 Python 驱动）。

每个变异都朝**真实的危险退化**去改 weather_service.cpp，并要求对应用例必须
失败。两个对照必须仍然通过（不误报）。

判定方式（第 30 轮实测）：
    QtTest 的退出码 == FAIL 行数（不是崩溃信号）。
    真正的崩溃 = 非零退出码但**一条 FAIL 行都没有**。
    所以用 `crashed = returncode != 0 and not failed`。
"""
import io
import os
import re
import shutil
import subprocess
# 注意：判定 FAIL 行只看行首 ``FAIL!``，**不要**去匹配用例名的形状。
# 数据驱动用例输出的是 ``Class::case(desk)`` 而不是 ``Class::case()``，
# 用 ``\w+::(\w+)\(\)`` 会漏掉它们，把正常的断言失败误判成崩溃。
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

D = r'C:\Users\user\Desktop\linux_ai\Accessterminal_desktop'
MSYS = r'C:\Users\user\.dsh\toolchains\msys64'
CMAKE = os.path.join(MSYS, 'mingw64', 'bin', 'cmake.exe')
BUILD = os.path.join(os.environ['TEMP'], 'fi32win')
EXE = os.path.join(BUILD, 'desktop_test_weather_service.exe')
OBJ = os.path.join(
    BUILD, 'CMakeFiles', 'desktop_test_weather_service.dir',
    'C_', 'Users', 'user', 'Desktop', 'linux_ai', 'Accessterminal_desktop',
    'src', 'core', 'weather', 'weather_service.cpp.obj')
SRC = os.path.join(D, 'src', 'core', 'weather', 'weather_service.cpp')

ENV = dict(os.environ)
ENV['PATH'] = (os.path.join(MSYS, 'mingw64', 'bin') + os.pathsep
               + os.path.join(MSYS, 'usr', 'bin') + os.pathsep + ENV['PATH'])


def read_src():
    return io.open(SRC, encoding='utf-8').read()


_ORIG = read_src()


def anchor(marker, end='}'):
    """从真实文件里按大括号配对取出 `marker` 开头的那段。

    锚点必须从**真实字节**构造，不要手抄 —— 手抄会漏掉空行与缩进差异，
    造出一个永远匹配不到（或匹配到错误位置）的变异。
    """
    i = _ORIG.find(marker)
    if i < 0:
        raise AssertionError('找不到 marker: %r' % marker)
    j = _ORIG.find('{', i)
    if j < 0:
        raise AssertionError('marker 后没有 { : %r' % marker)
    depth = 0
    for k in range(j, len(_ORIG)):
        c = _ORIG[k]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return _ORIG[i:k + 1]
    raise AssertionError('大括号不配对: %r' % marker)


# 各锚点（从真实文件取出）
ABANDON = anchor('void WeatherService::abandonReply()')
REFRESH = anchor('void WeatherService::refresh()')
REFRESH_BODY = REFRESH[REFRESH.find('{'):]
ONFINISH = anchor('void WeatherService::onFinished()')
DTOR = anchor('WeatherService::~WeatherService()')

# onFinished 里若干具体片段（从真实文件里按行定位）
_ol = _ORIG.split('\n')


def line_of(sub, nth=1):
    """返回包含 sub 的整行（第 nth 次出现），含行尾换行。"""
    seen = 0
    for l in _ol:
        if sub in l:
            seen += 1
            if seen == nth:
                return l + '\n'
    raise AssertionError('找不到行: %r' % sub)


STATUS_IF = (
    '    const int statusCode =\n'
    '        reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();\n'
    '    if (reply->error() != QNetworkReply::NoError || statusCode != 200) {\n'
    '        const QString msg = QStringLiteral("天气请求失败: %1 (HTTP %2)")\n'
    '                                .arg(reply->errorString())\n'
    '                                .arg(statusCode);\n'
    '        qWarning() << "[天气]" << msg;\n'
    '        emit errorOccurred(msg);\n'
    '        return;\n'
    '    }\n')
assert _ORIG.count(STATUS_IF) == 1, 'STATUS_IF 锚点不唯一: %d' % _ORIG.count(STATUS_IF)

DOC_ISOBJECT = (
    '    const QJsonDocument doc = QJsonDocument::fromJson(reply->readAll());\n'
    '    if (!doc.isObject()) {\n'
    '        emit errorOccurred(QStringLiteral("天气响应不是 JSON 对象"));\n'
    '        return;\n'
    '    }\n')
assert _ORIG.count(DOC_ISOBJECT) == 1, 'DOC_ISOBJECT 锚点不唯一'

FORECAST_EMPTY = (
    '    if (forecast.isEmpty()) {\n'
    '        emit errorOccurred(QStringLiteral("天气数据缺少预报内容"));\n'
    '        return;\n'
    '    }\n')
assert _ORIG.count(FORECAST_EMPTY) == 1, 'FORECAST_EMPTY 锚点不唯一'

TEXT_FMT = (
    '    const QString text =\n'
    '        QStringLiteral("%1，今日天气%2，\\n高温%3，低温%4，\\n%5\\n每日提醒：%6")\n'
    '            .arg(city, type, high, low, wind, notice);\n')
assert _ORIG.count(TEXT_FMT) == 1, 'TEXT_FMT 锚点不唯一'

HIGH_REMOVE = (
    '    const QString high = today.value(QStringLiteral("high")).toString()\n'
    '                             .remove(QStringLiteral("高温 "));\n')
assert _ORIG.count(HIGH_REMOVE) == 1, 'HIGH_REMOVE 锚点不唯一'
LOW_REMOVE = (
    '    const QString low = today.value(QStringLiteral("low")).toString()\n'
    '                            .remove(QStringLiteral("低温 "));\n')
assert _ORIG.count(LOW_REMOVE) == 1, 'LOW_REMOVE 锚点不唯一'

# 注意：**不能**只删 `.remove(...)` 那一行 —— 上一条语句以 `.toString()`
# 结尾、没有分号，删掉续行后会变成 "const QString high = ...toString()"
# 紧跟下一行声明，是**编译错误**（实测报 'low' was not declared in this scope）。
# 必须整两句一起换成带分号的单行版本，变异才是合法的。
HIGH_REMOVE_NEW = '    const QString high = today.value(QStringLiteral("high")).toString();\n'
LOW_REMOVE_NEW = '    const QString low = today.value(QStringLiteral("low")).toString();\n'
FORECAST_AT = line_of('const QJsonObject today = forecast.at(')
WEATHER_UPDATED = line_of('emit weatherUpdated(text);')
CITY_EXPR = (
    '    const QString city = root.value(QStringLiteral("cityInfo")).toObject()\n'
    '                             .value(QStringLiteral("city")).toString();\n')
assert _ORIG.count(CITY_EXPR) == 1, 'CITY_EXPR 锚点不唯一'

URL_EMPTY = (
    '    const QString url = AppConfig::instance().weatherUrl();\n'
    '    if (url.isEmpty()) {\n'
    '        qDebug() << "[天气] 未配置天气接口，跳过刷新";\n'
    '        return;\n'
    '    }\n')
assert _ORIG.count(URL_EMPTY) == 1, 'URL_EMPTY 锚点不唯一'

NEW_REPLY = line_of('m_reply = m_manager->get(')


MUT = [
    # ---- 取消逻辑（本测试的核心）----
    # abandonReply() 变成空实现 -> 旧请求不被取消，新旧并存。
    ("abandonReply 什么都不做（不取消在途请求）",
     ABANDON,
     'void WeatherService::abandonReply()\n{\n}'),

    # 只 abort 不先断连接、不先摘成员 —— 就是原注释警告的那个错误顺序。
    # 预期抓到的用例：refreshCancelsInFlightWithoutFalseError
    # （abort 同步触发 onFinished，看到 OperationCanceledError -> 假错误）。
    ("abandonReply 直接 abort（不断连接、不摘成员）",
     ABANDON,
     'void WeatherService::abandonReply()\n'
     '{\n'
     '    if (!m_reply) {\n'
     '        return;\n'
     '    }\n'
     '    m_reply->abort();\n'
     '    m_reply->deleteLater();\n'
     '}'),

    # "不摘除成员 m_reply" 这个退化实测抓不到，已移到 UNDETECTABLE 并说明原因。

    ("refresh 不取消前一个在途请求（不调 abandonReply）",
     '    // 避免请求堆积：新请求前取消在途请求。\n    abandonReply();\n',
     ''),

    # ---- 成功路径：文案 ----
    ("文案格式改了（多一个空格）",
     TEXT_FMT,
     '    const QString text =\n'
     '        QStringLiteral("%1，今日天气 %2，\\n高温%3，低温%4，\\n%5\\n每日提醒：%6")\n'
     '            .arg(city, type, high, low, wind, notice);\n'),

    ("文案少了『每日提醒』前缀",
     TEXT_FMT,
     '    const QString text =\n'
     '        QStringLiteral("%1，今日天气%2，\\n高温%3，低温%4，\\n%5\\n%6")\n'
     '            .arg(city, type, high, low, wind, notice);\n'),

    ("不剥离 high 的『高温 』前缀",
     HIGH_REMOVE, HIGH_REMOVE_NEW),

    ("不剥离 low 的『低温 』前缀",
     LOW_REMOVE, LOW_REMOVE_NEW),

    ("取 forecast 的第 1 项而不是第 0 项",
     FORECAST_AT,
     '    const QJsonObject today = forecast.at(1).toObject();\n'),

    ("city 取错字段",
     CITY_EXPR,
     '    const QString city = root.value(QStringLiteral("cityInfo")).toObject()\n'
     '                             .value(QStringLiteral("cityName")).toString();\n'),

    ("成功路径不发 weatherUpdated",
     WEATHER_UPDATED, ''),

    ("成功路径额外也发一次 errorOccurred",
     WEATHER_UPDATED,
     '    emit errorOccurred(QStringLiteral("假错误"));\n'
     '    emit weatherUpdated(text);\n'),

    # ---- 失败路径 ----
    ("HTTP 非 200 也当成成功",
     STATUS_IF,
     '    const int statusCode =\n'
     '        reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();\n'
     '    if (false) {\n'
     '        const QString msg = QStringLiteral("天气请求失败: %1 (HTTP %2)")\n'
     '                                .arg(reply->errorString())\n'
     '                                .arg(statusCode);\n'
     '        qWarning() << "[天气]" << msg;\n'
     '        emit errorOccurred(msg);\n'
     '        return;\n'
     '    }\n'),

    ("错误文案不带 HTTP 状态码",
     STATUS_IF,
     '    const int statusCode =\n'
     '        reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();\n'
     '    if (reply->error() != QNetworkReply::NoError || statusCode != 200) {\n'
     '        const QString msg = QStringLiteral("天气请求失败");\n'
     '        qWarning() << "[天气]" << msg;\n'
     '        emit errorOccurred(msg);\n'
     '        return;\n'
     '    }\n'),

    ("网络错误不 emit errorOccurred",
     '        emit errorOccurred(msg);\n        return;\n    }\n\n    const QJsonDocument',
     '        return;\n    }\n\n    const QJsonDocument'),

    ("非 JSON 对象也继续解析（不报错）",
     DOC_ISOBJECT,
     '    const QJsonDocument doc = QJsonDocument::fromJson(reply->readAll());\n'),

    ("forecast 为空也继续（越界风险）",
     FORECAST_EMPTY, ''),

    # ---- 生命周期 ----
    ("构造时就立刻发一次请求",
     'WeatherService::WeatherService(QObject* parent)\n'
     '    : QObject(parent)\n'
     '{\n'
     '    m_manager = new QNetworkAccessManager(this);\n'
     '}',
     'WeatherService::WeatherService(QObject* parent)\n'
     '    : QObject(parent)\n'
     '{\n'
     '    m_manager = new QNetworkAccessManager(this);\n'
     '    refresh();\n'
     '}'),

    # ---- 对照（必须不误报）----
    #
    # 对照的位置很讲究。第一版把注释放到 `void WeatherService::refresh()`
    # 之后，结果注释放进了**函数体内第一行** —— 那个位置会把函数体的行号
    # 整体下移，而且 `networkErrorEmitsErrorOccurred` 恰好在这个时间窗口内
    # 偶发失败时，看起来就像"无关改动导致误报"，其实那次失败是夹具自己的
    # 悬空键缺陷（已修）。对照必须选**语义与计时都绝不受影响**的位置：
    # 放在文件末尾的 namespace 收尾注释之前，只增加一行注释。
    ("对照：加无关注释",
     '} // namespace accessterminal',
     '// 无关注释（对照：不应影响任何行为）\n} // namespace accessterminal', False),

    ("对照：改 qDebug 文案",
     'qDebug() << "[天气] 未配置天气接口，跳过刷新";',
     'qDebug() << "[weather] no url configured, skip refresh";', False),
]


# ---------------------------------------------------------------------------
# 经实测判定为**本测试不可观测**的退化（如实记录，不假装覆盖）。
#
# 与第 31 轮 MonitorClient 同一套做法：不把它们塞进 MUT 换取一条假的"已覆盖"，
# 而是让夹具**实测证明**确实抓不到；将来某次改动若让它变得可观测，
# 夹具会报错并提示提升为真变异。
# ---------------------------------------------------------------------------
UNDETECTABLE = [
    # abandonReply() 里 `m_reply = nullptr;` 被删掉，但 disconnect 仍在。
    #
    # 为什么抓不到：abandonReply() 已经**先**把 finished 信号断开了，所以
    # abort() 那个同步 finished() 到不了 onFinished()，没有任何代码会再读
    # m_reply。而唯一"读 m_reply"的地方（refresh / 析构）都会立刻写它或
    # 走到对象销毁 —— 悬挂窗口里没有可观测行为。
    # 注意这与"不断开连接"是**两件事**：后者会走同步重入，是被抓到的。
    ("abandonReply 不摘除成员 m_reply（disconnect 仍在）",
     '    QNetworkReply* reply = m_reply;\n'
     '    m_reply = nullptr; // 先摘除成员，后续重入也看不到它\n'
     '    disconnect(reply, nullptr, this, nullptr);\n',
     '    QNetworkReply* reply = m_reply;\n'
     '    disconnect(reply, nullptr, this, nullptr);\n'),

    # 析构不调用 abandonReply()。
    #
    # 为什么抓不到：`QNetworkAccessManager` 是 WeatherService 的**子对象**
    # （new ... (this)），而 QNetworkAccessManager::get() 返回的 reply 又是
    # manager 的子对象。于是 ~QObject 会连带销毁 manager 和那个在途 reply，
    # 端口/句柄一样被释放。这与第 31 轮 MonitorClient "析构不调用 stop()'
    # 是同一类：**QObject 父子所有权让这条路径不可观测**。
    # （第 31 轮那条最后是靠 activeChanged 信号才变得可观测的；
    #   这里 abandonReply() 不发任何信号，因此没有任何可观测痕迹。）
    ("析构不丢弃在途请求",
     'WeatherService::~WeatherService()\n{\n    abandonReply();\n}',
     'WeatherService::~WeatherService()\n{\n}'),
]


def configure():
    return subprocess.run(
        [CMAKE, '-S', os.path.join(D, 'tests'), '-B', BUILD, '-G', 'Ninja'],
        capture_output=True, env=ENV, cwd=D)


def build(target='desktop_test_weather_service'):
    return subprocess.run([CMAKE, '--build', BUILD, '--target', target],
                          capture_output=True, env=ENV, cwd=D)


def run_exe():
    return subprocess.run([EXE], capture_output=True, env=ENV, cwd=D)


def main():
    # ---- 锚点唯一性自证 ----
    for item in MUT + UNDETECTABLE:
        name, old = item[0], item[1]
        n = _ORIG.count(old)
        if n != 1:
            print('[夹具错误] %s 锚点出现 %d 次（必须恰好 1 次）' % (name, n))
            return 2

    shutil.rmtree(BUILD, ignore_errors=True)
    r = configure()
    print('configure rc=%d' % r.returncode)
    if r.returncode != 0:
        print(r.stderr.decode('utf-8', 'replace')[-2000:])
        return 2
    rb = build()
    if rb.returncode != 0:
        print('基线构建失败:')
        print((rb.stdout + rb.stderr).decode('utf-8', 'replace')[-2000:])
        return 2
    rr = run_exe()
    out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
    base_fail = len(re.findall(r'^FAIL!\s*:', out, re.M))
    tot = re.search(r'Totals:\s*(\d+) passed,\s*(\d+) failed', out)
    print('基线: %s' % (tot.group(0) if tot else '(无 Totals)'))
    if base_fail != 0:
        print('*** 基线就有 %d 条 FAIL，无法继续' % base_fail)
        print(out[-3000:])
        return 2
    print()

    problems = []
    try:
        for item in MUT:
            name, old, new = item[0], item[1], item[2]
            expect_fail = item[3] if len(item) > 3 else True

            text = _ORIG.replace(old, new, 1)
            io.open(SRC, 'w', encoding='utf-8', newline='\n').write(text)
            if read_src() == _ORIG:
                print('  [夹具错误] %-46s 文件未变' % name)
                problems.append(name)
                io.open(SRC, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG)
                continue

            t0 = os.path.getmtime(OBJ) if os.path.exists(OBJ) else 0
            rb = build()
            if rb.returncode != 0:
                print('  [构建失败] %-46s %s' % (
                    name, (rb.stdout + rb.stderr).decode(
                        'utf-8', 'replace')[-220:]))
                problems.append(name)
                io.open(SRC, 'w', encoding='utf-8',
                        newline='\n').write(_ORIG)
                continue
            t1 = os.path.getmtime(OBJ) if os.path.exists(OBJ) else 0

            rr = run_exe()
            out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
            failed = re.findall(r'^FAIL!\s*:', out, re.M)
            crashed = rr.returncode != 0 and not failed
            totals = re.search(r'Totals:\s*(\d+) passed,\s*(\d+) failed', out)
            consistent = (totals is not None
                          and rr.returncode == int(totals.group(2)))

            if t1 <= t0:
                print('  [夹具错误] %-46s .obj 未重编' % name)
                problems.append(name)
            elif expect_fail:
                if failed or crashed:
                    if crashed:
                        tag = '崩溃(rc=%d, 0 条 FAIL 行)' % rr.returncode
                    elif consistent:
                        tag = '%d 条 FAIL 行(rc=%d)' % (len(failed), rr.returncode)
                    else:
                        tag = '%d 条 FAIL 行(rc=%d 与 failed 计数不符)' % (
                            len(failed), rr.returncode)
                    print('  %-46s 被抓到 ✓ %s' % (name, tag))
                else:
                    print('  %-46s *** 未被抓到（假绿）rc=%d' % (name, rr.returncode))
                    problems.append(name)
            else:
                if not failed and not crashed:
                    print('  %-46s 通过 ✓（不误报）' % name)
                else:
                    print('  %-46s *** 误报：%s' % (name, failed[:3]))
                    problems.append(name)

            io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)
    finally:
        io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)

    same = read_src() == _ORIG
    print()
    print('还原逐字节一致:', same)

    # -----------------------------------------------------------------
    # 实测"判定为不可观测"的那几个退化：必须真的抓不到。
    # 逻辑与 MUT 相反；一旦能抓到，就说明它已可观测，应提升为真变异。
    # -----------------------------------------------------------------
    print()
    print('--- 已判定不可观测的退化（必须抓不到；一旦能抓到就该提升为真变异）---')
    for item in UNDETECTABLE:
        name, old, new = item[0], item[1], item[2]
        io.open(SRC, 'w', encoding='utf-8',
                newline='\n').write(_ORIG.replace(old, new, 1))
        if read_src() == _ORIG:
            print('  [夹具错误] %-46s 文件未变' % name)
            problems.append(name)
            io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)
            continue
        rb = build()
        if rb.returncode != 0:
            print('  *** %-46s 构建失败（不可再自称不可观测）' % name)
            problems.append(name)
            io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)
            continue
        rr = run_exe()
        out = (rr.stdout + rr.stderr).decode('utf-8', 'replace')
        failed = re.findall(r'^FAIL!\s*:', out, re.M)
        crashed = rr.returncode != 0 and not failed
        if failed or crashed:
            print('  *** %-46s 竟然被抓到了（%d 条 FAIL, rc=%d）'
                  % (name, len(failed), rr.returncode))
            print('      => 它已可观测，应提升为真变异，而不是继续免责')
            problems.append(name)
        else:
            print('  %-46s 确认抓不到 ✓' % name)
        io.open(SRC, 'w', encoding='utf-8', newline='\n').write(_ORIG)

    same = same and (read_src() == _ORIG)

    build()
    rr = run_exe()
    for l in (rr.stdout + rr.stderr).decode('utf-8', 'replace').split('\n'):
        if 'Totals' in l:
            print('还原后全量:', l.strip())
    print()
    print('变异 %d 个（另有无判别力退化 %d 个已实测确认），致命问题 %d 个'
          % (len(MUT), len(UNDETECTABLE), len(problems)))
    if problems:
        print('问题清单:', problems)
    return 1 if (problems or not same) else 0


if __name__ == '__main__':
    sys.exit(main())
