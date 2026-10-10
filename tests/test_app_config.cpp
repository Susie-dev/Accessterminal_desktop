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
};

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
