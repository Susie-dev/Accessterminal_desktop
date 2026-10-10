/**
 * @file test_serial_light.cpp
 * @brief SerialLight（室内机串口灯控）单元测试。
 *
 * 背景
 * ----
 * `src/hal/serial_light.cpp` 此前**从未被任何测试目标链接**。它虽然只有 89 行，
 * 却是"把灯控指令写到硬件"的唯一出口，而且有两条**只靠日志区分**的失败分支
 * （指令名未知 / 串口未打开）——现场排障完全依赖这两条日志分得清楚。
 *
 * 怎么测（影子头文件）
 * --------------------
 * `SerialLight` 把 `QSerialPort` 当**具体类型**用（`new QSerialPort(this)`、
 * `m_port->write(...)`），既非虚函数也不可注入；本机又没有真实串口。
 * 因此本目录下的 `fake_serial_port/QSerialPort` 用
 * `target_include_directories(BEFORE ...)` 顶掉真正的 Qt 头
 * （探针十六实测确认该技巧生效）。
 *
 * 于是这里测的是**真实的 serial_light.cpp**，同一条代码路径，只把最底层的
 * 系统调用换成可记录的替身；"打开失败要发信号"、"写入不完整要发信号"、
 * "未打开不许写"这些分支都能真的被执行到，而不是靠读代码推断。
 *
 * 断言层次（按"能否观测到输出"排）
 * --------------------------------
 *   1. 串口的实际动作：setPortName/setBaudRate/8N1/无流控 的取值与调用次数、
 *      open() 的打开模式、write() 收到的**确切字节**、flush() 次数、
 *      在已打开时再次 open() 是否**先关再开**；
 *   2. 返回值与 errorOccurred 信号（含文案要点）；
 *   3. **日志分支**：两条失败路径只靠日志区分，故用消息处理器捕获后断言，
 *      并配一个正对照证明捕获管道本身是通的。
 */
#include <QByteArray>
#include <QDebug>
#include <QIODevice>
#include <QObject>
#include <QSignalSpy>
#include <QString>
#include <QStringList>
#include <QtTest>

#include "config/app_config.h"
#include "fake_serial_port.h"
#include "hal/serial_light.h"

using accessterminal::AppConfig;
using accessterminal::SerialLight;

namespace {

QStringList g_log;

void captureHandler(QtMsgType type, const QMessageLogContext& ctx,
                    const QString& msg)
{
    Q_UNUSED(type);
    Q_UNUSED(ctx);
    g_log.append(msg);
}

/// 安装日志捕获；RAII 保证异常/提前 return 时也会摘掉。
class LogCapture
{
public:
    LogCapture()
    {
        g_log.clear();
        m_prev = qInstallMessageHandler(captureHandler);
    }
    ~LogCapture() { qInstallMessageHandler(m_prev); }

    bool contains(const QString& needle) const
    {
        for (const QString& s : g_log) {
            if (s.contains(needle)) {
                return true;
            }
        }
        return false;
    }
    QString joined() const { return g_log.join(QStringLiteral(" | ")); }

private:
    QtMessageHandler m_prev = nullptr;
};

const char* const kPortName = "/dev/ttyUSB0";

} // namespace

class TestSerialLight : public QObject
{
    Q_OBJECT

private slots:
    void init();

    // ---- 构造 / 析构 ----
    void constructionDoesNotOpenAnything();
    void destructorClosesAnOpenPort();
    void destructorWithoutOpenIsSafe();

    // ---- open() 的参数与返回 ----
    void openConfiguresEightNOneWithoutFlowControl();
    void openUsesTheRequestedBaudRate();
    void defaultBaudRateIs9600();
    void openWhenAlreadyOpenClosesFirst();
    void openFailureReturnsFalseAndEmitsError();
    void openFailureMessageContainsPortNameAndReason();
    void failedOpenLeavesPortClosed();
    void successfulOpenEmitsNoError();

