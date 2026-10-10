/**
 * @file call_session.cpp
 * @brief CallSession 实现。
 */
#include "core/media/call_session.h"

#include "core/net/protocol.h"

#include <QAudioFormat>
#include <QAudioInput>
#include <QAudioOutput>
#include <QDebug>
#include <QIODevice>
#include <QImage>
#include <QUdpSocket>

namespace accessterminal {

namespace {

/// 音频缓冲上限：网络抖动时宁丢旧包，也不让延迟持续累积。
constexpr int kMaxAudioBufferMs = 200;

/// 回传语音的打包大小（字节）。与门口机一致，20ms 一包。
constexpr int kAudioPacketBytes = protocol::kAudioBytesPerPacket;

/// 构造两端一致的 PCM 格式。
QAudioFormat pcmFormat()
{
    QAudioFormat format;
    format.setSampleRate(protocol::kAudioSampleRate);
    format.setChannelCount(protocol::kAudioChannels);
    format.setSampleSize(protocol::kAudioBytesPerSample * 8);
    format.setCodec(QStringLiteral("audio/pcm"));
    format.setByteOrder(QAudioFormat::LittleEndian);
    format.setSampleType(QAudioFormat::SignedInt);
    return format;
}

} // namespace

CallSession::CallSession(QObject* parent)
    : QObject(parent)
{
}

CallSession::~CallSession()
{
    stop();
}

void CallSession::start()
{
    if (m_running) {
        stop();
    }
    m_running = true;

    // 先起 socket，再起声卡；任何一步失败都只记录日志。
    startAudioSocket();
    startVideoSocket();
    startAudioOutput();
    startAudioInput();

    qInfo() << "[通话] 音视频通道已启动";
}

bool CallSession::startAudioSocket()
{
    if (m_audioSocket) {
        return true;
    }
    m_audioSocket = new QUdpSocket(this);
    // 与重构前一致：AnyIPv4 + ShareAddress。
    if (!m_audioSocket->bind(QHostAddress::AnyIPv4, protocol::kAudioPort,
                             QUdpSocket::ShareAddress)) {
        const QString msg = QStringLiteral("音频 UDP 端口 %1 监听失败: %2")
                                .arg(protocol::kAudioPort)
                                .arg(m_audioSocket->errorString());
        qWarning() << "[通话]" << msg;
        emit errorOccurred(msg);
        delete m_audioSocket;
        m_audioSocket = nullptr;
        return false;
    }
    connect(m_audioSocket, &QUdpSocket::readyRead, this, &CallSession::onAudioDataReady);
    qInfo() << "[通话] 音频 UDP 监听端口" << protocol::kAudioPort;
    return true;
}

bool CallSession::startVideoSocket()
{
    if (m_videoSocket) {
        return true;
    }
    m_videoSocket = new QUdpSocket(this);
    if (!m_videoSocket->bind(QHostAddress::Any, protocol::kVideoPort,
                             QUdpSocket::ShareAddress)) {
        const QString msg = QStringLiteral("视频 UDP 端口 %1 监听失败: %2")
                                .arg(protocol::kVideoPort)
                                .arg(m_videoSocket->errorString());
        qWarning() << "[通话]" << msg;
        emit errorOccurred(msg);
        delete m_videoSocket;
        m_videoSocket = nullptr;
        return false;
    }
    connect(m_videoSocket, &QUdpSocket::readyRead, this, &CallSession::onVideoDataReady);
    qInfo() << "[通话] 视频 UDP 监听端口" << protocol::kVideoPort;
    return true;
}

void CallSession::startAudioOutput()
{
    const QAudioFormat format = pcmFormat();
    const int bytesPerMs = format.bytesPerFrame() * format.sampleRate() / 1000;

    if (m_audioOutput) {
        m_audioOutput->stop();
        delete m_audioOutput;
        m_audioOutput = nullptr;
    }
    m_audioOutput = new QAudioOutput(format, this);
    m_audioOutput->setBufferSize(bytesPerMs * 27);
    m_audioOutput->setNotifyInterval(1);
    m_audioDevice = m_audioOutput->start();
    if (!m_audioDevice) {
        qWarning() << "[通话] 音频输出启动失败:" << m_audioOutput->error();
    }
    m_audioBuffer.clear();
}

void CallSession::startAudioInput()
{
    const QAudioFormat format = pcmFormat();

    if (m_audioInput) {
        m_audioInput->stop();
        delete m_audioInput;
        m_audioInput = nullptr;
    }
    m_audioInput = new QAudioInput(format, this);
    m_audioInput->setBufferSize(protocol::kAudioFramesPerPacket);
    m_inputDevice = m_audioInput->start();
    if (!m_inputDevice) {
        qWarning() << "[通话] 音频输入启动失败:" << m_audioInput->error();
        return;
    }
    connect(m_inputDevice, &QIODevice::readyRead, this, &CallSession::onInputReady);
    m_inputBuffer.clear();
}

void CallSession::stop()
{
    if (m_audioSocket) {
        m_audioSocket->close();
        m_audioSocket->deleteLater();
        m_audioSocket = nullptr;
    }
    if (m_videoSocket) {
        m_videoSocket->close();
        m_videoSocket->deleteLater();
        m_videoSocket = nullptr;
    }
    if (m_audioOutput) {
        m_audioOutput->stop();
        delete m_audioOutput;
        m_audioOutput = nullptr;
    }
    if (m_audioInput) {
        m_audioInput->stop();
        delete m_audioInput;
        m_audioInput = nullptr;
    }
    m_audioDevice = nullptr;
    m_inputDevice = nullptr;
    m_audioBuffer.clear();
    m_inputBuffer.clear();
    m_deviceAddress.clear();
    m_devicePort = 0;
    m_running = false;
}

void CallSession::onAudioDataReady()
{
    if (!m_audioSocket) {
        return;
    }
    const int bytesPerMs = protocol::kAudioSampleRate
                           * protocol::kAudioChannels
                           * protocol::kAudioBytesPerSample / 1000;
    const int maxBufferBytes = kMaxAudioBufferMs * bytesPerMs;

    while (m_audioSocket->hasPendingDatagrams()) {
        QByteArray datagram;
        datagram.resize(static_cast<int>(m_audioSocket->pendingDatagramSize()));
        QHostAddress sender;
        quint16 senderPort = 0;
        m_audioSocket->readDatagram(datagram.data(), datagram.size(),
                                    &sender, &senderPort);

        // 只有收到过终端音频包，才知道回传目标地址。
        m_deviceAddress = sender;
        m_devicePort = senderPort;

        m_audioBuffer.append(datagram);
        if (m_audioBuffer.size() > maxBufferBytes) {
            m_audioBuffer.remove(0, m_audioBuffer.size() - maxBufferBytes);
        }
        writeAudioData();
    }
}

void CallSession::writeAudioData()
{
    if (!m_audioOutput || !m_audioDevice) {
        return;
    }
    while (!m_audioBuffer.isEmpty() && m_audioOutput->bytesFree() > 0) {
        const int chunk = qMin(m_audioBuffer.size(), m_audioOutput->bytesFree());
        const int written = m_audioDevice->write(m_audioBuffer.constData(), chunk);
        if (written > 0) {
            m_audioBuffer.remove(0, written);
        } else {
            break;
        }
    }
}

void CallSession::onInputReady()
{
    if (!m_inputDevice || !m_audioSocket) {
        return;
    }
    m_inputBuffer.append(m_inputDevice->readAll());

    while (m_inputBuffer.size() >= kAudioPacketBytes) {
        // 未学到目标地址前不发送，避免把语音发给未知主机。
        if (!m_deviceAddress.isNull() && m_devicePort != 0) {
            m_audioSocket->writeDatagram(m_inputBuffer.constData(), kAudioPacketBytes,
                                         m_deviceAddress, m_devicePort);
        }
        m_inputBuffer.remove(0, kAudioPacketBytes);
    }
}

void CallSession::onVideoDataReady()
{
    if (!m_videoSocket) {
        return;
    }
    while (m_videoSocket->hasPendingDatagrams()) {
        QByteArray datagram;
        datagram.resize(static_cast<int>(m_videoSocket->pendingDatagramSize()));
        m_videoSocket->readDatagram(datagram.data(), datagram.size());

        // 每包一帧完整 JPEG，直接解码。
        QImage image;
        if (image.loadFromData(datagram, "JPG") && !image.isNull()) {
            emit videoFrameReady(image);
        }
    }
}

} // namespace accessterminal
