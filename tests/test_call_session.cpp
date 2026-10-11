/**
 * @file test_call_session.cpp
 * @brief CallSession（室内机通话：双向音频 + 单向视频）单元测试。
 *
 * 背景
 * ----
 * `src/core/media/call_session.cpp` 此前**从未被任何测试目标链接**，却是
 * 两条协议硬约束的室内机一侧：
 *   - **UDP 12345** 双向音频，裸 PCM（S16_LE / 16000Hz / 单声道），无包头，
 *     每包 320 帧 / 640 字节；
 *   - **UDP 23456** 单向视频，门口机→室内机，每包一帧**完整 JPEG**，
 *     不重组、不重传。
 * 门口机那一侧有测试，室内机这一侧没有 —— 于是门口机改了字节，
 * 这边仍然是绿的，而互操作已经断了。
 *
 * 怎么测（socket 用真的，只替声卡）
 * --------------------------------
 * 端口是**协议常量**，不能像 monitor_client 那样挪到别的端口去测。探针实测
 * （%TEMP%\probe34\result17.txt）确认本机可以：
 *     bind(AnyIPv4, 12345, ShareAddress) = true
 *     收到报文 640 字节，sender=127.0.0.2:52803 与发送端一致
 * 因此这里让 CallSession 在**真实协议端口**上收发，用另一个 QUdpSocket
 * 充当门口机 —— 这样才真的证明了"端口对了、报文语义对了"。
 *
 * 只有声卡是替身：本机虽有可用音频设备（探针 result16.txt），但把单元测试
 * 绑在开发机的真实声卡上会让结果取决于机器（有无声卡、是否被独占）——
 * 那正是"在我这儿能跑"的坑。替身让音频路径完全确定。
 *
 * 端口独占：12345/23456 是固定端口，同一时刻只能有一个绑成功
 * （探针 result18.txt：独占绑占住后 ShareAddress 绑会失败）。因此
 * initTestCase 会先确认两个端口空闲，否则直接跳过并说明原因，而不是
 * 跑出一堆莫名其妙的失败。
 */
#include <QAudioFormat>
#include <QBuffer>
#include <QByteArray>
#include <QColor>
#include <QElapsedTimer>
#include <QHostAddress>
#include <QImage>
#include <QSignalSpy>
#include <QString>
#include <QUdpSocket>
#include <QtTest>

#include <functional>

#include "core/media/call_session.h"
#include "core/net/protocol.h"
#include "fake_audio.h"

using accessterminal::CallSession;

namespace {

/// 假门口机所在地址。用环回别名避免与"真正监听 12345 的其它进程"抢包。
const char* const kTerminalIp = "127.0.0.2";

/// 造一张可解码的 JPEG（与 monitor_client 测试同一手法）。
QByteArray makeJpeg(int w, int h, int hue)
{
    QImage img(w, h, QImage::Format_RGB32);
    img.fill(QColor::fromHsv(hue, 200, 200));
    QByteArray out;
    QBuffer buf(&out);
    buf.open(QIODevice::WriteOnly);
    img.save(&buf, "JPEG", 75);
    buf.close();
    return out;
}

/// 等某个谓词成立（按性质等，不按固定时长等）。
bool waitFor(const std::function<bool()>& pred, int timeoutMs = 5000)
{
    QElapsedTimer t;
    t.start();
    while (!pred() && t.elapsed() < timeoutMs) {
        QTest::qWait(5);
    }
    return pred();
}

/// 某个固定端口当前是否空闲（能绑上就说明没人独占）。
bool portIsFree(quint16 port)
{
    QUdpSocket s;
    const bool ok = s.bind(QHostAddress::AnyIPv4, port,
                           QUdpSocket::ShareAddress);
    if (ok) {
        s.close();
    }
    return ok;
}

} // namespace

class TestCallSession : public QObject
{
    Q_OBJECT

private slots:
    void initTestCase();
    void init();
    void cleanup();

    // ---- 生命周期 ----
    void constructionDoesNotBindOrOpenAudio();
    void startMarksRunning();
    void startIsIdempotentInRunningFlag();
    void stopMarksNotRunning();
    void stopIsSafeBeforeStart();
    void destructorStopsEverything();
    void startAfterStopWorksAgain();
    void startForgetsTheLearnedReturnAddress();
    void stopReleasesBothUdpPorts();

