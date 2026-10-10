/**
 * @file test_signaling_server.cpp
 * @brief SignalingServer（室内机 TCP 8887 信令服务端）行为断言。
 *
 * 为什么必须写这个测试
 * --------------------
 * TCP 8887 是本项目**第一条协议硬约束**，但室内机侧的 `SignalingServer`
 * （接收门口机的 `call`/`stopsend`/`unlock`，并回 `accept`/`recstop`/`unlock`）
 * 此前**没有任何单元测试** —— 只有 `t113/test_protocol.cpp` 覆盖了协议编解码，
 * 以及 T113 侧的 `SignalingClient` 有互操作测试。服务端自己的行为
 * （接入/断开、按连接分流的解码器、回执、广播、停止）全无覆盖。
 *
 * 测试方式
 * --------
 * 用**真实 QTcpSocket** 连到 `127.0.0.1` 上的真实 `QTcpServer`，走完整事件
 * 循环。这样 bind、`newConnection`、`readyRead` 派发、`disconnected` 清理
 * 全都一起被验证，而不是直接调私有槽（那会绕开真正的线上路径）。
 *
 * 端口：刻意**不用** 8887，而是取一个高位随机端口，避免与真实服务或并行
 * 测试用例冲突；端口号本身由 `protocol.h` 的常量单独断言。
 */
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QHostAddress>
#include <QSignalSpy>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTest>

#include "core/net/protocol.h"
#include "core/net/signaling_server.h"

using namespace accessterminal;

// QSignalSpy 需要把自定义枚举放进 QVariant，因此必须声明元类型。
// 生产代码里由 widget.h 声明（T113 侧），测试中单独声明以免引入 UI 依赖 ——
// 与 tests/interop/test_interop.cpp 的做法一致。
// 注意：不能改 protocol.h 去加这一行，它是冻结文件（跨仓库 SHA256 必须一致）。
Q_DECLARE_METATYPE(accessterminal::protocol::Signal)

namespace {

/// 等到条件成立，或超时。
template <typename Predicate>
bool waitFor(Predicate pred, int timeoutMs = 3000)
{
    QElapsedTimer timer;
    timer.start();
    while (timer.elapsed() < timeoutMs) {
        if (pred()) {
            return true;
        }
        QTest::qWait(10);
    }
    return pred();
}

/// 从真实 socket 读，直到攒够 len 字节或超时。
QByteArray readExactly(QTcpSocket& sock, int len, int timeoutMs = 3000)
{
    QByteArray got;
    QElapsedTimer timer;
    timer.start();
    while (got.size() < len && timer.elapsed() < timeoutMs) {
        if (sock.waitForReadyRead(50)) {
            got += sock.readAll();
        }
    }
    return got;
}

/**
 * @brief 取一个本次进程内单调递增的高位端口。
 *
 * 刻意**不用** 8887：那是真实服务的端口，测试占用会与之冲突，也会让并行
 * 用例互相踩。端口号本身由 protocolConstantsAreFrozen 单独断言。
 *
 * 不用 QRandomGenerator：它是 Qt 5.10 才有的，而本项目要能在 Tina SDK 的
 * Qt 5.9 上交叉编译，测试代码同样不引入高于 Qt 5.9 的 API。
 */
quint16 pickPort()
{
    static quint16 next = 21000;
    return next++;
}

} // namespace

class TestSignalingServer : public QObject
{
    Q_OBJECT

private slots:

    /**
     * 注册元类型。
     *
     * `Q_DECLARE_METATYPE` 只让 `QVariant::value<Signal>()` 能编译；跨越
     * 队列连接传递自定义类型还需要运行时注册，否则 QSignalSpy 在排队投递时
     * 会打印 "Cannot queue arguments of type" 并**丢掉参数**，spy 里的值
     * 变成默认构造的 Unknown —— 那会让所有断言看起来"恰好不匹配"，
     * 却完全不是被测代码的问题。T113 的互操作测试踩过同样的坑。
     */
    void initTestCase()
    {
        qRegisterMetaType<accessterminal::protocol::Signal>(
            "accessterminal::protocol::Signal");
        qRegisterMetaType<QTcpSocket*>("QTcpSocket*");
    }

    // -----------------------------------------------------------------------
    // 监听
    // -----------------------------------------------------------------------

