/**
 * @file test_widget.cpp
 * @brief 室内机主窗口 `src/ui/widget.cpp` 的行为测试（影子头方案）。
 *
 * 为什么值得单独钉
 * ----------------
 * `src/ui/widget.cpp`（383 行）是室内机的门面，也是**此前从未被任何测试目标
 * 链接过**的最大一块产线代码。它自己不含协议编解码，但决定了三件会直接影响
 * 互操作的事：
 *   1. **信令编排**：收到 `call` 弹通话浮层、`stopsend` 关掉它；浮层信号
 *      `accepted` / `hangupClicked` 必须**逐字节**回 `accept\n` / `recstop\n`
 *      给同一个连接 —— 这是室内机→门口机方向的线上字节。
 *   2. **开锁广播**：`unlock\n` 要发给所有在线门口机。
 *   3. **监看生命周期**：`m_monitor->toggle()` 的开关、以及
 *      **退出程序时是否通知门口机 `stop`**（由 MonitorClient::stop() 落实，
 *      但触发路径正是本文件的 Widget 析构）。
 *
 * 另一个价值是 P2 那类缺陷：本文件的按钮槽全部靠 `uic` 的
 * `connectSlotsByName` 自动接线。测试**通过真实按钮的 `click()`** 驱动，
 * 于是"槽名与 objectName 不匹配""被显式 connect 了第二次"这类问题会直接
 * 变成用例失败（双击会让灯控指令写两遍，见 lightButtonsSendExactCommands）。
 *
 * 做法：影子头 + 真实 widget.cpp
 * -----------------------------
 *   - `hal/serial_light.h` 里的 QSerialPort 用既有影子
 *     tests/fake_serial_port/QSerialPort 替掉（define ACC_SERIAL_LIGHT_TEST），
 *     `serial_light.cpp` 本身是**真的**；
 *   - `ui/form_phonecall.h` 用 tests/shadows/ui/form_phonecall.h 替掉
 *     （define ACC_WIDGET_TEST），避开 Qt5::Multimedia 与整个通话浮层，
 *     但 `widget.cpp` 一个字节都不改；
 *   - `ui/widget.h`、`config/app_config.cpp`、`core/net/{signaling_server,
 *     monitor_client}.cpp`、`core/weather/weather_service.cpp` 全部是**真的**。
 *
 * 隔离：网络、串口、天气在测试里都不许碰真实资源
 * ----------------------------------------------
 *   - 信令端口每个用例现取一个空闲端口，写进临时 JSON 配置再 load；
 *   - 天气 URL 置空（`refresh()` 因此早退，不发任何请求）；
 *   - 门口机地址设为 127.0.0.2，UDP 50000 由本文件的替身门口机接收；
 *   - 串口写进替身记录；
 *   - 相关 `ACCESSTERMINAL_*` / `SMARTSERVER_*` 环境变量在 initTestCase 里
 *     清掉，保证配置只来自本测试写的 JSON（否则开发机上残留的环境变量会
 *     悄悄改变被测行为）。
 */
#include <QApplication>
#include <QBuffer>
#include <QColor>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QHostAddress>
#include <QImage>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QPushButton>
#include <QRegularExpression>
#include <QScopedPointer>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTest>
#include <QUdpSocket>

#include "config/app_config.h"
#include "core/net/protocol.h"
#include "fake_form_phonecall.h"
#include "fake_serial_port.h"
#include "ui/form_phonecall.h"
#include "ui/widget.h"

using accessterminal::AppConfig;
using accessterminal::protocol::Signal;

