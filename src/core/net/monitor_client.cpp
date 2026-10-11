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
    // 退出接收态前**先通知门口机**。
    //
    // 门口机侧（CameraUdpServer）只有在收到 `stop` 时才会
    // `sendTimer->stop()`；仅仅关掉本地 socket 对它**不可观测** —— 它会继续
    // 按 50ms（20fps）的定时器朝这个已经消失的地址推 JPEG，直到进程结束。
    // 这正是《交接与继续开发》第 1.3 条要求的「发 stop 关掉远程监看」。
    //
    // 为什么必须放在这里、而不是只在按钮回调里：室内机退出时走的是
    // Widget 析构 → MonitorClient（子对象）析构 → stop()。若 stop() 不发，
    // 「用户在监看中途直接关掉程序」这条路径就会让门口机推流线程永久空转。
    // 之前这里**恰恰没有发** —— 交接文档却写着"重构版已修正这一点"，
    // 属于文档与实现不一致，由本注释与
    // test_monitor_client.cpp 的 stopWhenActiveNotifiesTerminal 钉住。
    //
    // 只在**确实处于接收态**时发：没发过 getframe 就发 stop 是无意义的
    // 多余信令。m_active 为 true 意味着 toggle() 已经成功绑定并记下地址。
    if (m_active && m_socket) {
        m_socket->writeDatagram(kStop, m_deviceAddress, protocol::kPreviewPort);
        qDebug() << "[监看] 已发送 stop 到" << m_deviceAddress.toString()
                 << "（通知门口机停止推流）";
    }

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

        // 不能忽略 readDatagram 的返回值：QByteArray::resize() 不会清零
        // 新分配的内存。若实际读到的字节数少于 pendingDatagramSize()，
        // 尾部就是未初始化字节（或上一次循环的残留），直接交给
        // loadFromData() 会解析到垃圾数据。
        // 正常情况下返回值等于 datagram.size()，行为与重构前一致。
        // 与门口机 camera_preview_server.cpp 的处理保持对称。
        const qint64 bytesRead = m_socket->readDatagram(datagram.data(), datagram.size());
        if (bytesRead < 0) {
            continue; // 读取失败，丢弃该数据报
        }
        if (bytesRead < datagram.size()) {
            datagram.resize(static_cast<int>(bytesRead));
        }

        // 每包即一帧完整 JPEG。
        QPixmap pix;
        if (pix.loadFromData(datagram, "JPG") && !pix.isNull()) {
            emit frameReceived(pix);
        }
    }
}

} // namespace accessterminal
