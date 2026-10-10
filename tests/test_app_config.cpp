/**
 * @file test_app_config.cpp
 * @brief AppConfig 灯控指令解析的单元测试。
 *
 * 这是本工程**第一个**针对配置解析的可执行测试（此前只有协议契约测试）。
 *
 * 为什么需要它：`parseHexBytes()` 原来只检查"清洗后非空"与"长度为偶数"，
 * 然后直接交给 `QByteArray::fromHex()`。而 fromHex() 遇到非法字符时**不报错**，
 * 它会跳过非法字符并把剩余合法字符重新两两配对。于是在**偶数长度**输入下，
 * 解码总是"成功"，只是内容完全错位：
 *
 *   "FD0G4C12045DDF" -> 0f d0 4c 12 04 5d df   （应为 7 字节的真实指令）
 *
 * 这一段写错的灯控指令会被原样写进串口，灯只表现为"没反应"。
 * 下面用**真实 Qt** 跑出可判定的断言，把该行为钉死。
 */
#include <QtTest/QtTest>

#include <QByteArray>
#include <QDir>
#include <QFile>
#include <QTemporaryDir>

#include "config/app_config.h"

using accessterminal::AppConfig;

class TestAppConfig : public QObject
{
    Q_OBJECT

private slots:
    void defaultsMatchBaseline();
    void rejectsNonHexEvenLength();
    void rejectsOddLength();
    void rejectsEmptyAndGarbage();
    void acceptsValidForms();
    void badCommandKeepsDefaultInsteadOfCorrupting();

    // ---- 数值配置兜底（与门口机对称；第 8/9 轮的缺陷类别）----
    void clampHelpersBoundaries();
    void signalingPortNeverZeroOrOutOfRange();
    void ringtoneVolumeStaysInRange();
    void legalNumericValuesPassThroughUnchanged();
    void brokenJsonKeepsDefaults();
    void reloadResetsLoadedState();
};

/**
 * 数值兜底：本工程的 `signalingPort()` / `ringtoneVolume()` 与门口机的
 * `faceDetectInterval()` 属于同一类问题 —— 配置是不可信输入，越界值必须在
 * **取值出口**被夹住。门口机那边一个 0 值直接导致取模除零（SIGFPE 崩溃），
 * 这里侧重"端口 0 会让 QTcpServer 绑到随机临时端口，门口机永远连不上且
 * 日志看不出原因"。
 */
void TestAppConfig::clampHelpersBoundaries()
{
    using accessterminal::clampInt;

    QCOMPARE(clampInt(5, 1, 10), 5);
    QCOMPARE(clampInt(1, 1, 10), 1);    // 等于下界：不变
    QCOMPARE(clampInt(10, 1, 10), 10);  // 等于上界：不变
    QCOMPARE(clampInt(0, 1, 10), 1);
    QCOMPARE(clampInt(-999, 1, 10), 1);
    QCOMPARE(clampInt(11, 1, 10), 10);
    QCOMPARE(clampInt(INT_MIN, 1, 10), 1);
    QCOMPARE(clampInt(INT_MAX, 1, 10), 10);
}

/// 信令端口在**任何**输入下都不得为 0，也不得超出 quint16。
void TestAppConfig::signalingPortNeverZeroOrOutOfRange()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());

    // 期望值按 clampInt 语义（夹取），**不是** static_cast<quint16 的取模：
    // 修复前实测 65536 -> 0、999999 -> 16959、-1 -> 65535、-5 -> 65531，
    // 即"能成功监听的错误端口"，是本轮修掉的真实缺陷。
    const struct { const char* json; quint16 expect; } cases[] = {
        {"{\"network\":{\"signaling_port\":8887}}", 8887},
        {"{\"network\":{\"signaling_port\":0}}", 1},        // 0 -> 随机端口，必须夹到 1
        {"{\"network\":{\"signaling_port\":-1}}", 1},       // 不是 65535
        {"{\"network\":{\"signaling_port\":-5}}", 1},       // 不是 65531
        {"{\"network\":{\"signaling_port\":65535}}", 65535},
        {"{\"network\":{\"signaling_port\":65536}}", 65535}, // 不是 0
        {"{\"network\":{\"signaling_port\":999999}}", 65535},// 不是 16959
    };
    for (const auto& c : cases) {
        const QString path = dir.filePath(QStringLiteral("cfg.json"));
        QFile f(path);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write(c.json);
        f.close();

        AppConfig& cfg = AppConfig::instance();
        cfg.load(path);
        QCOMPARE(cfg.signalingPort(), c.expect);
        // 硬性不变量：端口永不为 0（否则 QTcpServer 绑到随机临时端口）
        QVERIFY2(cfg.signalingPort() != 0, "signalingPort()==0 会让监听端口随机");
    }
}