    // ---- isOpen() / close() ----
    void isOpenIsFalseBeforeOpen();
    void isOpenTracksOpenAndClose();
    void closeWithoutOpenIsSafe();
    void closeIsIdempotent();

    // ---- sendCommand() ----
    void sendCommandWritesTheConfiguredBytes();
    void sendCommandFlushesOnce();
    void sendCommandReturnsFalseForUnknownName();
    void unknownNameLogsOnlyTheUnknownBranch();
    void sendCommandOnClosedPortReturnsFalse();
    void closedPortLogsOnlyTheNotOpenBranch();
    void sendCommandDoesNotWriteWhenClosed();
    void unknownNameIsCheckedBeforePortState();
    void partialWriteReturnsFalseAndEmitsError();
    void partialWriteStillFlushes();
    void sendCommandCanBeRepeated();

    // ---- 灯控指令契约（配置默认值，逐字节）----
    void defaultCommandsMatchTheFrozenBytes_data();
    void defaultCommandsMatchTheFrozenBytes();

    // ---- 正对照：日志捕获管道本身是通的 ----
    void logCapturePipelineWorks();
};

void TestSerialLight::init()
{
    resetFakeSerialPort();
    g_log.clear();
}

// ---------------------------------------------------------------------------
// 构造 / 析构
// ---------------------------------------------------------------------------

void TestSerialLight::constructionDoesNotOpenAnything()
{
    SerialLight light;
    // 构造不得碰硬件：未打开就只能是"未打开"。
    QCOMPARE(fakeSerialPort().openCalls, 0);
    QCOMPARE(light.isOpen(), false);
}

void TestSerialLight::destructorClosesAnOpenPort()
{
    int baselineCloses = 0;
    {
        SerialLight light;
        QVERIFY(light.open(QString::fromLatin1(kPortName), 9600));
        baselineCloses = fakeSerialPort().closeCalls; // open 时的"先关"为 0
        QCOMPARE(light.isOpen(), true);
    }
    // 析构必须把串口关掉，否则设备句柄会留在进程里。
    QCOMPARE(fakeSerialPort().closeCalls, baselineCloses + 1);
}

void TestSerialLight::destructorWithoutOpenIsSafe()
{
    {
        SerialLight light;
        Q_UNUSED(light);
    }
    // 从未 open 过：m_port 仍是 nullptr，析构不得崩、也不该报错。
    QCOMPARE(fakeSerialPort().openCalls, 0);
    QCOMPARE(fakeSerialPort().closeCalls, 0);
}

// ---------------------------------------------------------------------------
// open()
// ---------------------------------------------------------------------------

void TestSerialLight::openConfiguresEightNOneWithoutFlowControl()
{
    SerialLight light;
    QVERIFY(light.open(QString::fromLatin1(kPortName), 9600));

    const FakeSerialPortRecord& r = fakeSerialPort();
    // 8 数据位、无校验、1 停止位、无流控 —— 与重构前完全一致。
    //
    // 这里断言**裸数值**而不是 QSerialPort::Data8 之类的枚举：
    // 在本目标里 QSerialPort 是替身（见 fake_serial_port/QSerialPort），
    // 用它的枚举就等于"拿替身的定义去验替身"，是循环论证。
    // 裸数值钉住的是 Qt 的真实取值（Data8=8、NoParity=0、OneStop=1、
    // NoFlowControl=0），改错了这里会直接红。
    QCOMPARE(r.dataBits, 8);       // QSerialPort::Data8
    QCOMPARE(r.parity, 0);         // QSerialPort::NoParity
    QCOMPARE(r.stopBits, 1);       // QSerialPort::OneStop
    QCOMPARE(r.flowControl, 0);    // QSerialPort::NoFlowControl

    // 四项参数各设置一次：多设/漏设都要能被看出来。
    QCOMPARE(r.dataBitsCalls, 1);
    QCOMPARE(r.parityCalls, 1);
    QCOMPARE(r.stopBitsCalls, 1);
    QCOMPARE(r.flowControlCalls, 1);

    // 打开模式必须是可读可写（只写会漏掉后续可能的回读）。
    QCOMPARE(r.openModeReadWrite, true);
    QCOMPARE(r.openCalls, 1);
}

