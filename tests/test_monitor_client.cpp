/**
 * @file test_monitor_client.cpp
 * @brief MonitorClient（室内机 UDP 50000 远程监看客户端）行为断言。
 *
 * 为什么必须写这个测试
 * --------------------
 * UDP 50000 是**协议硬约束**的一员，而且它的语义和另外三条都不同：
 *
 *   - 门口机**只有收到 `getframe` 之后**才开始按 50ms 定时器推帧；
 *   - 请求文本是**裸的、不带 `'\n'`**（与 TCP 8887 信令不同！）；
 *   - 收到 `stop` 就停推；
 *   - 每包是一帧完整 JPEG，无重组、无重传；
 *   - 请求/停止的**文本身份**必须与门口机侧逐字节一致。
 *
 * 门口机侧（`CameraUdpServer`）已经有 `t113_test_camera_preview` 覆盖了，
 * 但**室内机侧这一半从来没有测过**：`MonitorClient` 的"发什么字节、发到哪个
 * 端口、状态怎么翻转、收到什么才算一帧"全都只靠源码阅读。两条半必须配对，
 * 否则一边改了字节，另一边的测试还是绿的。
 *
 * 测试方式：真实 QUdpSocket + 真实事件循环
 * ----------------------------------------
 * 不用假 socket，也不用直接调私有槽（那会绕开真正的线上路径）。而是：
 *
 *   1. 启动一个"假门口机"，绑在 **127.0.0.2:50000**；
 *   2. 让 MonitorClient 绑它自己的 **Any:50000**，并把 deviceIp 设为 127.0.0.2；
 *   3. 于是 MonClient 发出的 `getframe`/`stop` **只可能**落到假门口机；
 *      假门口机回发的帧**只可能**落到 MonitorClient。
 *
 * 这个"两个不同环回地址同端口"的布局是**实测挑出来的**（探针结果见下）：
 *   - 两个 socket 都绑 `Any:50000` 且都带 ShareAddress 时，Windows 只把数据报
 *     投给其中一个，**归属不确定** —— 直接这么写测试会随机失败；
 *   - 绑到不同的**具体**环回地址（127.0.0.2 vs 任何地址）后，投递按地址具体性
 *     决定，与 bind 顺序无关，实测重复 5 次全部一致。
 *
 * 三个实测结论写在这里，免得以后有人"顺手简化"成不确定的写法：
 *
 *   实测 1：`fake@127.0.0.2:50000` + `MonitorClient@Any:50000`（任意绑定顺序）
 *           → 客户端发的 8 字节 `getframe` 全部由 fake 收到，客户端自己收到 0 个；
 *              fake 发往 127.0.0.1:50000 的 JPEG 全部由 MonitorClient 收到。
 *           重复 5 次结果一致。
 *   实测 2：先由一个**排他**绑定（不带 ShareAddress）占住 `Any:50000`，则
 *           MonitorClient 的 `ShareAddress|ReuseAddressHint` 绑定**失败**
 *           （errorString = "The address is protected"）—— 错误分支可确定性地触发。
 *   实测 3：`QUdpSocket::close()` **立即**释放端口（不需要等 deleteLater 或
 *           事件循环），所以"stop() 之后端口可用"是可以直接断言的。
 *
 * 与基线的对应关系（逐条核对过，行为一致）
 * ----------------------------------------
 * 基线里没有 MonitorClient 这个类，逻辑内联在 desktop/smartserver/widget.cpp：
 *   - L472 `QByteArray requestData = "getframe";` → 本项目 `kGetFrame`
 *   - L485 `QByteArray requestData = "stop";`     → 本项目 `kStop`
 *   - L474/L487 `writeDatagram(requestData, cameraAddr, 50000)` → `toggle()`
 *   - L480 `camActive = true;` / L493 `camActive = false;` → `m_active`
 *   - L369 `pix.loadFromData(datagram, "JPG")`（注意是 "JPG" 不是 "JPEG"）
 *       → `onReadyRead()` 里同样是 `"JPG"`
 * 因此本测试断言的每一个字节都是继承来的，不是新发明的。
 *
 * 一个**故意不测**的地方（如实记录限制）
 * --------------------------------------
 * 基线在接收侧有 `if (!pix.isNull() && camActive)` 这个"非活动态不收帧"的门。
 * 重构后这道门**搬到了 `Widget::onVideoFrameReady()`**（`MonitorClient` 自己
 * 不再判 active）。两者对外可观测的结果相同，所以这里**不**断言 MonitorClient
 * 会因非活动态而丢帧 —— 那会造成一个与实现位置绑定的假断言。
 * 真正该守的是"门还在"，那由 `tools/verify.py` 的静态规则
 * `check_monitor_client_contract_is_pinned` 负责（它同时检查 Widget 里的那道门）。
 */