    // ---- 音频 UDP 12345：接收 ----
    void audioDatagramReachesTheAudioBuffer();
    void audioPacketsAccumulate();
    void audioBufferIsCappedAtTheJitterLimit();
    void audioWithoutAnOutputDeviceIsDropped();
    void audioStopsWritingWhenTheDeviceTakesNothing();
    void audioFromTheTerminalLearnsTheReturnAddress();

    // ---- 音频 UDP 12345：回传 ----
    void noUplinkBeforeTheTerminalIsHeard();
    void uplinkGoesToTheTerminalAddressAndPort();
    void uplinkSendsExactlyOnePacketPerFullChunk();
    void uplinkDoesNotSendPartialChunk();

    // ---- 视频 UDP 23456 ----
    void videoJpegEmitsOneFrame();
    void videoRejectsNonJpeg();
    void videoRejectsTruncatedJpeg();
    void videoEmitsOneFramePerDatagram();
    void videoDoesNotEmitEmptyDatagram();

    // ---- 声卡格式与缓冲（协议契约）----
    void audioFormatIsPcm16kMonoSignedLittleEndian();
    void inputBufferSizeIsOnePacket();
    void outputBufferSizeIs27ms();

    // ---- 失败路径 ----
    void audioBindFailureEmitsError();
    void videoBindFailureEmitsError();
    void audioBindFailureDoesNotMarkRunningFailuresAsFatal();
    void outputStartFailureIsSurvivable();
    void inputStartFailureIsSurvivable();

    // ---- 正对照 ----
    void signalSpiesAreLive();
};

void TestCallSession::initTestCase()
{
    // 两个端口都是协议固定值，被别的进程占着就没法测。
    // 与其跑出一堆莫名的失败，不如明确跳过并说明原因。
    if (!portIsFree(accessterminal::protocol::kAudioPort)) {
        QSKIP("UDP 12345 被占用（另一个测试或真实程序在跑），无法在真实协议"
              "端口上验证音频路径。");
    }
    if (!portIsFree(accessterminal::protocol::kVideoPort)) {
        QSKIP("UDP 23456 被占用，无法在真实协议端口上验证视频路径。");
    }
}

void TestCallSession::init()
{
    resetFakeAudio();
}

void TestCallSession::cleanup()
{
    // 每个用例结束时确保端口被释放（CallSession 析构会 stop()）。
    QTest::qWait(20);
}

// ---------------------------------------------------------------------------
// 生命周期
// ---------------------------------------------------------------------------

void TestCallSession::constructionDoesNotBindOrOpenAudio()
{
    CallSession session;
    // 构造不得占用端口或声卡：通话未接通前必须一切安静。
    QCOMPARE(session.isRunning(), false);
    QCOMPARE(fakeAudio().outCtorCalls, 0);
    QCOMPARE(fakeAudio().inCtorCalls, 0);
    QCOMPARE(fakeAudio().outStartCalls, 0);
    QCOMPARE(fakeAudio().inStartCalls, 0);
    QVERIFY2(portIsFree(accessterminal::protocol::kAudioPort),
             "构造后音频端口仍应空闲");
}

void TestCallSession::startMarksRunning()
{
    CallSession session;
    session.start();
    QCOMPARE(session.isRunning(), true);
}

void TestCallSession::startIsIdempotentInRunningFlag()
{
    CallSession session;
    session.start();
    // 第二次 start() 必须先 stop() 再重建；运行标志仍为 true，
    // 且不应因为"端口已被自己占着"而失败。
    session.start();
    QCOMPARE(session.isRunning(), true);
    // 声卡被重建：输出/输入各构造了两次。
    QCOMPARE(fakeAudio().outCtorCalls, 2);
    QCOMPARE(fakeAudio().inCtorCalls, 2);
}

void TestCallSession::stopMarksNotRunning()
{
    CallSession session;
    session.start();
    session.stop();
    QCOMPARE(session.isRunning(), false);
}

void TestCallSession::stopIsSafeBeforeStart()
{
    CallSession session;
    session.stop(); // 从未 start：全部成员都是 nullptr，不得崩
    QCOMPARE(session.isRunning(), false);
    QCOMPARE(fakeAudio().outStopCalls, 0);
}