void TestSerialLight::openUsesTheRequestedBaudRate()
{
    SerialLight light;
    QVERIFY(light.open(QString::fromLatin1(kPortName), 115200));
    QCOMPARE(fakeSerialPort().baudRate, 115200);
    QCOMPARE(fakeSerialPort().portName, QString::fromLatin1(kPortName));
    QCOMPARE(fakeSerialPort().setPortNameCalls, 1);
    QCOMPARE(fakeSerialPort().setBaudRateCalls, 1);
}

void TestSerialLight::defaultBaudRateIs9600()
{
    SerialLight light;
    // 头文件里默认实参是 QSerialPort::Baud9600，这里按**数值**钉住，
    // 免得将来有人把默认值悄悄改掉而 UI 那边没同步。
    QVERIFY(light.open(QString::fromLatin1(kPortName)));
    QCOMPARE(fakeSerialPort().baudRate, 9600);
}

void TestSerialLight::openWhenAlreadyOpenClosesFirst()
{
    SerialLight light;
    QVERIFY(light.open(QStringLiteral("/dev/ttyUSB0"), 9600));
    QCOMPARE(fakeSerialPort().openCalls, 1);
    QCOMPARE(fakeSerialPort().closeCalls, 0);

    QVERIFY(light.open(QStringLiteral("/dev/ttyUSB1"), 4800));
    // 已打开时必须**先关再开**，否则会泄漏上一个句柄。
    QCOMPARE(fakeSerialPort().closeCalls, 1);
    QCOMPARE(fakeSerialPort().openCalls, 2);
    QCOMPARE(fakeSerialPort().portName, QStringLiteral("/dev/ttyUSB1"));
    QCOMPARE(fakeSerialPort().baudRate, 4800);
    QCOMPARE(light.isOpen(), true);
}

void TestSerialLight::openFailureReturnsFalseAndEmitsError()
{
    fakeSerialPort().failOpen = true;
    fakeSerialPort().errorString = QStringLiteral("No such file or directory");

    SerialLight light;
    QSignalSpy errors(&light, &SerialLight::errorOccurred);
    LogCapture cap;

    QCOMPARE(light.open(QString::fromLatin1(kPortName), 9600), false);
    QCOMPARE(errors.count(), 1);
    QCOMPARE(light.isOpen(), false);
    // 失败也必须走 qWarning，否则现场日志里什么都看不到。
    QVERIFY2(cap.contains(QStringLiteral("[灯控]")),
             qPrintable(cap.joined()));
}

void TestSerialLight::openFailureMessageContainsPortNameAndReason()
{
    fakeSerialPort().failOpen = true;
    fakeSerialPort().errorString = QStringLiteral("Permission denied");

    SerialLight light;
    QSignalSpy errors(&light, &SerialLight::errorOccurred);
    QCOMPARE(light.open(QStringLiteral("/dev/ttyS9"), 9600), false);
    QCOMPARE(errors.count(), 1);

    const QString msg = errors.at(0).at(0).toString();
    // 文案必须同时带上"哪个口"和"为什么"，否则排障时只能猜。
    QVERIFY2(msg.contains(QStringLiteral("/dev/ttyS9")), qPrintable(msg));
    QVERIFY2(msg.contains(QStringLiteral("Permission denied")), qPrintable(msg));
    QVERIFY2(msg.contains(QStringLiteral("串口打开失败")), qPrintable(msg));
}

