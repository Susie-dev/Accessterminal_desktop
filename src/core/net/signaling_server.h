/**
 * @file signaling_server.h
 * @brief TCP 信令服务端（室内机侧）。
 *
 * 职责：监听信令端口、维护在线门口机连接、收发信令。
 * 不含任何 UI 依赖——收到的信令以信号形式抛出，由 UI 层决定如何响应。
 *
 * 协议（与门口机逐字节兼容）：
 *   门口机 → 室内机 : call / stopsend / unlock
 *   室内机 → 门口机 : accept / recstop / unlock
 *   文本行，UTF-8，'\n' 结束。
 */
#ifndef ACCESSTERMINAL_CORE_NET_SIGNALING_SERVER_H
#define ACCESSTERMINAL_CORE_NET_SIGNALING_SERVER_H

#include <QObject>
#include <QHash>
#include <QSet>

#include "core/net/protocol.h"

class QTcpServer;
class QTcpSocket;

namespace accessterminal {

class SignalingServer : public QObject
{
    Q_OBJECT

public:
    explicit SignalingServer(QObject* parent = nullptr);
    ~SignalingServer() override;

    /**
     * @brief 开始监听。
     * @param port 监听端口，默认使用协议约定的 8887。
     * @return 成功返回 true。
     */
    bool listen(quint16 port = protocol::kSignalingPort);

    /// 停止监听并断开所有客户端。
    void stop();

    /// 是否正在监听。
    bool isListening() const;

    /// 当前在线客户端数量。
    int clientCount() const { return m_clients.size(); }

    /**
     * @brief 向触发本次信令的那个客户端回复。
     * @param client 目标连接；为空或已断开时返回 false。
     * @param signal 要发送的信令。
     */
    bool reply(QTcpSocket* client, protocol::Signal signal);

    /**
     * @brief 向所有在线客户端广播信令（用于远程开锁）。
     * @return 成功发送的客户端数量。
     */
    int broadcast(protocol::Signal signal);

signals:
    /// 收到门口机信令。client 为来源连接，供 reply() 回执使用。
    void signalReceived(accessterminal::protocol::Signal signal, QTcpSocket* client);

    /// 新客户端接入。
    void clientConnected(const QString& peerAddress);

    /// 客户端断开。
    void clientDisconnected(const QString& peerAddress);

    /// 服务端错误（监听失败等）。
    void errorOccurred(const QString& message);

private:
    void onNewConnection();
    void onClientReadyRead(QTcpSocket* client);
    void onClientDisconnected(QTcpSocket* client);

    QTcpServer* m_server = nullptr;
    QSet<QTcpSocket*> m_clients;

    /// 每个连接各自的字节流解码器。
    /// 必须按连接区分：TCP 半包是**连接级**状态，若所有连接共用一个
    /// 解码器，多个门口机交错到达的半包会互相拼接成错误信令。
    QHash<QTcpSocket*, protocol::StreamDecoder> m_decoders;
};

} // namespace accessterminal

#endif // ACCESSTERMINAL_CORE_NET_SIGNALING_SERVER_H