/// 铃声音量必须落在 QMediaPlayer::setVolume 的有效区间 [0,100]。
void TestAppConfig::ringtoneVolumeStaysInRange()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());

    const struct { const char* json; int expect; } cases[] = {
        {"{\"media\":{\"ringtone_volume\":0}}", 0},
        {"{\"media\":{\"ringtone_volume\":50}}", 50},
        {"{\"media\":{\"ringtone_volume\":100}}", 100},
        {"{\"media\":{\"ringtone_volume\":101}}", 100},
        {"{\"media\":{\"ringtone_volume\":-20}}", 0},
    };
    for (const auto& c : cases) {
        const QString path = dir.filePath(QStringLiteral("cfg.json"));
        QFile f(path);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write(c.json);
        f.close();

        AppConfig& cfg = AppConfig::instance();
        cfg.load(path);
        QCOMPARE(cfg.ringtoneVolume(), c.expect);
        QVERIFY(cfg.ringtoneVolume() >= 0 && cfg.ringtoneVolume() <= 100);
    }
}

/// 合法配置必须原样通过兜底（加了下限不能改变正常行为）。
void TestAppConfig::legalNumericValuesPassThroughUnchanged()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString path = dir.filePath(QStringLiteral("cfg.json"));
    QFile f(path);
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write("{\"network\":{\"signaling_port\":8887},"
            "\"media\":{\"ringtone_volume\":80}}");
    f.close();

    AppConfig& cfg = AppConfig::instance();
    QVERIFY(cfg.load(path));
    QCOMPARE(cfg.signalingPort(), static_cast<quint16>(8887));
    QCOMPARE(cfg.ringtoneVolume(), 80);
    // 默认端口必须仍是协议冻结值 8887
    cfg.load(QStringLiteral("/nonexistent/definitely-missing.json"));
    QCOMPARE(cfg.signalingPort(), static_cast<quint16>(8887));
}

/// JSON 损坏时必须整体回退默认值，不留"半套"配置。
void TestAppConfig::brokenJsonKeepsDefaults()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());

    const QByteArray broken[] = {"{ this is not json", "[1,2,3]", ""};
    for (const QByteArray& b : broken) {
        const QString path = dir.filePath(QStringLiteral("cfg.json"));
        QFile f(path);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write(b);
        f.close();

        AppConfig& cfg = AppConfig::instance();
        QVERIFY(!cfg.load(path));
        QCOMPARE(cfg.signalingPort(), static_cast<quint16>(8887));
        QCOMPARE(cfg.ringtoneVolume(), 100);
        // 灯控默认值必须完好
        QCOMPARE(cfg.lightCommand(QStringLiteral("desk")).toHex(),
                 QByteArray("fd034c12045ddf"));
    }
}

/**
 * 回归（本轮修复）：单例的 load() 必须**每次**复位"已载入"状态。
 *
 * 修复前：先 load(好文件) 成功会把 m_loadedFromFile 置 true，之后再
 * load(坏文件) 时没有任何分支复位它，函数末尾 `return m_loadedFromFile;`
 * 于是返回 **true**，而 configPath() 仍指向早已不生效的旧路径。调用方会
 * 以为"配置已按文件生效"，实际用的是内置默认值。
 */