void TestSerialLight::failedOpenLeavesPortClosed()
{
    fakeSerialPort().failOpen = true;
    SerialLight light;
    QSignalSpy errors(&light, &SerialLight::errorOccurred);
    QCOMPARE(light.open(QString::fromLatin1(kPortName), 9600), false);

    // 打开失败后**不能**处于"已打开"状态，否则后续 sendCommand 会误发。
    QCOMPARE(light.isOpen(), false);

    QSignalSpy errs2(&light, &SerialLight::errorOccurred);
    QCOMPARE(light.sendCommand(QStringLiteral("desk")), false);
    QCOMPARE(fakeSerialPort().writes.size(), 0);
    Q_UNUSED(errs2);
}

void TestSerialLight::successfulOpenEmitsNoError()
{
    SerialLight light;
    QSignalSpy errors(&light, &SerialLight::errorOccurred);
    QVERIFY(light.open(QString::fromLatin1(kPortName), 9600));
    // 成功路径不得报错（正对照：证明 errorOccurred 不是"总会发"）。
    QCOMPARE(errors.count(), 0);
}

// ---------------------------------------------------------------------------
// isOpen() / close()
// ---------------------------------------------------------------------------

void TestSerialLight::isOpenIsFalseBeforeOpen()
{
    SerialLight light;
    QCOMPARE(light.isOpen(), false);
}

void TestSerialLight::isOpenTracksOpenAndClose()
{
    SerialLight light;
    QCOMPARE(light.isOpen(), false);
    QVERIFY(light.open(QString::fromLatin1(kPortName), 9600));
    QCOMPARE(light.isOpen(), true);
    light.close();
    QCOMPARE(light.isOpen(), false);
}

void TestSerialLight::closeWithoutOpenIsSafe()
{
    SerialLight light;
    light.close(); // m_port 是 nullptr
    QCOMPARE(fakeSerialPort().closeCalls, 0);
    QCOMPARE(light.isOpen(), false);
}

void TestSerialLight::closeIsIdempotent()
{
    SerialLight light;
    QVERIFY(light.open(QString::fromLatin1(kPortName), 9600));
    light.close();
    QCOMPARE(fakeSerialPort().closeCalls, 1);
    light.close();
    // 已经关了就不该再调 close()（真串口上重复关会多一次系统调用与报错）。
    QCOMPARE(fakeSerialPort().closeCalls, 1);
}

// ---------------------------------------------------------------------------
// sendCommand()
// ---------------------------------------------------------------------------

void TestSerialLight::sendCommandWritesTheConfiguredBytes()
{
    SerialLight light;
    QVERIFY(light.open(QString::fromLatin1(kPortName), 9600));

    const QByteArray expected = AppConfig::instance().lightCommand(
        QStringLiteral("desk"));
    QVERIFY2(!expected.isEmpty(), "配置里应当有 desk 指令");

    QCOMPARE(light.sendCommand(QStringLiteral("desk")), true);
    QCOMPARE(fakeSerialPort().writes.size(), 1);
    // 必须**逐字节**等于配置里的指令，一个字节都不能变。
    QCOMPARE(fakeSerialPort().writes.at(0), expected);
}

void TestSerialLight::sendCommandFlushesOnce()
{
    SerialLight light;
    QVERIFY(light.open(QString::fromLatin1(kPortName), 9600));
    QCOMPARE(fakeSerialPort().flushCalls, 0);

    QVERIFY(light.sendCommand(QStringLiteral("wall")));
    // 写完必须 flush，否则指令可能停在缓冲区里发不出去。
    QCOMPARE(fakeSerialPort().flushCalls, 1);
}

void TestSerialLight::sendCommandReturnsFalseForUnknownName()
{
    SerialLight light;
    QVERIFY(light.open(QString::fromLatin1(kPortName), 9600));

    QSignalSpy errors(&light, &SerialLight::errorOccurred);
    QCOMPARE(light.sendCommand(QStringLiteral("不存在的灯")), false);
    // 未知指令名不是"设备错误"，因此**不**发 errorOccurred（与基线一致）。
    QCOMPARE(errors.count(), 0);
    QCOMPARE(fakeSerialPort().writes.size(), 0);
    QCOMPARE(fakeSerialPort().flushCalls, 0);
}