namespace {

/// 替身门口机地址（真实门口机的默认值是 192.168.1.8，测试里不能碰）。
const char* const kFakeDeviceIp = "127.0.0.2";
/// 远程监看端口是协议常量，必须用真实的 50000。
const quint16 kPreviewPort = accessterminal::protocol::kPreviewPort;

/// 轮询等待（会跑事件循环，跨线程/信号都在同一线程内投递）。
template <typename Predicate>
bool waitFor(Predicate pred, int timeoutMs = 3000)
{
    QElapsedTimer timer;
    timer.start();
    while (!pred()) {
        if (timer.elapsed() > timeoutMs) {
            return false;
        }
        QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
        QTest::qWait(5);
    }
    return true;
}

/// 造一帧真实 JPEG（走 Qt 自己的编码器，不手搓字节）。
QByteArray makeJpeg(int w = 64, int h = 48, int hue = 0)
{
    QImage img(w, h, QImage::Format_RGB32);
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            img.setPixel(x, y, QColor::fromHsv((hue + x) % 360, 200, 200).rgb());
        }
    }
    QByteArray bytes;
    QBuffer buf(&bytes);
    buf.open(QIODevice::WriteOnly);
    img.save(&buf, "JPEG", 80);
    return bytes;
}

/// `QLabel::pixmap()` 在 Qt 5.15 起新增了"按值返回"的推荐重载；
/// 本工程下限是 Qt 5.12，用版本分支把两边的写法都收敛到这一处。
bool labelHasPixmap(QLabel* l)
{
#if QT_VERSION >= QT_VERSION_CHECK(5, 15, 0)
    return !l->pixmap(Qt::ReturnByValue).isNull();
#else
    const QPixmap* p = l->pixmap();
    return p != nullptr && !p->isNull();
#endif
}

/**
 * @brief 替身门口机（UDP 50000），与 test_monitor_client.cpp 同一套路。
 *
 * 绑在 127.0.0.2:50000（ShareAddress），于是室内机 MonitorClient
 * （绑 Any:50000）发出的 getframe / stop 都能被它收到；
 * 它也能把 JPEG 发到 127.0.0.1:50000 推给室内机。
 */
class FakeTerminal
{
public:
    bool bind()
    {
        m_sock = new QUdpSocket();
        const bool ok = m_sock->bind(QHostAddress(kFakeDeviceIp), kPreviewPort,
                                     QUdpSocket::ShareAddress
                                         | QUdpSocket::ReuseAddressHint);
        return ok;
    }

    ~FakeTerminal() { delete m_sock; }

    /// 收下当前挂起的数据报，返回本次新收到的条数。
    int pump()
    {
        int got = 0;
        while (m_sock->hasPendingDatagrams()) {
            QByteArray d;
            d.resize(static_cast<int>(m_sock->pendingDatagramSize()));
            const qint64 n = m_sock->readDatagram(d.data(), d.size());
            if (n < 0) {
                continue;
            }
            if (n < d.size()) {
                d.resize(static_cast<int>(n));
            }
            m_received.append(d);
            ++got;
        }
        return got;
    }

    bool waitForCount(int n, int timeoutMs = 3000)
    {
        return waitFor([&]() { pump(); return m_received.size() >= n; }, timeoutMs);
    }

    int count() const { return m_received.size(); }
    QByteArray at(int i) const { return m_received.value(i); }

    /// 按真实门口机的做法，把一帧推给室内机的监看端口。
    qint64 sendToClientPort(const QByteArray& payload)
    {
        return m_sock->writeDatagram(payload, QHostAddress::LocalHost, kPreviewPort);
    }

private:
    QUdpSocket* m_sock = nullptr;
    QList<QByteArray> m_received;
};

} // namespace

class TestWidget : public QObject
{
    Q_OBJECT

private slots:
    void initTestCase();
    void init();

    // ---- 配置隔离自证 ----
    void configIsolationIsActuallyInEffect();

    // ---- 界面开关 ----
    void powerButtonTogglesScreenOffStyle();
    void homeButtonTogglesLightPanel();
    void timeLabelsUseExpectedFormat();

    // ---- 灯控：Widget -> SerialLight -> AppConfig -> 串口字节 ----
    void lightButtonsSendExactCommands();

    // ---- 信令编排 ----
    void incomingCallCreatesCallForm();
    void secondCallDoesNotCreateSecondFormButRetargetsReply();
    void offlineStateSuppressesRing();
    void acceptedRepliesAcceptOnSameConnection();
    void hangupRepliesRecstopOnSameConnection();
    void stopsendClosesCallFormAndAllowsNextCall();
    void unlockFromDoorStationHasNoLocalEffect();
    void unexpectedUplinkSignalsAreIgnored();
    void lockButtonBroadcastsUnlock();