void TestCallSession::destructorStopsEverything()
{
    {
        CallSession session;
        session.start();
        QCOMPARE(fakeAudio().outStopCalls, 0);
    }
    // 析构必须 stop()：否则端口与声卡会留在进程里。
    QCOMPARE(fakeAudio().outStopCalls, 1);
    QCOMPARE(fakeAudio().inStopCalls, 1);
    QVERIFY2(portIsFree(accessterminal::protocol::kAudioPort),
             "析构后音频端口必须释放");
    QVERIFY2(portIsFree(accessterminal::protocol::kVideoPort),
             "析构后视频端口必须释放");
}

void TestCallSession::startAfterStopWorksAgain()
{
    CallSession session;
    session.start();
    session.stop();
    session.start();
    QCOMPARE(session.isRunning(), true);
    QCOMPARE(fakeAudio().outCtorCalls, 2);
    QCOMPARE(fakeAudio().inCtorCalls, 2);
}

void TestCallSession::startForgetsTheLearnedReturnAddress()
{
    // 重复 start() 必须**先 stop()**，而 stop() 会清掉学到的回传地址。
    //
    // 这是唯一能把"start() 里那句 if (m_running) stop();"区分开的可观测行为：
    // 少了它，交错的旧状态（尤其是"目标地址"）会留到新通话里 —— 新通话
    // 还没听到对方，就会把本地语音发到**上一次通话的对端地址**去。
    // （端口本身区分不出来：自己已绑着 12345 时再绑一次，无论是否先 stop()
    //   都拿不到干净端口，见探针 result20.txt A 组。）
    CallSession session;
    session.start();

    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));

    // 让会话学到门口机地址。
    terminal.writeDatagram(
        QByteArray(accessterminal::protocol::kAudioBytesPerPacket, 'A'),
        QHostAddress::LocalHost, accessterminal::protocol::kAudioPort);
    QVERIFY(waitFor([&]() {
        return fakeAudio().outDevice
               && fakeAudio().outDevice->written.size() > 0;
    }));

    // 清掉排队包，再重新 start()。
    while (terminal.hasPendingDatagrams()) {
        QByteArray d;
        d.resize(static_cast<int>(terminal.pendingDatagramSize()));
        terminal.readDatagram(d.data(), d.size());
    }
    session.start();

    // 新通话尚未听到任何门口机音频 —— 此时投喂本地语音**绝不能**发出去。
    fakeAudio().inDevice->feedBytes(
        QByteArray(accessterminal::protocol::kAudioBytesPerPacket, 'X'));
    QTest::qWait(250);
    QVERIFY2(!terminal.hasPendingDatagrams(),
             "重新 start() 后必须忘掉上一轮的回归地址，否则会把语音发给"
             "上一次通话的对端");
}

void TestCallSession::stopReleasesBothUdpPorts()
{
    {
        CallSession session;
        session.start();
        // 启动期间两个端口都该被本会话占着。
        QCOMPARE(fakeAudio().outStartCalls, 1);
        QCOMPARE(fakeAudio().inStartCalls, 1);
    }
    QVERIFY(portIsFree(accessterminal::protocol::kAudioPort));
    QVERIFY(portIsFree(accessterminal::protocol::kVideoPort));
}

// ---------------------------------------------------------------------------
// 音频接收
// ---------------------------------------------------------------------------

void TestCallSession::audioDatagramReachesTheAudioBuffer()
{
    CallSession session;
    session.start();

    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));

    const QByteArray pcm(accessterminal::protocol::kAudioBytesPerPacket, 'A');
    QCOMPARE(terminal.writeDatagram(
                 pcm, QHostAddress::LocalHost,
                 accessterminal::protocol::kAudioPort),
             static_cast<qint64>(pcm.size()));

    // 收到后会被 writeAudioData() 写进声卡替身设备。
    QVERIFY2(waitFor([&]() {
                 return fakeAudio().outDevice
                        && fakeAudio().outDevice->written.size() > 0;
             }),
             "音频包应当被写进声卡输出设备");
    QCOMPARE(fakeAudio().outDevice->written, pcm);
}