void TestSerialLight::unknownNameLogsOnlyTheUnknownBranch()
{
    SerialLight light;
    QVERIFY(light.open(QString::fromLatin1(kPortName), 9600));

    LogCapture cap;
    QCOMPARE(light.sendCommand(QStringLiteral("nope")), false);

    // 这条路径**只**靠日志和"串口未打开"区分，必须断言分得清。
    QVERIFY2(cap.contains(QStringLiteral("未知的指令名称")),
             qPrintable(cap.joined()));
    QVERIFY2(!cap.contains(QStringLiteral("串口未打开")),
             qPrintable(cap.joined()));
}

void TestSerialLight::sendCommandOnClosedPortReturnsFalse()
{
    SerialLight light;
    // 从未打开：与基线一致，只记日志、不打弹窗、不阻塞。
    QSignalSpy errors(&light, &SerialLight::errorOccurred);
    QCOMPARE(light.sendCommand(QStringLiteral("desk")), false);
    QCOMPARE(errors.count(), 0);
}

void TestSerialLight::closedPortLogsOnlyTheNotOpenBranch()
{
    SerialLight light;
    LogCapture cap;
    QCOMPARE(light.sendCommand(QStringLiteral("desk")), false);

    QVERIFY2(cap.contains(QStringLiteral("串口未打开")),
             qPrintable(cap.joined()));
    // 指令名是合法的，所以不能报"未知的指令名称"。
    QVERIFY2(!cap.contains(QStringLiteral("未知的指令名称")),
             qPrintable(cap.joined()));
}

void TestSerialLight::sendCommandDoesNotWriteWhenClosed()
{
    SerialLight light;
    QCOMPARE(light.sendCommand(QStringLiteral("desk")), false);
    // 未打开时绝不能落到 write() 上（那会解引用空/关着的串口）。
    QCOMPARE(fakeSerialPort().writes.size(), 0);
    QCOMPARE(fakeSerialPort().openCalls, 0);
}

void TestSerialLight::unknownNameIsCheckedBeforePortState()
{
    // 唯一能把两个前置检查的**次序**区分开的场景：串口没开 **且** 指令名未知。
    // 两种次序都会返回 false，所以只能靠**日志走哪一条分支**来判定。
    SerialLight light; // 从未打开

    LogCapture cap;
    QCOMPARE(light.sendCommand(QStringLiteral("完全不存在的灯")), false);

    // 指令名检查在前：应当报"未知的指令名称"，而不是"串口未打开"。
    // 这个次序是有意的 —— 配置写错（名字打错）比设备没插更该被明确指出，
    // 否则现场会一直去查串口线，而真正的问题是配置里的键名。
    QVERIFY2(cap.contains(QStringLiteral("未知的指令名称")),
             qPrintable(cap.joined()));
    QVERIFY2(!cap.contains(QStringLiteral("串口未打开")),
             qPrintable(cap.joined()));
    QCOMPARE(fakeSerialPort().writes.size(), 0);
}

void TestSerialLight::partialWriteReturnsFalseAndEmitsError()
{
    SerialLight light;
    QVERIFY(light.open(QString::fromLatin1(kPortName), 9600));

    const int full = AppConfig::instance()
                         .lightCommand(QStringLiteral("work"))
                         .size();
    QVERIFY(full > 1);
    fakeSerialPort().writeReturnOverride = full - 1; // 少写一个字节

    QSignalSpy errors(&light, &SerialLight::errorOccurred);
    QCOMPARE(light.sendCommand(QStringLiteral("work")), false);
    QCOMPARE(errors.count(), 1);

    const QString msg = errors.at(0).at(0).toString();
    QVERIFY2(msg.contains(QStringLiteral("写入不完整")), qPrintable(msg));
    QVERIFY2(msg.contains(QStringLiteral("work")), qPrintable(msg));
}