    // ---- 远程监看 ----
    void getFrameTogglesMonitorAndSendsWireBytes();
    void videoFrameIgnoredWhileCameraInactive();
    void nullFrameIgnoredWhileCameraActive();
    void destructorWhileMonitoringNotifiesTerminalStop();
    void destructorClosesCallForm();

private:
    quint16 pickFreePort();
    /// 写一份隔离用 JSON 配置并 load；返回所用路径。
    QString loadIsolatedConfig(quint16 signalingPort);
    /// 按当前配置造一个已 show 的 Widget（调用方负责生命周期）。
    Widget* makeWidget();
    void writeSignal(QTcpSocket& sock, Signal signal);
    QPushButton* button(Widget* w, const char* name);
    QLabel* label(Widget* w, const char* name);

    int m_configSeq = 0;
};

void TestWidget::initTestCase()
{
    // 清掉可能残留的环境覆盖，保证配置只来自本测试写的 JSON。
    const char* const names[] = {
        "SMARTSERVER_SELF_IP", "SMARTSERVER_DEVICE_IP",
        "ACCESSTERMINAL_NETWORK_SELF_IP", "ACCESSTERMINAL_NETWORK_DEVICE_IP",
        "ACCESSTERMINAL_NETWORK_SIGNALING_PORT",
        "ACCESSTERMINAL_HARDWARE_SERIAL_PORT", "ACCESSTERMINAL_WEATHER_URL",
        "ACCESSTERMINAL_MEDIA_RINGTONE_VOLUME",
    };
    for (const char* n : names) {
        qunsetenv(n);
    }
}

void TestWidget::init()
{
    // 每个用例都从干净的替身记录开始，否则跨用例的写次数会互相污染。
    resetFakeSerialPort();
    resetFakeForm();
}

quint16 TestWidget::pickFreePort()
{
    // 让内核分配一个空闲端口再立刻释放；Widget 构造时 SignalingServer 会
    // listen 它。若沿用固定端口，前一个用例的监听可能还没释放。
    QTcpServer probe;
    if (!probe.listen(QHostAddress::LocalHost, 0)) {
        return 0;
    }
    const quint16 port = probe.serverPort();
    probe.close();
    return port;
}

QString TestWidget::loadIsolatedConfig(quint16 signalingPort)
{
    QJsonObject net;
    net.insert(QStringLiteral("self_ip"), QStringLiteral("127.0.0.1"));
    net.insert(QStringLiteral("device_ip"), QString::fromLatin1(kFakeDeviceIp));
    net.insert(QStringLiteral("signaling_port"), static_cast<int>(signalingPort));

    QJsonObject hw;
    hw.insert(QStringLiteral("serial_port"), QStringLiteral("ACC_TEST_FAKE_PORT"));

    // 空 URL => WeatherService::refresh() 早退，测试期间不发任何网络请求。
    QJsonObject weather;
    weather.insert(QStringLiteral("url"), QString());

    QJsonObject media;
    media.insert(QStringLiteral("ringtone_volume"), 0);

    QJsonObject root;
    root.insert(QStringLiteral("network"), net);
    root.insert(QStringLiteral("hardware"), hw);
    root.insert(QStringLiteral("weather"), weather);
    root.insert(QStringLiteral("media"), media);

    const QString path =
        QDir(QDir::tempPath())
            .filePath(QStringLiteral("acc_widget_test_config_%1.json")
                          .arg(++m_configSeq));
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        return QString();
    }
    file.write(QJsonDocument(root).toJson());
    file.close();

    AppConfig::instance().load(path);
    return path;
}

Widget* TestWidget::makeWidget()
{
    Widget* w = new Widget();
    w->show();
    return w;
}

void TestWidget::writeSignal(QTcpSocket& sock, Signal signal)
{
    sock.write(accessterminal::protocol::frame(signal));
    sock.flush();
}