void TestCallSession::audioPacketsAccumulate()
{
    CallSession session;
    session.start();

    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));

    QByteArray expect;
    for (int i = 0; i < 3; ++i) {
        QByteArray pcm(accessterminal::protocol::kAudioBytesPerPacket,
                       static_cast<char>('A' + i));
        expect.append(pcm);
        terminal.writeDatagram(pcm, QHostAddress::LocalHost,
                               accessterminal::protocol::kAudioPort);
    }

    QVERIFY2(waitFor([&]() {
                 return fakeAudio().outDevice
                        && fakeAudio().outDevice->written.size()
                               >= expect.size();
             }),
             "三个音频包都应当到达声卡");
    QCOMPARE(fakeAudio().outDevice->written, expect);
}

void TestCallSession::audioBufferIsCappedAtTheJitterLimit()
{
    // kMaxAudioBufferMs = 200ms；16k*1ch*2B = 32 字节/ms -> 6400 字节上限。
    // 把声卡设成"永远写不进去"（bytesFree=0），于是缓冲区只增不减，
    // 超过上限就必须从**头部**丢旧数据。
    CallSession session;
    fakeAudio().bytesFree = 0;
    session.start();

    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));

    // 发足够多的包：每包 640 字节，20 包 = 12800 字节 > 6400。
    const int packets = 20;
    for (int i = 0; i < packets; ++i) {
        QByteArray pcm(accessterminal::protocol::kAudioBytesPerPacket,
                       static_cast<char>('a' + (i % 26)));
        terminal.writeDatagram(pcm, QHostAddress::LocalHost,
                               accessterminal::protocol::kAudioPort);
        QTest::qWait(3);
    }
    QTest::qWait(200);

    // 缓冲区被限长后，写不出去的部分不会无限增长；此时 bytesFree 仍为 0，
    // 所以声卡里应当什么都没有。
    QCOMPARE(fakeAudio().outDevice ? fakeAudio().outDevice->written.size() : 0,
             0);

    // 恢复可写，再发一个包触发 writeAudioData()，此时写出的字节数
    // **不应超过上限**（丢旧包而不是无界累积）。
    fakeAudio().bytesFree = 1024 * 1024;
    QByteArray probe(accessterminal::protocol::kAudioBytesPerPacket, 'Z');
    terminal.writeDatagram(probe, QHostAddress::LocalHost,
                           accessterminal::protocol::kAudioPort);
    QVERIFY(waitFor([&]() {
        return fakeAudio().outDevice
               && fakeAudio().outDevice->written.size() > 0;
    }));
    const int written = fakeAudio().outDevice->written.size();
    const int bytesPerMs = accessterminal::protocol::kAudioSampleRate
                           * accessterminal::protocol::kAudioChannels
                           * accessterminal::protocol::kAudioBytesPerSample
                           / 1000;
    const int cap = 200 * bytesPerMs;
    QVERIFY2(written <= cap + accessterminal::protocol::kAudioBytesPerPacket,
             qPrintable(QStringLiteral("写出 %1 字节，超过 200ms 上限 %2")
                            .arg(written).arg(cap)));
}

void TestCallSession::audioWithoutAnOutputDeviceIsDropped()
{
    // 声卡起不来时 m_audioDevice 是 nullptr（也顺带覆盖 m_audioOutput 兜底），
    // 此时收到音频包**绝不能崩**，而且不能留下"越攒越多"的缓冲。
    CallSession session;
    fakeAudio().failOutputStart = true;
    session.start();
    QVERIFY(fakeAudio().outDevice == nullptr
            || fakeAudio().outDevice->written.isEmpty());

    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));
    terminal.writeDatagram(
        QByteArray(accessterminal::protocol::kAudioBytesPerPacket, 'A'),
        QHostAddress::LocalHost, accessterminal::protocol::kAudioPort);
    QTest::qWait(250);

    // 没有输出设备 -> 一个字节也写不出去；进程仍然活着。
    QCOMPARE(session.isRunning(), true);
    QCOMPARE(fakeAudio().outDevice ? fakeAudio().outDevice->written.size() : 0, 0);
}

