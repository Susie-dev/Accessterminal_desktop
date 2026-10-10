/**
 * @file test_protocol.cpp
 * @brief 协议常量与信令编解码的一致性测试。
 *
 * 这是跨仓库契约的守卫：任何改动端口、信令字符串、音视频参数的提交
 * 都会在此处失败，从而强制开发者同步 Accessterminal_T113 与
 * Accessterminal_desktop 两份 protocol.h。
 *
 * 构建与运行：
 *   cmake -S . -B build -DACCESSTERMINAL_BUILD_TESTS=ON
 *   cmake --build build
 *   ctest --test-dir build --output-on-failure
 */
#include "core/net/protocol.h"

#include <QtTest/QtTest>

using namespace accessterminal;

class TestProtocol : public QObject
{
    Q_OBJECT

private slots:
    // ---- 端口契约：两端必须一致，改端口即破坏兼容性 ----
    void portsMatchContract()
    {
        QCOMPARE(protocol::kSignalingPort, quint16(8887));
        QCOMPARE(protocol::kAudioPort, quint16(12345));
        QCOMPARE(protocol::kVideoPort, quint16(23456));
        QCOMPARE(protocol::kPreviewPort, quint16(50000));
    }

    // ---- 音频参数：ALSA 与网络包长必须自洽 ----
    void audioParametersAreConsistent()
    {
        QCOMPARE(protocol::kAudioSampleRate, 16000);
        QCOMPARE(protocol::kAudioChannels, 1);
        QCOMPARE(protocol::kAudioBytesPerSample, 2);
        QCOMPARE(protocol::kAudioFramesPerPacket, 320);
        // 320 帧 * 1 声道 * 2 字节 = 640 字节 ≈ 20ms
        QCOMPARE(protocol::kAudioBytesPerPacket, 640);
        QCOMPARE(protocol::kAudioBytesPerPacket,
                 protocol::kAudioFramesPerPacket
                     * protocol::kAudioChannels
                     * protocol::kAudioBytesPerSample);

        // 20ms 一包：包数 * 帧数 / 采样率 == 1 秒
        const int packetsPerSecond = protocol::kAudioSampleRate
                                     / protocol::kAudioFramesPerPacket;
        QCOMPARE(packetsPerSecond, 50);
    }

    void protocolVersionIsSet()
    {
        QCOMPARE(protocol::kProtocolVersion, 1);
    }

    void terminatorIsNewline()
    {
        QCOMPARE(protocol::kSignalTerminator, '\n');
    }

    // ---- 编解码往返：每个信令都应稳定还原 ----
    void wireRoundTrip_data()
    {
        QTest::addColumn<int>("signal");
        QTest::addColumn<QByteArray>("wire");

        QTest::newRow("call")     << int(protocol::Signal::Call)     << QByteArray("call");
        QTest::newRow("accept")   << int(protocol::Signal::Accept)   << QByteArray("accept");
        QTest::newRow("recstop")  << int(protocol::Signal::RecStop)  << QByteArray("recstop");
        QTest::newRow("unlock")   << int(protocol::Signal::Unlock)   << QByteArray("unlock");
        QTest::newRow("stopsend") << int(protocol::Signal::StopSend) << QByteArray("stopsend");
        QTest::newRow("getframe") << int(protocol::Signal::GetFrame) << QByteArray("getframe");
        QTest::newRow("stop")     << int(protocol::Signal::Stop)     << QByteArray("stop");
    }

    void wireRoundTrip()
    {
        QFETCH(int, signal);
        QFETCH(QByteArray, wire);

        const protocol::Signal s = static_cast<protocol::Signal>(signal);

        // 枚举 → 线上文本
        QCOMPARE(protocol::toWire(s), wire);
        // 线上文本 → 枚举
        QCOMPARE(protocol::fromWire(wire), s);
        // 帧格式：文本 + '\n'
        QCOMPARE(protocol::frame(s), wire + '\n');
    }

    // ---- 线上文本必须逐字节固定，禁止大小写/空白变化 ----
    void wireStringsAreExact()
    {
        QCOMPARE(protocol::toWire(protocol::Signal::Call), QByteArray("call"));
        QCOMPARE(protocol::toWire(protocol::Signal::Accept), QByteArray("accept"));
        QCOMPARE(protocol::toWire(protocol::Signal::RecStop), QByteArray("recstop"));
        QCOMPARE(protocol::toWire(protocol::Signal::Unlock), QByteArray("unlock"));
        QCOMPARE(protocol::toWire(protocol::Signal::StopSend), QByteArray("stopsend"));
        QCOMPARE(protocol::toWire(protocol::Signal::GetFrame), QByteArray("getframe"));
        QCOMPARE(protocol::toWire(protocol::Signal::Stop), QByteArray("stop"));
    }

    // ---- 未知信令必须被容忍：旧版本互通时的前向兼容 ----
    void unknownSignalsAreTolerated()
    {
        QCOMPARE(protocol::fromWire(QByteArray("bogus")), protocol::Signal::Unknown);
        QCOMPARE(protocol::fromWire(QByteArray("")), protocol::Signal::Unknown);
        QCOMPARE(protocol::fromWire(QByteArray("CALL")), protocol::Signal::Unknown); // 大小写敏感
        QCOMPARE(protocol::toWire(protocol::Signal::Unknown), QByteArray());
        QCOMPARE(protocol::frame(protocol::Signal::Unknown), QByteArray());
    }

    // ---- 解析需容忍网络带来的首尾空白 ----
    void fromWireTrimsWhitespace()
    {
        QCOMPARE(protocol::fromWire(QByteArray(" accept ")), protocol::Signal::Accept);
        QCOMPARE(protocol::fromWire(QByteArray("\raccept\r")), protocol::Signal::Accept);
        // 结尾的 '\n' 也应被容忍
        QCOMPARE(protocol::fromWire(QByteArray("accept\n")), protocol::Signal::Accept);
    }

    // ---- 守护 "accept 之前不得建流" 这一生命周期约定所依赖的信令集合 ----
    void lifecycleSignalsArePresent()
    {
        // accept 触发建流，recstop 触发拆流：两者缺一不可
        QVERIFY(protocol::fromWire(QByteArray("accept")) == protocol::Signal::Accept);
        QVERIFY(protocol::fromWire(QByteArray("recstop")) == protocol::Signal::RecStop);
        // 远程监看由 getframe/stop 控制
        QVERIFY(protocol::fromWire(QByteArray("getframe")) == protocol::Signal::GetFrame);
        QVERIFY(protocol::fromWire(QByteArray("stop")) == protocol::Signal::Stop);
    }
};

QTEST_MAIN(TestProtocol)
#include "test_protocol.moc"