    /// listen() 成功后 isListening() 为真，且**重复 listen 幂等**。
    void listenIsIdempotent()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QVERIFY(server.isListening());
        // 再次 listen 应直接返回 true（不重新绑定、不报错）。
        QVERIFY(server.listen(port));
        QVERIFY(server.isListening());
        server.stop();
    }

    /// 端口被占用时 listen() 必须返回 false 并发出 errorOccurred。
    void listenOnBusyPortFailsAndEmits()
    {
        QTcpServer blocker;
        const quint16 port = pickPort();
        QVERIFY(blocker.listen(QHostAddress::Any, port));

        SignalingServer server;
        QSignalSpy spy(&server, &SignalingServer::errorOccurred);
        QVERIFY2(!server.listen(port), "端口已被占用，listen 必须失败");
        QVERIFY(!server.isListening());
        QVERIFY(spy.count() >= 1);
        server.stop();
    }

    /// stop() 后必须不再监听。
    void stopClosesListener()
    {
        SignalingServer server;
        QVERIFY(server.listen(pickPort()));
        server.stop();
        QVERIFY(!server.isListening());
    }

    // -----------------------------------------------------------------------
    // 接入 / 断开
    // -----------------------------------------------------------------------

    /// 门口机连上后必须发出 clientConnected。
    void clientConnectEmitsSignal()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy spy(&server, &SignalingServer::clientConnected);

        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(client.waitForConnected(3000));

        QVERIFY(waitFor([&spy]() { return spy.count() >= 1; }));
        server.stop();
    }

    /// 断开后必须发出 clientDisconnected（且不早于接入）。
    void clientDisconnectEmitsSignal()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy connected(&server, &SignalingServer::clientConnected);
        QSignalSpy disconnected(&server, &SignalingServer::clientDisconnected);

        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(client.waitForConnected(3000));
        QVERIFY(waitFor([&connected]() { return connected.count() >= 1; }));

        client.disconnectFromHost();
        QVERIFY(waitFor([&disconnected]() { return disconnected.count() >= 1; }));
        server.stop();
    }

    // -----------------------------------------------------------------------
    // 线上字节（本文件的核心）
    // -----------------------------------------------------------------------

    /**
     * 门口机发来的每条信令必须**逐字节**还原成正确的枚举。
     *
     * 这是协议硬约束的核心断言：`call`（呼叫）、`unlock`（开锁）、
     * `stopsend`（对端停止发送）。一律带 '\n' 结尾——这是线上实际形态。
     */
    void receivesExactWireBytes()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy spy(&server, &SignalingServer::signalReceived);

        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(client.waitForConnected(3000));

        struct Case { const char* wire; protocol::Signal expect; };
        const Case cases[] = {
            {"call\n",     protocol::Signal::Call},
            {"unlock\n",   protocol::Signal::Unlock},
            {"stopsend\n", protocol::Signal::StopSend},
        };
        for (const Case& c : cases) {
            const int before = spy.count();
            const QByteArray wire(c.wire);
            client.write(wire);
            client.flush();
            QVERIFY2(waitFor([&spy, before]() { return spy.count() > before; }),
                     c.wire);
            QCOMPARE(spy.last().at(0).value<protocol::Signal>(), c.expect);
        }
        server.stop();
    }

    /**
     * 一次 write 里含**多条**信令时必须全部解出（TCP 是字节流，会粘包）。
     *
     * 这是 `StreamDecoder` 存在的理由：旧实现只取第一条，其余永久丢失。
     */
    void multipleSignalsInOneWriteAreAllDecoded()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy spy(&server, &SignalingServer::signalReceived);

        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(client.waitForConnected(3000));

        client.write(QByteArrayLiteral("call\nunlock\nstopsend\n"));
        client.flush();

        QVERIFY(waitFor([&spy]() { return spy.count() >= 3; }));
        QCOMPARE(spy.at(0).at(0).value<protocol::Signal>(), protocol::Signal::Call);
        QCOMPARE(spy.at(1).at(0).value<protocol::Signal>(), protocol::Signal::Unlock);
        QCOMPARE(spy.at(2).at(0).value<protocol::Signal>(), protocol::Signal::StopSend);
        server.stop();
    }

    /**
     * 信令被 TCP **拆成两个包**时仍必须正确拼出（半包不得丢）。
     *
     * 流程：先发 "cal"，等一会（确保服务端已处理完这个半包），再发 "l\n"。
     * 若实现把半包丢掉，第二条就只会看到 "l\n"（无法识别）→ 断言失败。
     */
    void splitSignalIsReassembled()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy spy(&server, &SignalingServer::signalReceived);

        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(client.waitForConnected(3000));

        client.write(QByteArrayLiteral("cal"));
        client.flush();
        QTest::qWait(150); // 让服务端确实处理了这个半包

        client.write(QByteArrayLiteral("l\n"));
        client.flush();

        QVERIFY2(waitFor([&spy]() { return spy.count() >= 1; }),
                 "被 TCP 拆开的 call 必须仍能拼出");
        QCOMPARE(spy.last().at(0).value<protocol::Signal>(), protocol::Signal::Call);
        server.stop();
    }

    /**
     * `"stopsend"` 被拆成 `"stop"` + `"send\n"` 时**不得**被误判为 `stop`。
     *
     * 这是协议里最阴险的一处歧义：`"stop"` 是 `"stopsend"` 的严格前缀。
     * `protocol::isAmbiguousPrefix()` 就是为此存在的——它让解码器把
     * `"stop"` 缓冲住而不是立刻解码，等后续字节到了再做决定。
     * 若没有这个机制，远程监看的 `stop` 与挂断的 `stopsend` 会混淆。
     */
    void stopsendSplitAtAmbiguousPrefixIsNotMisdecoded()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy spy(&server, &SignalingServer::signalReceived);

        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(client.waitForConnected(3000));

        client.write(QByteArrayLiteral("stop"));
        client.flush();
        QTest::qWait(200); // 关键：此时绝不能已经解出 Signal::Stop

        QCOMPARE(spy.count(), 0); // 歧义前缀必须被缓冲

        client.write(QByteArrayLiteral("send\n"));
        client.flush();

        QVERIFY(waitFor([&spy]() { return spy.count() >= 1; }));
        QCOMPARE(spy.last().at(0).value<protocol::Signal>(),
                 protocol::Signal::StopSend);
        server.stop();
    }

    /**
     * 裸 `"stop\n"`（远程监看停止）必须解码为 `Signal::Stop`，
     * 不能在等 `stopsend` 的后续字节上卡住。
     */
    void bareStopIsDecodedAsStop()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy spy(&server, &SignalingServer::signalReceived);

        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(client.waitForConnected(3000));

        // 发完整的 "stop\n"：解码器看到终止符就能定论，无需再等。
        client.write(QByteArrayLiteral("stop\n"));
        client.flush();

        QVERIFY(waitFor([&spy]() { return spy.count() >= 1; }));
        QCOMPARE(spy.last().at(0).value<protocol::Signal>(), protocol::Signal::Stop);
        server.stop();
    }

    /**
     * 历史遗留的裸 `"recstop"`（**不带 '\n'**）必须仍能被识别。
     *
     * 这是 baseline 的宽容语义，也是本项目里悬而未决的一个点：室内机发出的
     * `recstop` 没有换行符（见 baseline widget.cpp 的 hangupClicked）。
     * `StreamDecoder` 的尾段匹配分支正是为它保留的，不能被"清理"掉。
     */
    void legacyRecstopWithoutNewlineIsAccepted()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy spy(&server, &SignalingServer::signalReceived);

        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(client.waitForConnected(3000));

        client.write(QByteArrayLiteral("recstop")); // 刻意不带 '\n'
        client.flush();

        // 这一条需要等待：解码器可能要到下一次喂入才吐出尾段。
        // 用再发一个无关字节的方式触发重新解析，模拟"随后断开"前的最后数据。
        QVERIFY2(waitFor([&spy]() { return spy.count() >= 1; }, 2000),
                 "裸 recstop（无换行）必须仍被识别，这是 baseline 的宽容语义");
        QCOMPARE(spy.last().at(0).value<protocol::Signal>(),
                 protocol::Signal::RecStop);
        server.stop();
    }

    /// 无法识别的文本必须被忽略，不得发出任何 signalReceived。
    void unknownTextIsIgnored()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy spy(&server, &SignalingServer::signalReceived);

        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(client.waitForConnected(3000));

        client.write(QByteArrayLiteral("garbage\n"));
        client.flush();
        QTest::qWait(300);
        QCOMPARE(spy.count(), 0);

        // 之后仍能正常识别。
        client.write(QByteArrayLiteral("call\n"));
        client.flush();
        QVERIFY(waitFor([&spy]() { return spy.count() >= 1; }));
        server.stop();
    }

    /// 空行必须被安全忽略。
    void emptyLineIsIgnored()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy spy(&server, &SignalingServer::signalReceived);

        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(client.waitForConnected(3000));
        client.write(QByteArrayLiteral("\n\n\n"));
        client.flush();
        QTest::qWait(300);
        QCOMPARE(spy.count(), 0);
        server.stop();
    }

    /// 带前导/尾随空白的信令必须被 trim 后识别（`fromWire` 的既有语义）。
    void whitespaceIsTrimmed()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy spy(&server, &SignalingServer::signalReceived);

        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(client.waitForConnected(3000));
        client.write(QByteArrayLiteral("  call  \n"));
        client.flush();
        QVERIFY(waitFor([&spy]() { return spy.count() >= 1; }));
        QCOMPARE(spy.last().at(0).value<protocol::Signal>(), protocol::Signal::Call);
        server.stop();
    }

    // -----------------------------------------------------------------------
    // 回执与广播（线上字节逐字节）
    // -----------------------------------------------------------------------

    /// `reply()` 必须原样发出 `accept\n` / `recstop\n` / `unlock\n`。
    void replyWritesExactWireBytes()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));

        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(client.waitForConnected(3000));

        // 先让服务端认识这个连接：发一条信令并等 signalReceived 拿到 client 指针。
        QSignalSpy spy(&server, &SignalingServer::signalReceived);
        client.write(QByteArrayLiteral("call\n"));
        client.flush();
        QVERIFY(waitFor([&spy]() { return spy.count() >= 1; }));
        QTcpSocket* srvSide = spy.last().at(1).value<QTcpSocket*>();
        QVERIFY(srvSide != nullptr);

        struct Case { protocol::Signal sig; const char* wire; };
        const Case cases[] = {
            {protocol::Signal::Accept,  "accept\n"},
            {protocol::Signal::RecStop, "recstop\n"},
            {protocol::Signal::Unlock,  "unlock\n"},
        };
        for (const Case& c : cases) {
            QVERIFY(server.reply(srvSide, c.sig));
            const QByteArray got = readExactly(client, static_cast<int>(qstrlen(c.wire)));
            QCOMPARE(got, QByteArray(c.wire));
        }
        server.stop();
    }

    /// `reply()` 对空指针与未连接 socket 必须返回 false，不得崩溃。
    void replyRejectsInvalidSocket()
    {
        SignalingServer server;
        QVERIFY(server.listen(pickPort()));
        QVERIFY2(!server.reply(nullptr, protocol::Signal::Accept),
                 "空指针必须被拒绝");

        QTcpSocket orphan; // 未连接
        QVERIFY2(!server.reply(&orphan, protocol::Signal::Accept),
                 "未连接的 socket 必须被拒绝");
        server.stop();
    }

    /// `reply()` 必须拒绝未知信令（不能发出空帧或半个帧）。
    void replyRejectsUnknownSignal()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy spy(&server, &SignalingServer::signalReceived);

        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(client.waitForConnected(3000));
        client.write(QByteArrayLiteral("call\n"));
        client.flush();
        QVERIFY(waitFor([&spy]() { return spy.count() >= 1; }));
        QTcpSocket* srvSide = spy.last().at(1).value<QTcpSocket*>();
        QVERIFY(srvSide);

        QVERIFY2(!server.reply(srvSide, protocol::Signal::Unknown),
                 "未知信令必须被拒绝");
        server.stop();
    }

    /// `broadcast()` 必须向所有已连接客户端发同一串字节，并返回条数。
    void broadcastReachesAllClients()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy conn(&server, &SignalingServer::clientConnected);

        QTcpSocket a, b;
        a.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(a.waitForConnected(3000));
        b.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(b.waitForConnected(3000));
        QVERIFY(waitFor([&conn]() { return conn.count() >= 2; }));

        QCOMPARE(server.broadcast(protocol::Signal::Unlock), 2);
        QCOMPARE(readExactly(a, 7), QByteArrayLiteral("unlock\n"));
        QCOMPARE(readExactly(b, 7), QByteArrayLiteral("unlock\n"));
        server.stop();
    }

    /// `broadcast()` 对未知信令必须返回 0，且不发任何字节。
    void broadcastRejectsUnknownSignal()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy conn(&server, &SignalingServer::clientConnected);

        QTcpSocket a;
        a.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(a.waitForConnected(3000));
        QVERIFY(waitFor([&conn]() { return conn.count() >= 1; }));

        QCOMPARE(server.broadcast(protocol::Signal::Unknown), 0);
        QTest::qWait(200);
        QCOMPARE(a.bytesAvailable(), static_cast<qint64>(0));
        server.stop();
    }

    /// 无客户端时 broadcast() 返回 0（不得崩溃）。
    void broadcastWithNoClientsReturnsZero()
    {
        SignalingServer server;
        QVERIFY(server.listen(pickPort()));
        QCOMPARE(server.broadcast(protocol::Signal::Unlock), 0);
        server.stop();
    }

    // -----------------------------------------------------------------------
    // 按连接分流
    // -----------------------------------------------------------------------

    /**
     * 两条连接各自的**半包不得串味**：解码器必须按 socket 分别持有。
     *
     * 若所有连接共用一个解码器，A 的 "cal" 与 B 的 "l\n" 会拼成一条 call，
     * 而两条连接各自都拿不到结果 —— 现场表现为"随机有一条呼叫收不到"。
     *
     * 关键断言是 `QCOMPARE(spy.count(), 0)` 这一步（在 A 补上自己的后半
     * **之前**）。第一版测试漏了它：只断言"最终出现了一条 Call"，而共用解码器
     * 恰好也能产生**一条** Call（A 的前半 + B 的后半），于是测试照样通过。
     * 对照实验（M4）抓到了这个空转断言 —— "断言最终出现了什么"是不够的，
     * 还要断言"在错误的那一侧发生之前什么都没出现"。
     */
    void decodersArePerConnection()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy spy(&server, &SignalingServer::signalReceived);

        QTcpSocket a, b;
        a.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(a.waitForConnected(3000));
        b.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(b.waitForConnected(3000));
        QTest::qWait(150);

        // A 发前半，B 发后半。共用解码器会立刻拼出一条 call —— 必须没有。
        a.write(QByteArrayLiteral("cal"));
        a.flush();
        b.write(QByteArrayLiteral("l\n"));
        b.flush();
        QTest::qWait(300);
        QCOMPARE(spy.count(), 0); // ← 这条才是真正有区分度的断言

        // A 补上自己的后半 —— 只有此时才应出现第一条 call，且来自 A。
        a.write(QByteArrayLiteral("l\n"));
        a.flush();
        QVERIFY(waitFor([&spy]() { return spy.count() >= 1; }));
        QCOMPARE(spy.at(0).at(0).value<protocol::Signal>(), protocol::Signal::Call);
        QCOMPARE(spy.count(), 1);

        // 再确认信令确实归属 A 这条连接（而不是 B 的 socket 上凭空多出）。
        QTcpSocket* origin = spy.at(0).at(1).value<QTcpSocket*>();
        QVERIFY(origin != nullptr);
        QCOMPARE(origin->peerPort(), a.localPort());
        server.stop();
    }

    /**
     * 断开后该连接的解码器必须被清掉。
     *
     * `QTcpSocket` 指针在 `deleteLater()` 之后**可能**被新连接复用；若陈旧的
     * 半包还留着，新连接的字节会被"续上"，解出一条谁也没发的信令。
     *
     * ⚠ 本用例**不具区分度**，如实记录（第 22 轮对照实验 M5 证实）：
     * 把 `onClientDisconnected()` 里的 `m_decoders.remove(client);` 删掉，
     * 本用例**照样通过**。原因是 `deleteLater()` 之后新连接拿到的是一个全新的
     * `QTcpSocket` 对象，其 `QHash` 键与旧的**不同**，所以陈旧条目根本不会
     * 被命中 —— 它只是**泄漏**（映射表无限增长），不会串味。
     *
     * 另用真实探针（8 次"连接-断开-重连"，观察 `nextPendingConnection()`
     * 返回的指针值）实测：8 次得到 **8 个互不相同的指针**，未观察到复用。
     * 因此当前无法构造出可复现的失败场景。
     *
     * 保留本用例与那行 `remove()` 的理由：一旦分配器真的复用了地址，
     * 串味就会发生且极难定位。这里如实标注"不具区分度"，而不是写一个
     * 看起来在防这件事、实则空转的断言。
     */
    void decoderIsClearedOnDisconnect()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy spy(&server, &SignalingServer::signalReceived);
        QSignalSpy disc(&server, &SignalingServer::clientDisconnected);

        {
            QTcpSocket a;
            a.connectToHost(QHostAddress::LocalHost, port);
            QVERIFY(a.waitForConnected(3000));
            a.write(QByteArrayLiteral("cal")); // 留一个半包
            a.flush();
            QTest::qWait(150);
            a.disconnectFromHost();
            QVERIFY(waitFor([&disc]() { return disc.count() >= 1; }));
        }

        // 新连接只发后半：若旧半包残留，就会拼出 call —— 那是错的。
        QTcpSocket b;
        b.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(b.waitForConnected(3000));
        b.write(QByteArrayLiteral("l\n"));
        b.flush();
        QTest::qWait(400);
        QCOMPARE(spy.count(), 0);
        server.stop();
    }

    /**
     * 一条连接断开不得影响另一条连接继续收信令。
     */
    void disconnectOfOneClientDoesNotAffectOther()
    {
        SignalingServer server;
        const quint16 port = pickPort();
        QVERIFY(server.listen(port));
        QSignalSpy spy(&server, &SignalingServer::signalReceived);
        QSignalSpy disc(&server, &SignalingServer::clientDisconnected);

        QTcpSocket a, b;
        a.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(a.waitForConnected(3000));
        b.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(b.waitForConnected(3000));
        QTest::qWait(150);

        a.disconnectFromHost();
        QVERIFY(waitFor([&disc]() { return disc.count() >= 1; }));

        b.write(QByteArrayLiteral("unlock\n"));
        b.flush();
        QVERIFY(waitFor([&spy]() { return spy.count() >= 1; }));
        QCOMPARE(spy.last().at(0).value<protocol::Signal>(), protocol::Signal::Unlock);
        server.stop();
    }

    // -----------------------------------------------------------------------
    // 协议常量（硬约束）
    // -----------------------------------------------------------------------

    /// 端口与线上文本被钉住：8887，且每条信令的字节形态固定。
    void protocolConstantsAreFrozen()
    {
        QCOMPARE(protocol::kSignalingPort, static_cast<quint16>(8887));
        QCOMPARE(protocol::kSignalTerminator, '\n');
        QCOMPARE(protocol::kProtocolVersion, 1);

        // 门口机 → 室内机
        QCOMPARE(protocol::frame(protocol::Signal::Call), QByteArrayLiteral("call\n"));
        QCOMPARE(protocol::frame(protocol::Signal::StopSend),
                 QByteArrayLiteral("stopsend\n"));
        QCOMPARE(protocol::frame(protocol::Signal::Unlock),
                 QByteArrayLiteral("unlock\n"));
        // 室内机 → 门口机
        QCOMPARE(protocol::frame(protocol::Signal::Accept),
                 QByteArrayLiteral("accept\n"));
        QCOMPARE(protocol::frame(protocol::Signal::RecStop),
                 QByteArrayLiteral("recstop\n"));
        // 远程监看（裸文本，不带 '\n' 才是线上形态，见 UDP 50000）
        QCOMPARE(protocol::toWire(protocol::Signal::GetFrame),
                 QByteArrayLiteral("getframe"));
        QCOMPARE(protocol::toWire(protocol::Signal::Stop),
                 QByteArrayLiteral("stop"));

        // Unknown 必须产生**空帧**，而不是空字符串 + '\n'。
        QVERIFY(protocol::frame(protocol::Signal::Unknown).isEmpty());
        QVERIFY(protocol::toWire(protocol::Signal::Unknown).isEmpty());
    }

    /// 四个端口互不重叠（信令 / 音频 / 视频 / 预览）。
    void allPortsAreDistinct()
    {
        const quint16 ports[4] = {
            protocol::kSignalingPort, protocol::kAudioPort,
            protocol::kVideoPort, protocol::kPreviewPort
        };
        QCOMPARE(ports[0], static_cast<quint16>(8887));
        QCOMPARE(ports[1], static_cast<quint16>(12345));
        QCOMPARE(ports[2], static_cast<quint16>(23456));
        QCOMPARE(ports[3], static_cast<quint16>(50000));
        for (int i = 0; i < 4; ++i) {
            for (int j = i + 1; j < 4; ++j) {
                QVERIFY2(ports[i] != ports[j], "端口不得重复");
            }
        }
    }
};

QTEST_MAIN(TestSignalingServer)
#include "test_signaling_server.moc"