void TestSerialLight::partialWriteStillFlushes()
{
    SerialLight light;
    QVERIFY(light.open(QString::fromLatin1(kPortName), 9600));
    fakeSerialPort().writeReturnOverride = 0;

    QSignalSpy errors(&light, &SerialLight::errorOccurred);
    QCOMPARE(light.sendCommand(QStringLiteral("work")), false);
    // flush() 在长度校验**之前**调用，所以失败路径上它也已经调过一次。
    // 这是基线的实际顺序，钉住它以免将来"顺手挪动"改变时序。
    QCOMPARE(fakeSerialPort().flushCalls, 1);
}

void TestSerialLight::sendCommandCanBeRepeated()
{
    SerialLight light;
    QVERIFY(light.open(QString::fromLatin1(kPortName), 9600));

    QVERIFY(light.sendCommand(QStringLiteral("desk")));
    QVERIFY(light.sendCommand(QStringLiteral("work")));
    QVERIFY(light.sendCommand(QStringLiteral("desk")));

    const AppConfig& cfg = AppConfig::instance();
    QCOMPARE(fakeSerialPort().writes.size(), 3);
    QCOMPARE(fakeSerialPort().writes.at(0), cfg.lightCommand(QStringLiteral("desk")));
    QCOMPARE(fakeSerialPort().writes.at(1), cfg.lightCommand(QStringLiteral("work")));
    QCOMPARE(fakeSerialPort().writes.at(2), cfg.lightCommand(QStringLiteral("desk")));
    QCOMPARE(fakeSerialPort().flushCalls, 3);
}

// ---------------------------------------------------------------------------
// 灯控指令契约
// ---------------------------------------------------------------------------

void TestSerialLight::defaultCommandsMatchTheFrozenBytes_data()
{
    QTest::addColumn<QString>("name");
    QTest::addColumn<QByteArray>("hex");

    // 期望值**独立写死**在这里，不从 app_config.cpp 抄。
    // 这些字节是灯控模块的既定协议，改了就必须有人显式确认。
    QTest::newRow("desk") << QStringLiteral("desk")
                          << QByteArray::fromHex("FD034C12045DDF");
    QTest::newRow("work") << QStringLiteral("work")
                          << QByteArray::fromHex("FD034C12025DDF");
    QTest::newRow("work_round") << QStringLiteral("work_round")
                                << QByteArray::fromHex("FD039736F44FDF");
    QTest::newRow("desk_round") << QStringLiteral("desk_round")
                                << QByteArray::fromHex("FD039736F250DF");
    QTest::newRow("wall") << QStringLiteral("wall")
                          << QByteArray::fromHex("FD039736F150DF");
}

void TestSerialLight::defaultCommandsMatchTheFrozenBytes()
{
    QFETCH(QString, name);
    QFETCH(QByteArray, hex);
    QCOMPARE(AppConfig::instance().lightCommand(name), hex);
}

// ---------------------------------------------------------------------------
// 正对照
// ---------------------------------------------------------------------------

void TestSerialLight::logCapturePipelineWorks()
{
    // 上面多条断言都是"日志里**没有**某个串"或者"有某个串"。
    // 若捕获管道本身坏了，那些断言会**真空成立** —— 这个用例保证管道是通的，
    // 并且 qDebug/qWarning 两个级别都能被捕获到。
    LogCapture cap;
    qWarning() << "[灯控]" << "对照-warning";
    qDebug() << "[灯控]" << "对照-debug";
    QVERIFY2(cap.contains(QStringLiteral("对照-warning")),
             qPrintable(cap.joined()));
    QVERIFY2(cap.contains(QStringLiteral("对照-debug")),
             qPrintable(cap.joined()));
}

QTEST_MAIN(TestSerialLight)
#include "test_serial_light.moc"