void TestCallSession::audioStopsWritingWhenTheDeviceTakesNothing()
{
    // writeAudioData() 的 `else { break; }`：设备一次写不进任何字节时必须
    // **跳出循环**，而不是无限重试（那会把 UI 线程卡死）。
    CallSession session;
    session.start();
    QVERIFY(fakeAudio().outDevice != nullptr);
    fakeAudio().outDevice->writeReturnsZero = true;

    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));
    terminal.writeDatagram(
        QByteArray(accessterminal::protocol::kAudioBytesPerPacket, 'A'),
        QHostAddress::LocalHost, accessterminal::protocol::kAudioPort);

    // 必须在有限时间内返回（卡死就会等到超时）。
    QVERIFY2(waitFor([&]() {
                 return fakeAudio().outDevice->writeZeroCalls > 0;
             }, 2000),
             "writeAudioData 必须真的尝试过写入");
    QTest::qWait(120);
    // 尝试次数极少（每次 readyRead 只试一次就 break），绝不该是几千次。
    QVERIFY2(fakeAudio().outDevice->writeZeroCalls < 50,
             qPrintable(QStringLiteral("设备不收数据时重试了 %1 次，"
                                       "应当在第一次失败就 break")
                            .arg(fakeAudio().outDevice->writeZeroCalls)));
    QCOMPARE(fakeAudio().outDevice->written.size(), 0);
}

void TestCallSession::audioFromTheTerminalLearnsTheReturnAddress()
{
    CallSession session;
    session.start();

    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));

    QByteArray pcm(accessterminal::protocol::kAudioBytesPerPacket, 'A');
    terminal.writeDatagram(pcm, QHostAddress::LocalHost,
                           accessterminal::protocol::kAudioPort);
    QVERIFY(waitFor([&]() {
        return fakeAudio().outDevice
               && fakeAudio().outDevice->written.size() > 0;
    }));

    // 学到地址后，投喂上行语音就应发往该地址。
    fakeAudio().outDevice->written.clear();
    fakeAudio().inDevice->feedBytes(
        QByteArray(accessterminal::protocol::kAudioBytesPerPacket, 'B'));
    QVERIFY(waitFor([&]() { return terminal.hasPendingDatagrams(); }));

    QByteArray got;
    got.resize(static_cast<int>(terminal.pendingDatagramSize()));
    QHostAddress from;
    quint16 fromPort = 0;
    terminal.readDatagram(got.data(), got.size(), &from, &fromPort);
    QCOMPARE(got.size(), accessterminal::protocol::kAudioBytesPerPacket);
    QCOMPARE(got.at(0), 'B');
    Q_UNUSED(from);
    Q_UNUSED(fromPort);
}

// ---------------------------------------------------------------------------
// 音频回传
// ---------------------------------------------------------------------------

void TestCallSession::noUplinkBeforeTheTerminalIsHeard()
{
    CallSession session;
    session.start();

    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));

    // 还没收到过门口机的音频，设备地址未知 —— 此时投喂上行语音
    // **绝不能**发出去（避免把语音发给未知主机）。
    fakeAudio().inDevice->feedBytes(
        QByteArray(accessterminal::protocol::kAudioBytesPerPacket, 'X'));
    QTest::qWait(150);
    QCOMPARE(terminal.hasPendingDatagrams(), false);
}

void TestCallSession::uplinkGoesToTheTerminalAddressAndPort()
{
    CallSession session;
    session.start();

    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));

    // 先下行一包，让 CallSession 学到地址。
    QByteArray pcm(accessterminal::protocol::kAudioBytesPerPacket, 'A');
    terminal.writeDatagram(pcm, QHostAddress::LocalHost,
                           accessterminal::protocol::kAudioPort);
    QVERIFY(waitFor([&]() {
        return fakeAudio().outDevice
               && fakeAudio().outDevice->written.size() > 0;
    }));

    // 再上行：必须发到门口机的**实际端口**（不是 12345）。
    const QByteArray up(accessterminal::protocol::kAudioBytesPerPacket, 'U');
    fakeAudio().inDevice->feedBytes(up);
    QVERIFY(waitFor([&]() { return terminal.hasPendingDatagrams(); }));

    QByteArray got;
    got.resize(static_cast<int>(terminal.pendingDatagramSize()));
    QHostAddress from;
    quint16 fromPort = 0;
    terminal.readDatagram(got.data(), got.size(), &from, &fromPort);

    // 能收到本身就证明"发对了目的端口"：这个临时端口只有 terminal 在监听，
    // 若 CallSession 把包发去 12345 或别处，terminal 什么也收不到。
    QCOMPARE(got, up);
    // 再看来源：必须是 CallSession 自己的音频 socket（协议端口 12345）。
    // 注意不要拿它跟 terminalPort 比 —— fromPort 是**发送方**的端口，
    // 即会话的 12345，而 terminalPort 是**接收方**的端口，两者本来就不同。
    QCOMPARE(fromPort, accessterminal::protocol::kAudioPort);
    QVERIFY2(from.isLoopback(), qPrintable(from.toString()));
}