QPushButton* TestWidget::button(Widget* w, const char* name)
{
    return w->findChild<QPushButton*>(QString::fromLatin1(name));
}

QLabel* TestWidget::label(Widget* w, const char* name)
{
    return w->findChild<QLabel*>(QString::fromLatin1(name));
}

// ===========================================================================
// 配置隔离自证
// ===========================================================================

/**
 * 必要性：下面所有用例都建立在"信令端口、门口机地址、天气 URL 已被隔离"
 * 之上。若 JSON 没写进去、或某个环境变量把值又覆盖回去了，用例会以各种
 * 面目诡异失败（连不上、真去请求外网、往 192.168.1.8 发包）。
 * 这条把前提本身变成断言。
 */
void TestWidget::configIsolationIsActuallyInEffect()
{
    const quint16 port = pickFreePort();
    QVERIFY(port != 0);
    QVERIFY(!loadIsolatedConfig(port).isEmpty());

    QCOMPARE(AppConfig::instance().deviceIp(), QString::fromLatin1(kFakeDeviceIp));
    QCOMPARE(static_cast<int>(AppConfig::instance().signalingPort()),
             static_cast<int>(port));
    QVERIFY2(AppConfig::instance().weatherUrl().isEmpty(),
             "天气 URL 必须为空，否则测试会真的去请求外网");
}

// ===========================================================================
// 界面开关
// ===========================================================================