void TestAppConfig::reloadResetsLoadedState()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());

    const QString good = dir.filePath(QStringLiteral("good.json"));
    QFile gf(good);
    QVERIFY(gf.open(QIODevice::WriteOnly));
    gf.write("{\"network\":{\"self_ip\":\"1.2.3.4\"}}");
    gf.close();

    const QString bad = dir.filePath(QStringLiteral("bad.json"));
    QFile bf(bad);
    QVERIFY(bf.open(QIODevice::WriteOnly));
    bf.write("{ broken");
    bf.close();

    AppConfig& cfg = AppConfig::instance();

    // 1) 好文件：成功，且路径更新
    QVERIFY(cfg.load(good));
    QCOMPARE(cfg.selfIp(), QStringLiteral("1.2.3.4"));
    QCOMPARE(cfg.configPath(), good);

    // 2) 坏文件：必须返回 false，且不残留上一个路径
    QVERIFY2(!cfg.load(bad), "坏文件之后 load() 仍返回 true（状态未复位）");
    QCOMPARE(cfg.selfIp(), QStringLiteral("192.168.1.4"));   // 回落默认
    QVERIFY2(cfg.configPath().isEmpty(),
             "load() 失败后 configPath() 仍指向旧文件，会误导现场排查");

    // 3) 不存在的文件：同样 false
    QVERIFY(!cfg.load(QStringLiteral("/nonexistent/definitely-missing.json")));
    QVERIFY(cfg.configPath().isEmpty());

    // 4) 再次载入好文件必须恢复正常
    QVERIFY(cfg.load(good));
    QCOMPARE(cfg.configPath(), good);
    QCOMPARE(cfg.selfIp(), QStringLiteral("1.2.3.4"));
}

/// 内置默认灯控指令必须与重构前的 hexArray* 逐字节一致。
void TestAppConfig::defaultsMatchBaseline()
{
    AppConfig& cfg = AppConfig::instance();
    cfg.load(QStringLiteral("/nonexistent/definitely-missing.json"));

    QCOMPARE(cfg.lightCommand(QStringLiteral("desk")).toHex(),
             QByteArray("fd034c12045ddf"));
    QCOMPARE(cfg.lightCommand(QStringLiteral("work")).toHex(),
             QByteArray("fd034c12025ddf"));
    QCOMPARE(cfg.lightCommand(QStringLiteral("work_round")).toHex(),
             QByteArray("fd039736f44fdf"));
    QCOMPARE(cfg.lightCommand(QStringLiteral("desk_round")).toHex(),
             QByteArray("fd039736f250df"));
    QCOMPARE(cfg.lightCommand(QStringLiteral("wall")).toHex(),
             QByteArray("fd039736f150df"));
    QVERIFY(!cfg.loadedFromFile());
}

/**
 * 核心回归：非法字符必须被拒绝，而不是被"跳过并重新配对"。
 *
 * 每个用例的字符数都是**偶数**，正是 fromHex 会静默产出错误结果的那一类。
 */
void TestAppConfig::rejectsNonHexEvenLength()
{
    // 通过配置文件走完整路径，断言"非法即保留默认值"。
    QTemporaryDir dir;
    QVERIFY(dir.isValid());

    struct Case {
        const char* name;
        const char* text;
        const char* expectDefault;  // 该键的默认值
    };
    const Case cases[] = {
        // 把某一位敲成字母 G —— 最容易犯的错
        {"desk", "FD0G4C12045DDF", "fd034c12045ddf"},
        // 非法字符出现在中间
        {"work", "FD03Z412025DDF", "fd034c12025ddf"},
        // 前面两个字符非法，导致整体错位
        {"wall", "XX039736F150DF", "fd039736f150df"},
        // 最后一位非法
        {"desk_round", "FD039736F250DZ", "fd039736f250df"},
        // 空白字符不属于被清洗的那几种（制表符）
        {"work_round", "FD039736\t44FDF", "fd039736f44fdf"},
    };

    for (const Case& c : cases) {
        const QString path = dir.filePath(QStringLiteral("cfg.json"));
        QFile f(path);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write(QStringLiteral("{\"lights\":{\"%1\":\"%2\"}}")
                    .arg(QString::fromLatin1(c.name),
                         QString::fromLatin1(c.text))
                    .toUtf8());
        f.close();

        AppConfig& cfg = AppConfig::instance();
        cfg.load(path);
        QVERIFY2(cfg.loadedFromFile(), "配置应成功载入");

        // 非法指令必须被丢弃 -> 回落到内置默认值
        QCOMPARE(cfg.lightCommand(QString::fromLatin1(c.name)).toHex(),
                 QByteArray(c.expectDefault));
    }
}