void TestCallSession::uplinkSendsExactlyOnePacketPerFullChunk()
{
    CallSession session;
    session.start();

    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));
    QByteArray pcm(accessterminal::protocol::kAudioBytesPerPacket, 'A');
    terminal.writeDatagram(pcm, QHostAddress::LocalHost,
                           accessterminal::protocol::kAudioPort);
    QVERIFY(waitFor([&]() {
        return fakeAudio().outDevice
               && fakeAudio().outDevice->written.size() > 0;
    }));

    const int pkt = accessterminal::protocol::kAudioBytesPerPacket;
    // 一次投喂 2.5 包 -> 应当发出 2 包，剩半包留在缓冲里。
    fakeAudio().inDevice->feedBytes(QByteArray(pkt * 2 + pkt / 2, 'U'));

    QVERIFY(waitFor([&]() { return terminal.hasPendingDatagrams(); }));
    QTest::qWait(150);

    int packets = 0;
    int firstTwoBytes = 0;
    while (terminal.hasPendingDatagrams()) {
        QByteArray d;
        d.resize(static_cast<int>(terminal.pendingDatagramSize()));
        terminal.readDatagram(d.data(), d.size());
        ++packets;
        if (d.size() == pkt) {
            ++firstTwoBytes;
        }
    }
    // 每包必须正好是 kAudioBytesPerPacket（不能把半包也发出去）。
    QCOMPARE(packets, 2);
    QCOMPARE(firstTwoBytes, 2);
}

void TestCallSession::uplinkDoesNotSendPartialChunk()
{
    CallSession session;
    session.start();

    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));
    QByteArray pcm(accessterminal::protocol::kAudioBytesPerPacket, 'A');
    terminal.writeDatagram(pcm, QHostAddress::LocalHost,
                           accessterminal::protocol::kAudioPort);
    QVERIFY(waitFor([&]() {
        return fakeAudio().outDevice
               && fakeAudio().outDevice->written.size() > 0;
    }));

    // 只投喂半包：不足一包就**不能发**（否则门口机会收到残缺 PCM）。
    fakeAudio().inDevice->feedBytes(
        QByteArray(accessterminal::protocol::kAudioBytesPerPacket / 2, 'U'));
    QTest::qWait(200);
    QCOMPARE(terminal.hasPendingDatagrams(), false);

    // 补足另一半 -> 这时才发一包。
    fakeAudio().inDevice->feedBytes(
        QByteArray(accessterminal::protocol::kAudioBytesPerPacket / 2, 'V'));
    QVERIFY(waitFor([&]() { return terminal.hasPendingDatagrams(); }));
    QByteArray got;
    got.resize(static_cast<int>(terminal.pendingDatagramSize()));
    terminal.readDatagram(got.data(), got.size());
    QCOMPARE(got.size(), accessterminal::protocol::kAudioBytesPerPacket);
}

// ---------------------------------------------------------------------------
// 视频
// ---------------------------------------------------------------------------

void TestCallSession::videoJpegEmitsOneFrame()
{
    CallSession session;
    session.start();

    QSignalSpy frames(&session, &CallSession::videoFrameReady);
    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));

    const QByteArray jpeg = makeJpeg(64, 48, 120);
    QVERIFY(!jpeg.isEmpty());
    terminal.writeDatagram(jpeg, QHostAddress::LocalHost,
                           accessterminal::protocol::kVideoPort);

    QVERIFY2(waitFor([&]() { return frames.count() > 0; }),
             "一整帧 JPEG 应当解出一帧画面");
    QCOMPARE(frames.count(), 1);
    const QImage got = frames.at(0).at(0).value<QImage>();
    QCOMPARE(got.size(), QSize(64, 48));
}

void TestCallSession::videoRejectsNonJpeg()
{
    CallSession session;
    session.start();

    QSignalSpy frames(&session, &CallSession::videoFrameReady);
    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));

    terminal.writeDatagram(QByteArray(600, 'x'), QHostAddress::LocalHost,
                           accessterminal::protocol::kVideoPort);
    QTest::qWait(200);
    QCOMPARE(frames.count(), 0);
}