#include <QBuffer>
#include <QColor>
#include <QElapsedTimer>
#include <QHostAddress>
#include <QImage>
#include <QSignalSpy>
#include <QTest>
#include <QUdpSocket>

#include "core/net/monitor_client.h"
#include "core/net/protocol.h"

using namespace accessterminal;

namespace {

/// 门口机的地址。刻意用 127.0.0.2 而不是 127.0.0.1 —— 见文件头"实测 1"。
const char* kFakeTerminalIp = "127.0.0.2";

/// MonitorClient 发出数据报时，假门口机看到的来源端口应当是 50000
/// （因为 MonitorClient 自己就绑在 50000 上）。
const quint16 kPreviewPort = protocol::kPreviewPort;

/// 等到条件成立，或超时。**等属性，不等固定时长。**
template <typename Predicate>
bool waitFor(Predicate pred, int timeoutMs = 3000)
{
    QElapsedTimer timer;
    timer.start();
    while (timer.elapsed() < timeoutMs) {
        if (pred()) {
            return true;
        }
        QTest::qWait(5);
    }
    return pred();
}

/// 造一帧真实 JPEG（走 Qt 自己的编码器，不手搓字节）。
QByteArray makeJpeg(int w = 64, int h = 48, int hue = 0)
{
    QImage img(w, h, QImage::Format_RGB32);
    img.fill(QColor::fromHsv(hue % 360, 255, 255));
    QByteArray out;
    QBuffer buf(&out);
    buf.open(QIODevice::WriteOnly);
    img.save(&buf, "JPEG", 80);
    buf.close();
    return out;
}

/**
 * @brief 假门口机：绑在 127.0.0.2:50000，记录收到的每个请求，并能回发帧。
 *
 * 回发目标是**记录下来的发送者地址**，这与真实门口机 `CameraUdpServer` 的
 * 行为一致（它收到 getframe 后把 `sender`/`senderPort` 记下来，之后按定时器
 * 推给这一对地址），因此顺带把"MonitorClient 发出的数据报来自 50000 端口"
 * 这条线上性质也钉住了。
 */
class FakeTerminal
{
public:
    bool bind()
    {
        m_sock = new QUdpSocket();
        const bool ok = m_sock->bind(QHostAddress(kFakeTerminalIp), kPreviewPort,
                                     QUdpSocket::ShareAddress
                                         | QUdpSocket::ReuseAddressHint);
        m_bound = ok;
        return ok;
    }

    ~FakeTerminal()
    {
        delete m_sock;
        m_sock = nullptr;
    }

    bool isBound() const { return m_bound; }

    /// 把当前挂起的数据报全部收下，返回这一次新收到的条数。
    int pump()
    {
        int got = 0;
        while (m_sock->hasPendingDatagrams()) {
            QByteArray d;
            d.resize(static_cast<int>(m_sock->pendingDatagramSize()));
            QHostAddress from;
            quint16 fromPort = 0;
            const qint64 n = m_sock->readDatagram(d.data(), d.size(),
                                                  &from, &fromPort);
            if (n < 0) {
                continue;
            }
            if (n < d.size()) {
                d.resize(static_cast<int>(n));
            }
            m_received.append(d);
            m_lastSender = from;
            m_lastSenderPort = fromPort;
            ++got;
        }
        return got;
    }

    /// 等到累计收到 `n` 条请求（或超时）；返回是否达到。
    bool waitForCount(int n, int timeoutMs = 3000)
    {
        return waitFor([&]() { pump(); return m_received.size() >= n; }, timeoutMs);
    }

    int count() const { return m_received.size(); }
    QByteArray at(int i) const { return m_received.value(i); }
    void clear() { m_received.clear(); }
    quint16 lastSenderPort() const { return m_lastSenderPort; }

    /// 按真实门口机的做法，回发给"最后那个请求者"。
    qint64 sendFrame(const QByteArray& payload)
    {
        const QHostAddress to = m_lastSender.isNull() ? QHostAddress::LocalHost
                                                      : m_lastSender;
        const quint16 port = m_lastSenderPort ? m_lastSenderPort : kPreviewPort;
        return m_sock->writeDatagram(payload, to, port);
    }