void TestWidget::powerButtonTogglesScreenOffStyle()
{
    QVERIFY(!loadIsolatedConfig(pickFreePort()).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    QWidget* main = w->findChild<QWidget*>(QStringLiteral("widget_main"));
    QVERIFY(main);

    QPushButton* power = button(w.data(), "btn_power");
    QVERIFY(power);

    // 第一次：黑屏。样式表里必须出现 black，且不再贴背景图。
    power->click();
    QVERIFY2(main->styleSheet().contains(QStringLiteral("black")),
             "第一次点电源键应进入黑屏（black）");

    // 第二次：还原背景图。
    power->click();
    QVERIFY2(main->styleSheet().contains(QStringLiteral("border-image")),
             "第二次点电源键应还原背景图（border-image）");
    QVERIFY2(main->styleSheet().contains(QStringLiteral("smartbg")),
             "还原的应当是重构前那张背景图 :/pic/smartbg.png");
}

void TestWidget::homeButtonTogglesLightPanel()
{
    QVERIFY(!loadIsolatedConfig(pickFreePort()).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    QWidget* panel = w->findChild<QWidget*>(QStringLiteral("widget_light"));
    QVERIFY(panel);
    QVERIFY2(panel->isHidden(), "构造后灯光面板应先隐藏");

    QPushButton* home = button(w.data(), "btn_home");
    QVERIFY(home);

    home->click();
    QVERIFY2(panel->isVisible(), "点主键应显示灯光面板");

    home->click();
    QVERIFY2(!panel->isVisible(), "再点主键应重新隐藏灯光面板");
}

void TestWidget::timeLabelsUseExpectedFormat()
{
    QVERIFY(!loadIsolatedConfig(pickFreePort()).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    QLabel* date = label(w.data(), "labelDate");
    QLabel* time = label(w.data(), "labelTime_2");
    QVERIFY(date);
    QVERIFY(time);

    // 构造时已经调用过一次 time_reflash()。
    QVERIFY2(QRegularExpression(QStringLiteral("^\\d{4}-\\d{2}-\\d{2}$"))
                 .match(date->text())
                 .hasMatch(),
             qPrintable("labelDate 格式应为 yyyy-MM-dd，实际: " + date->text()));
    QVERIFY2(QRegularExpression(QStringLiteral("^\\d{2}:\\d{2}:\\d{2}$"))
                 .match(time->text())
                 .hasMatch(),
             qPrintable("labelTime_2 格式应为 HH:mm:ss，实际: " + time->text()));
}

// ===========================================================================
// 灯控
// ===========================================================================

/**
 * 这条把整条链路串起来验：
 *   按钮 click()（含 uic 自动接线）-> Widget::on_btn_tea_clicked
 *   -> SerialLight::sendCommand("desk_round") -> AppConfig::lightCommand()
 *   -> 影子 QSerialPort 收到的**逐字节**指令。
 *
 * 顺带钉住 P2 那类"退格双删"缺陷：若某个槽被显式 connect 了第二次，
 * 一次 click() 会写两遍，下面的 QCOMPARE(writes.size(), 1) 立刻失败。
 */
void TestWidget::lightButtonsSendExactCommands()
{
    QVERIFY(!loadIsolatedConfig(pickFreePort()).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    // 构造时 open() 过一次；清掉记录，只留点击产生的写。
    resetFakeSerialPort();

    struct Case {
        const char* buttonName;
        const char* commandName;
    };
    const Case cases[] = {
        {"btn_tea", "desk_round"},
        {"btn_teab", "work_round"},
        {"btn_white", "desk"},
    };

    for (const Case& c : cases) {
        QPushButton* btn = button(w.data(), c.buttonName);
        QVERIFY2(btn, c.buttonName);
        btn->click();

        QCOMPARE(fakeSerialPort().writes.size(), 1);
        QCOMPARE(fakeSerialPort().writes.at(0),
                 AppConfig::instance().lightCommand(QString::fromLatin1(c.commandName)));
        resetFakeSerialPort();
    }
}

// ===========================================================================
// 信令编排
// ===========================================================================

void TestWidget::incomingCallCreatesCallForm()
{
    const quint16 port = pickFreePort();
    QVERIFY(!loadIsolatedConfig(port).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    QTcpSocket client;
    client.connectToHost(QHostAddress::LocalHost, port);
    QVERIFY(client.waitForConnected(2000));

    writeSignal(client, Signal::Call);
    QVERIFY2(waitFor([]() { return fakeForm().constructed == 1; }),
             "收到 call 必须弹出通话浮层");
    QVERIFY2(fakeForm().last && fakeForm().last->isVisible(),
             "来电浮层必须真的显示出来（不是只 new 了出来）");

    // label_off 默认隐藏 => playRing 为 true。
    QVERIFY2(fakeForm().lastPlayRing, "非离线状态下来电应响铃");
}

void TestWidget::secondCallDoesNotCreateSecondFormButRetargetsReply()
{
    const quint16 port = pickFreePort();
    QVERIFY(!loadIsolatedConfig(port).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    QTcpSocket first;
    QTcpSocket second;
    first.connectToHost(QHostAddress::LocalHost, port);
    QVERIFY(first.waitForConnected(2000));
    writeSignal(first, Signal::Call);
    QVERIFY(waitFor([]() { return fakeForm().constructed == 1; }));

    second.connectToHost(QHostAddress::LocalHost, port);
    QVERIFY(second.waitForConnected(2000));
    writeSignal(second, Signal::Call);

    // 给事件循环一点时间：若会重复弹窗，这里就会变成 2。
    QTest::qWait(150);
    QCOMPARE(fakeForm().constructed, 1);

    // 但回执目标必须更新到**最后一次**来电的那个连接。
    QVERIFY(fakeForm().last);
    fakeForm().last->emitAcceptedForTest();

    QVERIFY2(waitFor([&]() { return second.bytesAvailable() > 0; }),
             "accept 应回给最后一次来电的连接");
    QCOMPARE(second.readAll(), QByteArrayLiteral("accept\n"));
    QCOMPARE(first.bytesAvailable(), 0);
}

void TestWidget::offlineStateSuppressesRing()
{
    const quint16 port = pickFreePort();
    QVERIFY(!loadIsolatedConfig(port).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    // 先进入"离线"状态：label_off 变为可见。
    QPushButton* offline = button(w.data(), "btn_offline");
    QVERIFY(offline);
    offline->click();
    QVERIFY(label(w.data(), "label_off")->isVisible());

    QTcpSocket client;
    client.connectToHost(QHostAddress::LocalHost, port);
    QVERIFY(client.waitForConnected(2000));
    writeSignal(client, Signal::Call);

    QVERIFY(waitFor([]() { return fakeForm().constructed == 1; }));
    QVERIFY2(!fakeForm().lastPlayRing, "离线状态下来电不应响铃");
}

void TestWidget::acceptedRepliesAcceptOnSameConnection()
{
    const quint16 port = pickFreePort();
    QVERIFY(!loadIsolatedConfig(port).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    QTcpSocket client;
    client.connectToHost(QHostAddress::LocalHost, port);
    QVERIFY(client.waitForConnected(2000));
    writeSignal(client, Signal::Call);
    QVERIFY(waitFor([]() { return fakeForm().constructed == 1; }));
    QVERIFY(fakeForm().last);

    fakeForm().last->emitAcceptedForTest();

    QVERIFY2(waitFor([&]() { return client.bytesAvailable() > 0; }),
             "接通后必须回 accept");
    // 逐字节：'accept' + '\n'。门口机按行解析，少了终止符就永远等下去。
    QCOMPARE(client.readAll(), QByteArrayLiteral("accept\n"));
}

void TestWidget::hangupRepliesRecstopOnSameConnection()
{
    const quint16 port = pickFreePort();
    QVERIFY(!loadIsolatedConfig(port).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    QTcpSocket client;
    client.connectToHost(QHostAddress::LocalHost, port);
    QVERIFY(client.waitForConnected(2000));
    writeSignal(client, Signal::Call);
    QVERIFY(waitFor([]() { return fakeForm().constructed == 1; }));
    QVERIFY(fakeForm().last);

    fakeForm().last->emitHangupForTest();

    QVERIFY2(waitFor([&]() { return client.bytesAvailable() > 0; }),
             "挂断后必须回 recstop");
    QCOMPARE(client.readAll(), QByteArrayLiteral("recstop\n"));
}

void TestWidget::stopsendClosesCallFormAndAllowsNextCall()
{
    const quint16 port = pickFreePort();
    QVERIFY(!loadIsolatedConfig(port).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    QTcpSocket client;
    client.connectToHost(QHostAddress::LocalHost, port);
    QVERIFY(client.waitForConnected(2000));
    writeSignal(client, Signal::Call);
    QVERIFY(waitFor([]() { return fakeForm().constructed == 1; }));

    // 门口机主动停止推流 => 浮层必须关掉（close + WA_DeleteOnClose）。
    writeSignal(client, Signal::StopSend);
    QVERIFY2(waitFor([]() { return fakeForm().destroyed == 1; }),
             "收到 stopsend 必须关闭通话浮层");

    // 关掉之后必须能再次来电：若 m_callForm 没被清空，这里永远弹不出来。
    writeSignal(client, Signal::Call);
    QVERIFY2(waitFor([]() { return fakeForm().constructed == 2; }),
             "stopsend 之后必须还能再次弹出来电浮层");
}

void TestWidget::unlockFromDoorStationHasNoLocalEffect()
{
    const quint16 port = pickFreePort();
    QVERIFY(!loadIsolatedConfig(port).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    QTcpSocket client;
    client.connectToHost(QHostAddress::LocalHost, port);
    QVERIFY(client.waitForConnected(2000));

    writeSignal(client, Signal::Unlock);
    QTest::qWait(200);

    QCOMPARE(fakeForm().constructed, 0);
    QCOMPARE(client.bytesAvailable(), 0);
}

void TestWidget::unexpectedUplinkSignalsAreIgnored()
{
    const quint16 port = pickFreePort();
    QVERIFY(!loadIsolatedConfig(port).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    QTcpSocket client;
    client.connectToHost(QHostAddress::LocalHost, port);
    QVERIFY(client.waitForConnected(2000));

    // accept / recstop / getframe / stop 都是室内机→门口机方向或监看信令，
    // 门口机不应上行这些。收到只应记日志，不弹窗、不回执、不崩。
    const Signal unexpected[] = {Signal::Accept, Signal::RecStop,
                                 Signal::GetFrame, Signal::Stop};
    for (Signal s : unexpected) {
        writeSignal(client, s);
    }
    QTest::qWait(200);

    QCOMPARE(fakeForm().constructed, 0);
    QCOMPARE(client.bytesAvailable(), 0);
}

void TestWidget::lockButtonBroadcastsUnlock()
{
    const quint16 port = pickFreePort();
    QVERIFY(!loadIsolatedConfig(port).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    QTcpSocket client;
    client.connectToHost(QHostAddress::LocalHost, port);
    QVERIFY(client.waitForConnected(2000));
    // 服务端要跑一轮事件循环才会把该连接登记进 m_clients，广播才发得到它。
    QTest::qWait(150);

    QPushButton* lock = button(w.data(), "btn_lock");
    QVERIFY(lock);
    lock->click();

    QVERIFY2(waitFor([&]() { return client.bytesAvailable() > 0; }),
             "点开锁应把 unlock 广播给在线门口机");
    QCOMPARE(client.readAll(), QByteArrayLiteral("unlock\n"));
}

// ===========================================================================
// 远程监看
// ===========================================================================

void TestWidget::getFrameTogglesMonitorAndSendsWireBytes()
{
    FakeTerminal fake;
    QVERIFY2(fake.bind(), "替身门口机应能绑定 127.0.0.2:50000");

    QVERIFY(!loadIsolatedConfig(pickFreePort()).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    QPushButton* cam = button(w.data(), "btngetframe");
    QVERIFY(cam);

    // 开：必须是**裸的** getframe（UDP 50000 不带 '\n'，与 TCP 8887 不同）。
    cam->click();
    QVERIFY2(fake.waitForCount(1), "打开监看必须发出 getframe");
    QCOMPARE(fake.at(0), QByteArrayLiteral("getframe"));

    // 关：必须发出裸的 stop，门口机据此停掉 50ms 推流定时器。
    cam->click();
    QVERIFY2(fake.waitForCount(2), "关闭监看必须发出 stop");
    QCOMPARE(fake.at(1), QByteArrayLiteral("stop"));
}

/**
 * 这条钉的是 `onVideoFrameReady()` 里的 `!m_cameraActive` 门控。
 *
 * 门槛在于：**关掉监看后 MonitorClient 的 socket 并没有关**（toggle 只发 stop，
 * 只有 stop() 才关 socket），所以帧仍会到达、frameReceived 仍会 emit。
 * 若门控被去掉，labelcam 会在用户已经关掉监看之后又冒出来 —— 这正是能被
 * 观测到的真实差异，而不是"读代码觉得应该"。
 */
void TestWidget::videoFrameIgnoredWhileCameraInactive()
{
    FakeTerminal fake;
    QVERIFY(fake.bind());

    QVERIFY(!loadIsolatedConfig(pickFreePort()).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    QLabel* cam = label(w.data(), "labelcam");
    QVERIFY(cam);

    QPushButton* btn = button(w.data(), "btngetframe");
    QVERIFY(btn);

    // 开监看。
    btn->click();
    QVERIFY(fake.waitForCount(1));

    // 收到一帧 -> 画面显示出来。
    QVERIFY(fake.sendToClientPort(makeJpeg()) > 0);
    QVERIFY2(waitFor([&]() { return cam->isVisible() && labelHasPixmap(cam); }),
             "接收态下收到完整 JPEG 应显示画面");

    // 关监看 -> 画面立刻隐藏。
    btn->click();
    QVERIFY(fake.waitForCount(2));
    QVERIFY2(!cam->isVisible(), "关闭监看后应立刻隐藏画面");

    // 再推一帧：socket 还开着，帧确实会到 —— 但绝不能把画面又显示出来。
    QVERIFY(fake.sendToClientPort(makeJpeg(32, 32, 120)) > 0);
    QTest::qWait(300);
    QVERIFY2(!cam->isVisible(),
             "m_cameraActive 为 false 时不得显示新帧（门控失效会让画面复活）");
}

/**
 * 钉 `frame.isNull()` 这一半门控：即使处于接收态，空帧也不能触发显示
 * （showCameraFrame 会 setVisible(true) 并设个空 pixmap）。
 */
void TestWidget::nullFrameIgnoredWhileCameraActive()
{
    FakeTerminal fake;
    QVERIFY(fake.bind());

    QVERIFY(!loadIsolatedConfig(pickFreePort()).isEmpty());
    QScopedPointer<Widget> w(makeWidget());

    QLabel* cam = label(w.data(), "labelcam");
    QVERIFY(cam);

    QPushButton* btn = button(w.data(), "btngetframe");
    QVERIFY(btn);
    btn->click();
    QVERIFY(fake.waitForCount(1));

    // 建立已知基线：先藏起来。
    cam->setVisible(false);

    QPixmap nullPixmap;
    QVERIFY(QMetaObject::invokeMethod(w.data(), "onVideoFrameReady",
                                      Qt::DirectConnection,
                                      Q_ARG(QPixmap, nullPixmap)));
    QTest::qWait(100);
    QVERIFY2(!cam->isVisible(), "空帧不得触发画面显示");

    // 反证：真实帧仍然能显示出来（说明上一条不是因为整条路断了）。
    QVERIFY(fake.sendToClientPort(makeJpeg()) > 0);
    QVERIFY2(waitFor([&]() { return cam->isVisible(); }),
             "真实 JPEG 仍应能显示（否则上一条断言无判别力）");
}

/**
 * 这条把"用户在监看中途直接关掉程序"这条**真实退出路径**端到端钉住：
 *   delete Widget -> ~Widget -> 子对象 MonitorClient 析构 -> stop()
 *   -> 向门口机发 stop。
 *
 * MonitorClient::stop() 里那句发送曾经缺失，门口机会永远推流；
 * test_monitor_client.cpp 已在单元层钉住它，这里再从**主窗口**这一层验一遍，
 * 证明触发路径确实经过 Widget 的析构。
 */
void TestWidget::destructorWhileMonitoringNotifiesTerminalStop()
{
    FakeTerminal fake;
    QVERIFY(fake.bind());

    QVERIFY(!loadIsolatedConfig(pickFreePort()).isEmpty());

    {
        QScopedPointer<Widget> w(makeWidget());
        QPushButton* cam = button(w.data(), "btngetframe");
        QVERIFY(cam);
        cam->click();
        QVERIFY(fake.waitForCount(1));
        QCOMPARE(fake.at(0), QByteArrayLiteral("getframe"));
    } // <- Widget 在这里析构（真实退出路径）

    QVERIFY2(fake.waitForCount(2),
             "关闭程序必须通知门口机 stop，否则它会一直推流");
    QCOMPARE(fake.at(1), QByteArrayLiteral("stop"));
}

/**
 * ~Widget 必须显式关掉通话浮层：它是**无父窗口的顶层窗口**，不随 QObject
 * 父子关系销毁；若不关，用户退出后会留下残留窗口与音频设备句柄。
 */
void TestWidget::destructorClosesCallForm()
{
    const quint16 port = pickFreePort();
    QVERIFY(!loadIsolatedConfig(port).isEmpty());

    QTcpSocket client;
    {
        QScopedPointer<Widget> w(makeWidget());
        // Widget 构造时 SignalingServer 才开始 listen，必须排在它后面连。
        client.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(client.waitForConnected(2000));
        writeSignal(client, Signal::Call);
        QVERIFY2(waitFor([]() { return fakeForm().constructed == 1; }),
                 "收到 call 应弹出通话浮层");
    } // <- Widget 析构 -> destroyCallForm() -> close()

    QVERIFY2(waitFor([]() { return fakeForm().destroyed == 1; }),
             "关闭主窗口必须一并关掉无父窗口的通话浮层");
}

int main(int argc, char** argv)
{
    // 无显示环境下自动退到 offscreen；已显式设置平台插件时不覆盖。
    if (qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM")) {
        qputenv("QT_QPA_PLATFORM", QByteArrayLiteral("offscreen"));
    }
    QApplication app(argc, argv);
    TestWidget tc;
    return QTest::qExec(&tc, argc, argv);
}

#include "test_widget.moc"