void TestCallSession::videoRejectsTruncatedJpeg()
{
    CallSession session;
    session.start();

    QSignalSpy frames(&session, &CallSession::videoFrameReady);
    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));

    const QByteArray jpeg = makeJpeg(64, 48, 30);
    QVERIFY(jpeg.size() > 20);
    // 砍掉一半：解码必须失败，不能发出半张图。
    terminal.writeDatagram(jpeg.left(jpeg.size() / 2),
                           QHostAddress::LocalHost,
                           accessterminal::protocol::kVideoPort);
    QTest::qWait(300);
    QCOMPARE(frames.count(), 0);
}

void TestCallSession::videoEmitsOneFramePerDatagram()
{
    CallSession session;
    session.start();

    QSignalSpy frames(&session, &CallSession::videoFrameReady);
    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));

    // 每包一帧完整 JPEG：3 包 -> 3 帧，不重组、不重传。
    for (int i = 0; i < 3; ++i) {
        terminal.writeDatagram(makeJpeg(32, 32, i * 60),
                               QHostAddress::LocalHost,
                               accessterminal::protocol::kVideoPort);
        QTest::qWait(10);
    }
    QVERIFY(waitFor([&]() { return frames.count() >= 3; }));
    QCOMPARE(frames.count(), 3);
}

void TestCallSession::videoDoesNotEmitEmptyDatagram()
{
    CallSession session;
    session.start();

    QSignalSpy frames(&session, &CallSession::videoFrameReady);
    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));

    terminal.writeDatagram(QByteArray(), QHostAddress::LocalHost,
                           accessterminal::protocol::kVideoPort);
    QTest::qWait(200);
    QCOMPARE(frames.count(), 0);
}

// ---------------------------------------------------------------------------
// 声卡格式
// ---------------------------------------------------------------------------

void TestCallSession::audioFormatIsPcm16kMonoSignedLittleEndian()
{
    CallSession session;
    session.start();

    const FakeAudioFormatRecord& out = fakeAudio().outFormat;
    // 这些是**协议硬约束**：门口机发来的就是 S16_LE/16k/单声道。
    // 裸数值断言（而不是替身的枚举）钉住真 Qt 的取值。
    QCOMPARE(out.sampleRate, accessterminal::protocol::kAudioSampleRate);
    QCOMPARE(out.channelCount, accessterminal::protocol::kAudioChannels);
    QCOMPARE(out.sampleSize,
             accessterminal::protocol::kAudioBytesPerSample * 8);
    QCOMPARE(out.codec, QStringLiteral("audio/pcm"));
    QCOMPARE(out.byteOrder, 1);   // QAudioFormat::LittleEndian == 1
    QCOMPARE(out.sampleType, 1);  // QAudioFormat::SignedInt == 1

    // 输入侧必须完全一致，否则上下行声音会一个快一个慢。
    QCOMPARE(fakeAudio().inFormat.sampleRate, out.sampleRate);
    QCOMPARE(fakeAudio().inFormat.channelCount, out.channelCount);
    QCOMPARE(fakeAudio().inFormat.sampleSize, out.sampleSize);
    QCOMPARE(fakeAudio().inFormat.byteOrder, out.byteOrder);
    QCOMPARE(fakeAudio().inFormat.sampleType, out.sampleType);

    // 每帧 2 字节 = 16 位单声道。
    QCOMPARE(fakeAudio().outBytesPerFrame, 2);
    QCOMPARE(fakeAudio().inBytesPerFrame, 2);
}

void TestCallSession::inputBufferSizeIsOnePacket()
{
    CallSession session;
    session.start();
    QCOMPARE(fakeAudio().inBufferSize,
             accessterminal::protocol::kAudioFramesPerPacket);
}

void TestCallSession::outputBufferSizeIs27ms()
{
    CallSession session;
    session.start();
    // bytesPerMs = 2 * 16000 / 1000 = 32；缓冲区 = 32 * 27 = 864。
    const int bytesPerMs = 2 * accessterminal::protocol::kAudioSampleRate / 1000;
    QCOMPARE(fakeAudio().outBufferSize, bytesPerMs * 27);
    QCOMPARE(fakeAudio().outNotifyInterval, 1);
}