void TestAppConfig::rejectsOddLength()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString path = dir.filePath(QStringLiteral("cfg.json"));
    QFile f(path);
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write("{\"lights\":{\"desk\":\"FD034C12045DD\"}}");
    f.close();

    AppConfig& cfg = AppConfig::instance();
    cfg.load(path);
    QCOMPARE(cfg.lightCommand(QStringLiteral("desk")).toHex(),
             QByteArray("fd034c12045ddf"));  // 默认值
}

void TestAppConfig::rejectsEmptyAndGarbage()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString path = dir.filePath(QStringLiteral("cfg.json"));
    QFile f(path);
    QVERIFY(f.open(QIODevice::WriteOnly));
    // 空串、纯非法、非字符串类型
    f.write("{\"lights\":{\"desk\":\"\",\"work\":\"ZZZZ\",\"wall\":123}}");
    f.close();

    AppConfig& cfg = AppConfig::instance();
    cfg.load(path);
    QCOMPARE(cfg.lightCommand(QStringLiteral("desk")).toHex(),
             QByteArray("fd034c12045ddf"));
    QCOMPARE(cfg.lightCommand(QStringLiteral("work")).toHex(),
             QByteArray("fd034c12025ddf"));
    QCOMPARE(cfg.lightCommand(QStringLiteral("wall")).toHex(),
             QByteArray("fd039736f150df"));
}

/// 合法写法必须都被接受，且解析结果逐字节正确（不能因加固而误杀）。
void TestAppConfig::acceptsValidForms()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString path = dir.filePath(QStringLiteral("cfg.json"));
    QFile f(path);
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write("{\"lights\":{"
            "\"desk\":\"FD034C12045DDF\","          // 紧凑大写
            "\"work\":\"FD 03 4C 12 02 5D DF\","    // 带空格
            "\"wall\":\"fd039736f150df\","          // 小写
            "\"desk_round\":\"0xFD039736F250DF\","  // 带 0x 前缀
            "\"work_round\":\"FD:03:97:36:F4:4F:DF\"" // 带冒号
            "}}");
    f.close();

    AppConfig& cfg = AppConfig::instance();
    cfg.load(path);
    QVERIFY(cfg.loadedFromFile());

    QCOMPARE(cfg.lightCommand(QStringLiteral("desk")).toHex(),
             QByteArray("fd034c12045ddf"));
    QCOMPARE(cfg.lightCommand(QStringLiteral("work")).toHex(),
             QByteArray("fd034c12025ddf"));
    QCOMPARE(cfg.lightCommand(QStringLiteral("wall")).toHex(),
             QByteArray("fd039736f150df"));
    QCOMPARE(cfg.lightCommand(QStringLiteral("desk_round")).toHex(),
             QByteArray("fd039736f250df"));
    QCOMPARE(cfg.lightCommand(QStringLiteral("work_round")).toHex(),
             QByteArray("fd039736f44fdf"));
}

/**
 * 直接展示缺陷本身：证明 fromHex 在偶数长度非法输入下**不会**返回空。
 *
 * 这条断言不依赖 AppConfig，是对 Qt 行为的"记录"，说明上面的加固为什么必要。
 * 若将来 Qt 改变了该行为，这条会失败，提醒我们重新评估守卫是否还需要。
 */
void TestAppConfig::badCommandKeepsDefaultInsteadOfCorrupting()
{
    const QByteArray corrupted = QByteArray::fromHex("FD0G4C12045DDF");
    // 关键：非空！所以 `!bytes.isEmpty()` 拦不住它。
    QVERIFY2(!corrupted.isEmpty(),
             "fromHex 对偶数长度非法输入返回了空 —— Qt 行为可能已变，"
             "请重新评估 parseHexBytes 的显式校验是否仍必要");
    // 关键：内容与真实指令完全不同（错位重排）。
    QVERIFY(corrupted != QByteArray::fromHex("FD034C12045DDF"));
    QCOMPARE(corrupted.toHex(), QByteArray("0fd04c12045ddf"));
}

QTEST_MAIN(TestAppConfig)
#include "test_app_config.moc"
