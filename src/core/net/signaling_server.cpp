/**
 * @file signaling_server.cpp
 * @brief SignalingServer 实现。
 */
#include "core/net/signaling_server.h"

#include <QDebug>
#include <QHostAddress>
#include <QTcpServer>
#include <QTcpSocket>

namespace accessterminal {

SignalingServer::SignalingServer(QObject* parent)
    : QObject(parent)
{
    m_server = new QTcpServer(this);
    connect(m_server, &QTcpServer::newConnection, this, &SignalingServer::onNewConnection);
}

SignalingServer::~SignalingServer()
{
    stop();
}

bool SignalingServer::listen(quint16 port)
{
    if (m_server->isListening()) {
        return true;
    }
    if (!m_server->listen(QHostAddress::Any, port)) {
        const QString msg = QStringLiteral("TCP 信令监听 %1 失败: %2")
                                .arg(port)
                                .arg(m_server->errorString());
        qWarning() << "[信令]" << msg;
        emit errorOccurred(msg);
        return false;
    }
    qInfo() << "[信令] 服务端监听端口" << port;
    return true;
}

void SignalingServer::stop()
{
    for (QTcpSocket* client : m_clients) {
        if (client) {
            client->disconnect(this);
            client->abort();
            client->deleteLater();
        }
    }
    m_clients.clear();
    if (m_server->isListening()) {
        m_server->close();
    }
}

bool SignalingServer::isListening() const
{
    return m_server->isListening();
}

bool SignalingServer::reply(QTcpSocket* client, protocol::Signal signal)
{
    if (!client || client->state() != QAbstractSocket::ConnectedState) {
        qWarning() << "[信令] 回执失败：连接不可用";
        return false;
    }
    const QByteArray payload = protocol::frame(signal);
    if (payload.isEmpty()) {
        qWarning() << "[信令] 拒绝发送未知信令";
        return false;
    }
    const qint64 written = client->write(payload);
    client->flush();
    qDebug() << "[信令] 已发送:" << payload.trimmed();
    return written == payload.size();
}

int SignalingServer::broadcast(protocol::Signal signal)
{
    const QByteArray payload = protocol::frame(signal);
    if (payload.isEmpty()) {
        qWarning() << "[信令] 拒绝广播未知信令";
        return 0;
    }
    int sent = 0;
    for (QTcpSocket* client : m_clients) {
        if (client && client->state() == QAbstractSocket::ConnectedState) {
            client->write(payload);
            client->flush();
            ++sent;
            qDebug() << "[信令] 已广播" << payload.trimmed() << "到" << client;
        }
    }
    return sent;
}

void SignalingServer::onNewConnection()
{
    while (m_server->hasPendingConnections()) {
        QTcpSocket* client = m_server->nextPendingConnection();
        m_clients.insert(client);
        const QString peer = client->peerAddress().toString();

        connect(client, &QTcpSocket::readyRead, this,
                [this, client]() { onClientReadyRead(client); });
        connect(client, &QTcpSocket::disconnected, this,
                [this, client]() { onClientDisconnected(client); });

        qInfo() << "[信令] 门口机接入:" << peer;
        emit clientConnected(peer);
    }
}

void SignalingServer::onClientReadyRead(QTcpSocket* client)
{
    const QByteArray data = client->readAll();
    qDebug() << "[信令] 收到数据来自" << client << ":" << data;

    // TCP 是字节流：一次 readAll 可能含多条 '\n' 分隔的信令，也可能
    // 只有半条。交给 protocol::StreamDecoder 做跨包重组——它既修掉了
    // 旧版“半包会被静默丢弃”的缺陷，又保留了旧版对无 '\n' 结尾信令
    // （如历史遗留的 "recstop"）的宽容语义。
    // 解码器按连接区分，见 QHash<QTcpSocket*, StreamDecoder> m_decoders。
    // 注意：局部变量不能叫 signals —— Qt 把 signals 定义成了宏
    // （#define signals public），用它会直接把类体语法打乱。
    const QList<protocol::Signal> decoded = m_decoders[client].feed(data);
    for (const protocol::Signal sig : decoded) {
        // 门口机不应发 accept/recstop/getframe/stop，收到也交由 UI 判定。
        emit signalReceived(sig, client);
    }
}

void SignalingServer::onClientDisconnected(QTcpSocket* client)
{
    const QString peer = client ? client->peerAddress().toString() : QString();
    m_clients.remove(client);
    // 该连接的解码器一并清理：QTcpSocket 指针在 deleteLater 之后会被
    // 复用，留着陈旧的半包可能被下一个连接的字节“续上”。
    m_decoders.remove(client);
    if (client) {
        client->deleteLater();
    }
    qInfo() << "[信令] 门口机断开:" << peer;
    emit clientDisconnected(peer);
}

} // namespace accessterminal