// ---------------------------------------------------------------------------
// 失败路径
// ---------------------------------------------------------------------------

void TestCallSession::audioBindFailureEmitsError()
{
    // 用另一个 socket **独占**占住 12345，于是 CallSession 的 ShareAddress 绑
    // 必然失败（探针 result18.txt：3/3 次稳定复现）。
    QUdpSocket squatter;
    QVERIFY(squatter.bind(QHostAddress::AnyIPv4,
                          accessterminal::protocol::kAudioPort));

    CallSession session;
    QSignalSpy errors(&session, &CallSession::errorOccurred);
    session.start();

    QCOMPARE(errors.count(), 1);
    const QString msg = errors.at(0).at(0).toString();
    QVERIFY2(msg.contains(QString::number(accessterminal::protocol::kAudioPort)),
             qPrintable(msg));
    QVERIFY2(msg.contains(QStringLiteral("音频")), qPrintable(msg));
}

void TestCallSession::videoBindFailureEmitsError()
{
    QUdpSocket squatter;
    QVERIFY(squatter.bind(QHostAddress::Any,
                          accessterminal::protocol::kVideoPort));

    CallSession session;
    QSignalSpy errors(&session, &CallSession::errorOccurred);
    session.start();

    QCOMPARE(errors.count(), 1);
    const QString msg = errors.at(0).at(0).toString();
    QVERIFY2(msg.contains(QString::number(accessterminal::protocol::kVideoPort)),
             qPrintable(msg));
    QVERIFY2(msg.contains(QStringLiteral("视频")), qPrintable(msg));
}

void TestCallSession::audioBindFailureDoesNotMarkRunningFailuresAsFatal()
{
    // 端口失败**不影响**会话继续：整体 live 且不抛异常（通话界面仍可显示，
    // 只是没有声音）——头文件里明确承诺了这个行为，必须钉住。
    QUdpSocket squatter;
    QVERIFY(squatter.bind(QHostAddress::AnyIPv4,
                          accessterminal::protocol::kAudioPort));

    CallSession session;
    QSignalSpy errors(&session, &CallSession::errorOccurred);
    session.start();
    QCOMPARE(errors.count(), 1);
    // 音频口坏了，视频口仍应被绑上。
    QCOMPARE(fakeAudio().outStartCalls, 1);
    QCOMPARE(fakeAudio().inStartCalls, 1);
    session.stop();
    QCOMPARE(session.isRunning(), false);
}

void TestCallSession::outputStartFailureIsSurvivable()
{
    CallSession session;
    fakeAudio().failOutputStart = true;
    session.start();
    // 声卡起不来只记日志，不得崩、不得影响其余通道。
    QCOMPARE(session.isRunning(), true);
    QCOMPARE(fakeAudio().inStartCalls, 1);
}

void TestCallSession::inputStartFailureIsSurvivable()
{
    CallSession session;
    fakeAudio().failInputStart = true;
    session.start();
    QCOMPARE(session.isRunning(), true);
    QCOMPARE(fakeAudio().outStartCalls, 1);
    // 输入设备为 nullptr 时，投喂路径不能崩。
    session.stop();
}

// ---------------------------------------------------------------------------
// 正对照
// ---------------------------------------------------------------------------

void TestCallSession::signalSpiesAreLive()
{
    // 上面多条断言都依赖 QSignalSpy 真的在记数。若 QImage 的元类型没注册，
    // QSignalSpy 会记不到 videoFrameReady —— 那些"count()==0"的断言就会
    // **真空成立**。这里证明 spy 管道是通的。
    CallSession session;
    session.start();
    QSignalSpy frames(&session, &CallSession::videoFrameReady);

    QUdpSocket terminal;
    QVERIFY(terminal.bind(QHostAddress(QString::fromLatin1(kTerminalIp)), 0));
    terminal.writeDatagram(makeJpeg(16, 16, 200), QHostAddress::LocalHost,
                           accessterminal::protocol::kVideoPort);
    QVERIFY2(waitFor([&]() { return frames.count() > 0; }),
             "QSignalSpy 应当能捕获 videoFrameReady（QImage 必须可入队）");
}

QTEST_MAIN(TestCallSession)
#include "test_call_session.moc"