    /// 直接发一帧到 127.0.0.1:50000（不依赖是否收到过请求）。
    qint64 sendToClientPort(const QByteArray& payload)
    {
        return m_sock->writeDatagram(payload, QHostAddress::LocalHost, kPreviewPort);
    }

private:
    QUdpSocket* m_sock = nullptr;
    bool m_bound = false;
    QList<QByteArray> m_received;
    QHostAddress m_lastSender;
    quint16 m_lastSenderPort = 0;
};

/// 探测 `127.0.0.1:50000` 能否被**排他**绑定（不带 ShareAddress）：
/// 绑得上说明当前没有任何 socket 占着该端口；绑不上说明已被占用。
///
/// 为什么探 `127.0.0.1` 而不是 `Any`（Linux 实测修正）
/// --------------------------------------------------
/// 原先这里探的是 `QHostAddress::Any`。它在 Windows 上能用，但在 Linux 上
/// 会被**假门口机对 127.0.0.2 的合法占用**顶成"已占用"，于是所有
/// "在 FakeTerminal 存活期间断言端口空闲"的用例都会失败。实测矩阵：
///
///   场景                                探 Any      探 127.0.0.1
///   真空闲                              free        free
///   仅 fake@127.0.0.2（本测试的常态）    OCCUPIED ✗  free ✓
///   fake@.2 + client@Any                OCCUPIED    OCCUPIED
///   仅 client@Any（无 fake）             OCCUPIED    OCCUPIED
///   排他@Any 持有                        OCCUPIED    OCCUPIED
///
/// 根因是两个平台对 `SO_REUSEADDR` 的语义不同：Windows 允许"通配地址的排他
/// 绑定"与"具体地址的复用绑定"共存；Linux 则把 `0.0.0.0:50000` 与
/// `127.0.0.2:50000` 视为同一端口的冲突绑定而直接拒绝。失败出在**夹具的
/// 探测地址**上，与被测的 MonitorClient 无关。
///
/// 探 127.0.0.1 **保留了全部判别力**：MonitorClient 绑的是 `Any`，只要它还
/// 占着端口，对 127.0.0.1 的排他绑定在两个平台上都会失败。因此
/// "stop()/析构后端口释放"这类断言该抓的退化照样能抓到（可用故障注入
/// "stop() 不关闭 socket" 实测确认）。
bool previewPortIsFree()
{
    QUdpSocket probe;
    const bool ok = probe.bind(QHostAddress::LocalHost, kPreviewPort);
    if (ok) {
        probe.close();
    }
    return ok;
}

/// 这一点在 127.0.0.2 不可用的平台上应整体跳过，而不是假装通过。
bool loopbackAliasAvailable()
{
    QUdpSocket probe;
    return probe.bind(QHostAddress(kFakeTerminalIp), quint16(0));
}

} // namespace

class TestMonitorClient : public QObject
{
    Q_OBJECT

private slots:
    // ------------------------------------------------------------------
    // 协议常量：这是跨仓库契约，必须是这几个字面量
    // ------------------------------------------------------------------
    void protocolPinsPreviewPortAndWireText()
    {
        QCOMPARE(protocol::kPreviewPort, quint16(50000));
        // 与门口机 CameraUdpServer 解析的文本完全一致，且**不带 '\n'**。
        QCOMPARE(protocol::toWire(protocol::Signal::GetFrame),
                 QByteArrayLiteral("getframe"));
        QCOMPARE(protocol::toWire(protocol::Signal::Stop),
                 QByteArrayLiteral("stop"));
        // 明确钉住"没有换行符"这件事：带 '\n' 会让门口机的 exact match 落空。
        QVERIFY(!protocol::toWire(protocol::Signal::GetFrame).contains('\n'));
        QVERIFY(!protocol::toWire(protocol::Signal::Stop).contains('\n'));
        // 也不能是 'stop' 之外的东西（'stop' 是 'stopsend' 的前缀，别搞混）。
        QVERIFY(protocol::toWire(protocol::Signal::Stop) != QByteArrayLiteral("stopsend"));
    }

    // ------------------------------------------------------------------
    // 惰性绑定
    // ------------------------------------------------------------------
    void constructionDoesNotBindPreviewPort()
    {
        QVERIFY(previewPortIsFree()); // 前置：端口本来是空的（正对照）
        {
            MonitorClient client;
            QTest::qWait(50);
            // 构造后仍未占用 —— ensureSocket() 是惰性的，只有 start/toggle 才绑。
            QVERIFY2(previewPortIsFree(),
                     "MonitorClient 构造时不应占用 50000 端口");
        }
    }

