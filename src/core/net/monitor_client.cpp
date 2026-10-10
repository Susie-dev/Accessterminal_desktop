/**
 * @file monitor_client.cpp
 * @brief MonitorClient 实现。
 */
#include "core/net/monitor_client.h"

#include "core/net/protocol.h"

#include <QDebug>
#include <QUdpSocket>
#include <QPixmap>

namespace accessterminal {

namespace {
/// 远程监看使用的请求文本，与门口机一致。
const QByteArray kGetFrame = QByteArrayLiteral("getframe");
const QByteArray kStop = QByteArrayLiteral("stop");
} // namespace

MonitorClient::MonitorClient(QObject* parent)
    : QObject(parent)
{
}

MonitorClient::~MonitorClient()
{
    stop();
}

bool MonitorClient::ensureSocket()
{
    if (m_socket) {
        return true;
    }
    m_socket = new QUdpSocket(this);
    if (!m_socket->bind(QHostAddress::Any, protocol::kPreviewPort,
                        QUdpSocket::ShareAddress | QUdpSocket::ReuseAddressHint)) {
        const QString msg = QStringLiteral("监看端口 %1 绑定失败: %2")
                                .arg(protocol::kPreviewPort)
                                .arg(m_socket->errorString());
        qWarning() << "[监看]" << msg;
        emit errorOccurred(msg);
        delete m_socket;
        m_socket = nullptr;
        return false;
    }
    connect(m_socket, &QUdpSocket::readyRead, this, &MonitorClient::onReadyRead);
    qInfo() << "[监看] 已绑定 UDP 端口" << protocol::kPreviewPort;
    return true;
}

bool MonitorClient::start()
{
    return ensureSocket();
}

void MonitorClient::stop()
{
    if (m_socket) {
        m_socket->close();
        m_socket->deleteLater();
        m_socket = nullptr;
    }
    if (m_active) {
        m_active = false;
        emit activeChanged(false);
    }
}

bool MonitorClient::toggle(const QString& deviceIp)
{
    if (!ensureSocket()) {
        return false;
    }
    m_deviceAddress = QHostAddress(deviceIp);

    if (!m_active) {
        m_socket->writeDatagram(kGetFrame, m_deviceAddress, protocol::kPreviewPort);
        qDebug() << "[监看] 已发送 getframe 到" << deviceIp;
        m_active = true;
    } else {
        m_socket->writeDatagram(kStop, m_deviceAddress, protocol::kPreviewPort);
        qDebug() << "[监看] 已发送 stop 到" << deviceIp;
        m_active = false;
    }
    emit activeChanged(m_active);
    return m_active;
}

void MonitorClient::onReadyRead()
{
    if (!m_socket) {
        return;
    }
    while (m_socket->hasPendingDatagrams()) {
        QByteArray datagram;
        datagram.resize(static_cast<int>(m_socket->pendingDatagramSize()));
        m_socket->readDatagram(datagram.data(), datagram.size());

        // 每包即一帧完整 JPEG。
        QPixmap pix;
        if (pix.loadFromData(datagram, "JPG") && !pix.isNull()) {
            emit frameReceived(pix);
        }
    }
}

} // namespace accessterminal