    void startBindsPreviewPort()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        QVERIFY(previewPortIsFree());
        MonitorClient client;
        QVERIFY(client.start());
        // 已绑上：此时排他绑定应当失败。这是"确实占了端口"的正证据。
        QVERIFY2(!previewPortIsFree(),
                 "start() 之后 50000 端口应当已被占用");
    }

    void startIsIdempotent()
    {
        MonitorClient client;
        QVERIFY(client.start());
        QVERIFY(client.start());  // 第二次不应因重复绑定而失败
        QVERIFY(previewPortIsFree() == false);
    }

    // ------------------------------------------------------------------
    // 发送侧：字节、端口、次数
    // ------------------------------------------------------------------
    void firstToggleSendsGetframeWithoutNewline()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        FakeTerminal fake;
        QVERIFY(fake.bind());

        MonitorClient client;
        const bool active = client.toggle(QString::fromLatin1(kFakeTerminalIp));
        QVERIFY2(active, "首次 toggle 应进入接收态");
        QVERIFY2(fake.waitForCount(1), "没有收到 getframe");

        QCOMPARE(fake.count(), 1);
        QCOMPARE(fake.at(0), QByteArrayLiteral("getframe"));
        QCOMPARE(fake.at(0).size(), 8);
        QVERIFY2(!fake.at(0).contains('\n'),
                 "UDP 50000 的请求文本必须不带换行 —— 与 TCP 8887 不同");
    }

    void secondToggleSendsStopWithoutNewline()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        FakeTerminal fake;
        QVERIFY(fake.bind());

        MonitorClient client;
        QVERIFY(client.toggle(QString::fromLatin1(kFakeTerminalIp)));
        QVERIFY(fake.waitForCount(1));

        const bool active = client.toggle(QString::fromLatin1(kFakeTerminalIp));
        QVERIFY2(!active, "再次 toggle 应退出接收态");
        QVERIFY2(fake.waitForCount(2), "没有收到 stop");

        QCOMPARE(fake.count(), 2);
        QCOMPARE(fake.at(0), QByteArrayLiteral("getframe"));
        QCOMPARE(fake.at(1), QByteArrayLiteral("stop"));
        QCOMPARE(fake.at(1).size(), 4);
        QVERIFY(!fake.at(1).contains('\n'));
        // 必须是 'stop'，不是 'stopsend'（后者是 TCP 信令，前缀相同，极易混淆）
        QVERIFY(fake.at(1) != QByteArrayLiteral("stopsend"));
    }

    void exactlyOneDatagramPerToggle()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        FakeTerminal fake;
        QVERIFY(fake.bind());

        MonitorClient client;
        for (int i = 0; i < 3; ++i) {
            client.toggle(QString::fromLatin1(kFakeTerminalIp));
            QVERIFY(fake.waitForCount(i + 1));
            QTest::qWait(80);  // 给"多余的重发"充分机会出现
            fake.pump();
            QVERIFY2(fake.count() == i + 1,
                     qPrintable(QStringLiteral("第 %1 次 toggle 后累计应当只有 %1 条，实际 %2 条")
                                    .arg(i + 1).arg(fake.count())));
        }
        QCOMPARE(fake.count(), 3);
    }

    void requestComesFromPreviewPort()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        FakeTerminal fake;
        QVERIFY(fake.bind());

        MonitorClient client;
        client.toggle(QString::fromLatin1(kFakeTerminalIp));
        QVERIFY(fake.waitForCount(1));

        // 真实门口机把帧按 senderAddr/senderPort 推回来，所以客户端必须
        // 从 50000 端口发出去，门口机才能推得回来。
        QCOMPARE(fake.lastSenderPort(), kPreviewPort);
    }

    void toggleDoesNotRebindExistingSocket()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        FakeTerminal fake;
        QVERIFY(fake.bind());

        MonitorClient client;
        QSignalSpy errSpy(&client, &MonitorClient::errorOccurred);
        client.toggle(QString::fromLatin1(kFakeTerminalIp));
        client.toggle(QString::fromLatin1(kFakeTerminalIp));
        client.toggle(QString::fromLatin1(kFakeTerminalIp));
        QVERIFY(fake.waitForCount(3));
        // 复用已有 socket，不应因"重复绑定"产生任何错误。
        QCOMPARE(errSpy.count(), 0);
    }

    void toggleReturnValueMatchesActiveState()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        FakeTerminal fake;
        QVERIFY(fake.bind());

        MonitorClient client;
        QVERIFY(!client.isActive());          // 初态
        QVERIFY(client.toggle(QString::fromLatin1(kFakeTerminalIp)));
        QVERIFY(client.isActive());           // 返回值 == 调用后的状态
        QVERIFY(!client.toggle(QString::fromLatin1(kFakeTerminalIp)));
        QVERIFY(!client.isActive());
        QVERIFY(client.toggle(QString::fromLatin1(kFakeTerminalIp)));
        QVERIFY(client.isActive());
    }

    void activeChangedFollowsEveryToggle()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        FakeTerminal fake;
        QVERIFY(fake.bind());

        MonitorClient client;
        QSignalSpy spy(&client, &MonitorClient::activeChanged);

        client.toggle(QString::fromLatin1(kFakeTerminalIp));
        QCOMPARE(spy.count(), 1);
        QCOMPARE(spy.at(0).at(0).toBool(), true);

        client.toggle(QString::fromLatin1(kFakeTerminalIp));
        QCOMPARE(spy.count(), 2);
        QCOMPARE(spy.at(1).at(0).toBool(), false);

        client.toggle(QString::fromLatin1(kFakeTerminalIp));
        QCOMPARE(spy.count(), 3);
        QCOMPARE(spy.at(2).at(0).toBool(), true);
    }

    // 发送失败不改状态 —— 这是**继承自基线**的行为（基线也忽略 writeDatagram
    // 的返回值，无条件置 camActive）。如实钉住，免得以后被"顺手修正"成静默
    // 不同的语义；要改必须当成一个有意识的决定。
    void sendFailureStillFlipsActiveStateAsBaselineDid()
    {
        MonitorClient client;
        QSignalSpy spy(&client, &MonitorClient::activeChanged);
        // 空地址不是合法的单播目标。
        const bool active = client.toggle(QString());
        QCOMPARE(active, true);
        QVERIFY(client.isActive());
        QCOMPARE(spy.count(), 1);
        // 注意：这里只断言"状态翻转了"，不断言门口机会收到东西。
    }

    // ------------------------------------------------------------------
    // 接收侧：什么算一帧
    // ------------------------------------------------------------------
    void receivedJpegEmitsFrameReceived()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        FakeTerminal fake;
        QVERIFY(fake.bind());

        MonitorClient client;
        QSignalSpy spy(&client, &MonitorClient::frameReceived);
        QVERIFY(client.toggle(QString::fromLatin1(kFakeTerminalIp)));
        QVERIFY(fake.waitForCount(1));   // 先让门口机知道往哪儿回发

        QVERIFY(fake.sendFrame(makeJpeg(64, 48)) > 0);
        QVERIFY2(waitFor([&]() { return spy.count() >= 1; }),
                 "发来的完整 JPEG 应当产生 frameReceived");
        QCOMPARE(spy.count(), 1);

        const QPixmap got = spy.at(0).at(0).value<QPixmap>();
        QVERIFY(!got.isNull());
        QCOMPARE(got.width(), 64);
        QCOMPARE(got.height(), 48);
    }

    void frameReceivedCarriesTheFrameSize()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        FakeTerminal fake;
        QVERIFY(fake.bind());

        MonitorClient client;
        QSignalSpy spy(&client, &MonitorClient::frameReceived);
        client.toggle(QString::fromLatin1(kFakeTerminalIp));
        QVERIFY(fake.waitForCount(1));

        QVERIFY(fake.sendFrame(makeJpeg(120, 90)) > 0);
        QVERIFY(waitFor([&]() { return spy.count() >= 1; }));
        const QPixmap got = spy.at(0).at(0).value<QPixmap>();
        QCOMPARE(got.width(), 120);
        QCOMPARE(got.height(), 90);
    }

    // 负向断言必须配正对照：先证明同一套管路**确实能**送达一帧，
    // 再证明垃圾数据不会。否则"没收到帧"可能只是管路本身坏了。
    void garbageDatagramEmitsNoFrameAndGoodOneStillDoes()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        FakeTerminal fake;
        QVERIFY(fake.bind());

        MonitorClient client;
        QSignalSpy spy(&client, &MonitorClient::frameReceived);
        client.toggle(QString::fromLatin1(kFakeTerminalIp));
        QVERIFY(fake.waitForCount(1));

        // (1) 正对照：好帧必须先能送达 —— 证明管路是通的。
        QVERIFY(fake.sendFrame(makeJpeg(64, 48)) > 0);
        QVERIFY2(waitFor([&]() { return spy.count() >= 1; }),
                 "正对照失败：好帧都没送达，后面的负向断言会变成假绿");
        QCOMPARE(spy.count(), 1);

        // (2) 负向：垃圾数据不得产生 frameReceived，也不得崩。
        QVERIFY(fake.sendToClientPort(QByteArrayLiteral("not a jpeg at all")) > 0);
        QTest::qWait(250);
        QCOMPARE(spy.count(), 1);

        // (3) 再送一帧好帧：必须仍然能收到（没被垃圾数据搞坏状态）。
        QVERIFY(fake.sendFrame(makeJpeg(80, 60)) > 0);
        QVERIFY2(waitFor([&]() { return spy.count() >= 2; }),
                 "垃圾数据之后的正常帧也应当送达");
        QCOMPARE(spy.count(), 2);
    }

    void emptyDatagramEmitsNoFrame()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        FakeTerminal fake;
        QVERIFY(fake.bind());

        MonitorClient client;
        QSignalSpy spy(&client, &MonitorClient::frameReceived);
        client.toggle(QString::fromLatin1(kFakeTerminalIp));
        QVERIFY(fake.waitForCount(1));

        // 先打一次正对照（空数据报在某些平台上可能根本不会被投递，
        // 那样下面的 QCOMPARE 就是空的 —— 所以要先证明管路通）。
        QVERIFY(fake.sendFrame(makeJpeg(64, 48)) > 0);
        QVERIFY(waitFor([&]() { return spy.count() >= 1; }));

        fake.sendToClientPort(QByteArray());
        QTest::qWait(200);
        QCOMPARE(spy.count(), 1);
    }

    /**
     * 一次突发里的多帧必须**一帧不丢**。
     *
     * 这条用例守的是什么、不守什么（实测边界，别高估它）
     * --------------------------------------------------
     * 它守的是"不会丢帧"这个**结果**。
     *
     * 它**不**守 `onReadyRead()` 里的 `while` 循环 —— 这一点是被故障注入
     * 反过来教育的：把 `while` 改成 `if`（一次只读一个数据报）之后，
     * 本用例**依然通过**。探针实测（result8.txt）说明了原因：
     * Qt 在数据报仍有剩余时会**再次**发出 `readyRead`，所以两种写法
     * 最终都把帧送完，只是回调次数不同：
     *
     *     连发 50 个：while 版读到 50、readyRead 触发 **1** 次
     *                 if    版读到 50、readyRead 触发 **50** 次
     *
     * 也就是说"帧全到了"这件事对 `while`/`if` **没有判别力**。
     * 与其留一条看起来守着 while、其实守不住的断言（那比没有更糟，
     * 因为它会让人以为这块已经被守住了），不如把边界写清楚：
     * `while` 的存在由 tools/verify.py 的静态规则
     * `check_monitor_client_contract_is_pinned` 直接检查源码文本来保证。
     */
    void multipleDatagramsInOneBurstAreAllDelivered()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        FakeTerminal fake;
        QVERIFY(fake.bind());

        MonitorClient client;
        QSignalSpy spy(&client, &MonitorClient::frameReceived);
        client.toggle(QString::fromLatin1(kFakeTerminalIp));
        QVERIFY(fake.waitForCount(1));

        // 门口机 50ms 推一帧，一次 readyRead 里可能有多帧 —— 不能丢。
        QVERIFY(fake.sendFrame(makeJpeg(32, 32, 0)) > 0);
        QVERIFY(fake.sendFrame(makeJpeg(32, 32, 120)) > 0);
        QVERIFY(fake.sendFrame(makeJpeg(32, 32, 240)) > 0);
        QVERIFY2(waitFor([&]() { return spy.count() >= 3; }),
                 "一次突发里的多帧不应当丢失");
        QCOMPARE(spy.count(), 3);
    }

    // ------------------------------------------------------------------
    // stop() / 析构：释放与幂等
    // ------------------------------------------------------------------
    void stopReleasesPreviewPort()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        MonitorClient client;
        QVERIFY(client.start());
        QVERIFY2(!previewPortIsFree(), "start() 后端口应被占用");
        client.stop();
        // 实测：close() 立即释放端口，无需等 deleteLater 或事件循环。
        QVERIFY2(previewPortIsFree(), "stop() 应当释放 50000 端口");
    }

    void stopWhenActiveEmitsOnceAndIsIdempotent()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        FakeTerminal fake;
        QVERIFY(fake.bind());

        MonitorClient client;
        QSignalSpy spy(&client, &MonitorClient::activeChanged);
        client.toggle(QString::fromLatin1(kFakeTerminalIp));
        QCOMPARE(spy.count(), 1);

        client.stop();
        QCOMPARE(spy.count(), 2);                    // 由 true 变 false，发一次
        QCOMPARE(spy.at(1).at(0).toBool(), false);
        QVERIFY(!client.isActive());

        client.stop();                               // 再停一次
        QCOMPARE(spy.count(), 2);                    // 已经是 false，不再发
        QVERIFY(!client.isActive());
        QVERIFY(previewPortIsFree());
    }

    void stopWhenInactiveEmitsNothing()
    {
        MonitorClient client;
        QSignalSpy spy(&client, &MonitorClient::activeChanged);
        client.stop();
        QCOMPARE(spy.count(), 0);
        QVERIFY(!client.isActive());
    }

    void stopWithoutPriorBindIsSafe()
    {
        MonitorClient client;
        QSignalSpy errSpy(&client, &MonitorClient::errorOccurred);
        client.stop();   // 从未绑定过
        client.stop();
        QCOMPARE(errSpy.count(), 0);
        QVERIFY(!client.isActive());
    }

    void destructorReleasesPreviewPort()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        QVERIFY(previewPortIsFree());
        {
            MonitorClient client;
            QVERIFY(client.toggle(QString::fromLatin1(kFakeTerminalIp)));
            QVERIFY(!previewPortIsFree());
        }
        QVERIFY2(previewPortIsFree(), "析构应当释放 50000 端口");
    }

    /**
     * 析构一个**处于接收态**的客户端时，必须再报一次 activeChanged(false)。
     *
     * 为什么这条断言必要（实测的教训）
     * --------------------------------
     * "析构不调用 stop()" 这个变异**端口照样会被释放** —— 因为 socket 是用
     * `new QUdpSocket(this)` 建的，是 MonitorClient 的子对象，QObject 的析构
     * 会连带销毁它。所以单看"端口有没有释放"，两种实现完全一样，
     * `destructorReleasesPreviewPort` **抓不到**这个变异（故障注入实测 rc=0）。
     *
     * 两条路径**唯一**可观测的差别，就是 `stop()` 里那句
     * `emit activeChanged(false)`：它会在对象消亡之前通知监听者"已经停了"。
     * 因此这里必须直接断言这个信号，否则"析构里的 stop()"就是一个
     * 看起来被覆盖、实际无人看守的调用。
     */
    void destructorOfActiveClientNotifiesActiveChanged()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        FakeTerminal fake;
        QVERIFY(fake.bind());

        int observed = 0;
        bool lastValue = false;

        QVERIFY(previewPortIsFree());
        {
            MonitorClient client;
            connect(&client, &MonitorClient::activeChanged, this,
                    [&observed, &lastValue](bool active) {
                        ++observed;
                        lastValue = active;
                    });
            QVERIFY(client.toggle(QString::fromLatin1(kFakeTerminalIp)));
            // 进入接收态那一次。
            QCOMPARE(observed, 1);
            QCOMPARE(lastValue, true);
            QVERIFY(!previewPortIsFree());
        }
        // 析构时 stop() 应当再发一次 false（这就是与"析构不调用 stop()"的区别）。
        QVERIFY2(observed == 2,
                 qPrintable(QStringLiteral("析构时应再发一次 activeChanged，"
                                           "实际只发了 %1 次").arg(observed)));
        QCOMPARE(lastValue, false);
        QVERIFY(previewPortIsFree());
    }

    void portIsReusableAfterFullCycle()
    {
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        for (int i = 0; i < 3; ++i) {
            MonitorClient client;
            QVERIFY2(client.start(), "反复 start 应当每次都成功");
            QVERIFY(!previewPortIsFree());
        }
        QVERIFY(previewPortIsFree());
    }

    // ------------------------------------------------------------------
    // 绑定失败：错误分支
    // ------------------------------------------------------------------
    void bindFailureEmitsErrorOccurredAndReturnsFalse()
    {
        // 实测：先由一个排他绑定占住端口，MonitorClient 的
        // ShareAddress|ReuseAddressHint 就会失败（"The address is protected"）。
        QUdpSocket exclusive;
        QVERIFY2(exclusive.bind(QHostAddress::Any, kPreviewPort),
                 "前置条件失败：无法排他占用 50000");
        QVERIFY2(!previewPortIsFree(), "前置条件失败：端口应已被占用");

        MonitorClient client;
        QSignalSpy errSpy(&client, &MonitorClient::errorOccurred);
        QSignalSpy activeSpy(&client, &MonitorClient::activeChanged);

        const bool active = client.toggle(QString::fromLatin1(kFakeTerminalIp));
        QVERIFY2(!active, "绑定失败时 toggle 必须返回 false");
        QVERIFY2(!client.isActive(), "绑定失败时不应进入接收态");
        QCOMPARE(errSpy.count(), 1);
        QVERIFY2(!activeSpy.count() || activeSpy.at(0).at(0).toBool() == false,
                 "绑定失败时不能报出 active=true");

        // 错误消息应当指出端口，便于现场定位；但不绑定具体措辞。
        const QString msg = errSpy.at(0).at(0).toString();
        QVERIFY2(msg.contains(QString::number(kPreviewPort)),
                 qPrintable(QStringLiteral("错误消息未提及端口 %1: %2")
                                .arg(kPreviewPort).arg(msg)));

        client.stop();  // 失败后 stop 也不应崩
    }

    void startReturnsFalseWhenBindFails()
    {
        QUdpSocket exclusive;
        QVERIFY(exclusive.bind(QHostAddress::Any, kPreviewPort));

        MonitorClient client;
        QSignalSpy errSpy(&client, &MonitorClient::errorOccurred);
        QVERIFY2(!client.start(), "绑定失败时 start() 必须返回 false");
        QCOMPARE(errSpy.count(), 1);
    }

    void bindFailureIsRecoverable()
    {
        {
            // 先制造一次失败……
            QUdpSocket exclusive;
            QVERIFY(exclusive.bind(QHostAddress::Any, kPreviewPort));
            MonitorClient client;
            QVERIFY(!client.toggle(QString::fromLatin1(kFakeTerminalIp)));
            QVERIFY(!client.isActive());
            // ……排他 socket 离开作用域，端口释放。
        }
        QVERIFY2(previewPortIsFree(), "前置条件失败：端口应已释放");

        // 同一个进程里，新的 MonitorClient 应当能正常绑定。
        MonitorClient client2;
        QVERIFY2(client2.start(), "端口释放后应能重新绑定");
        QVERIFY(client2.isActive() == false);
    }

    void failedBindDoesNotLeakPort()
    {
        {
            QUdpSocket exclusive;
            QVERIFY(exclusive.bind(QHostAddress::Any, kPreviewPort));
            MonitorClient client;
            client.start();   // 失败
            client.stop();
            // 失败路径上 ensureSocket() 自己 delete 了 socket 并置空，
            // 因此这里不应留下任何占用。
        }
        QVERIFY2(previewPortIsFree(), "失败的绑定不应留下端口占用");
    }

    // ------------------------------------------------------------------
    // 生产接线：门口机的地址来自配置
    // ------------------------------------------------------------------
    void productionWiringIsPinned()
    {
        // MonitorClient 的目标地址由调用方传入（生产代码里是
        // AppConfig::instance().deviceIp()），它自己**不读配置**。
        // 这里钉住"确实用传入的地址"，避免以后被改成硬编码。
        if (!loopbackAliasAvailable()) {
            QSKIP("本平台不支持 127.0.0.2 环回别名");
        }
        FakeTerminal fake;
        QVERIFY(fake.bind());

        MonitorClient client;
        client.toggle(QString::fromLatin1(kFakeTerminalIp));
        QVERIFY(fake.waitForCount(1));
        QCOMPARE(fake.at(0), QByteArrayLiteral("getframe"));

        // 换一个别的地址：那一边收得到，原来这一边收不到。
        QUdpSocket otherSock;
        const bool ok = otherSock.bind(QHostAddress("127.0.0.3"), kPreviewPort,
                                       QUdpSocket::ShareAddress
                                           | QUdpSocket::ReuseAddressHint);
        if (!ok) {
            QSKIP("本平台不支持 127.0.0.3 环回别名");
        }
        fake.clear();
        client.toggle(QStringLiteral("127.0.0.3"));
        QTest::qWait(200);
        fake.pump();
        QVERIFY2(fake.count() == 0,
                 qPrintable(QStringLiteral("发给 127.0.0.3 的请求不应落到 127.0.0.2 上，实际收到 %1 条")
                                .arg(fake.count())));
    }
};

QTEST_MAIN(TestMonitorClient)
#include "test_monitor_client.moc"
