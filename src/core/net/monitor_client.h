/**
 * @file monitor_client.h
 * @brief 远程监看客户端（UDP 50000）。
 *
 * 门口机不主动推帧；室内机先发 "getframe" 才开始收到 JPEG 帧，
 * 发 "stop" 则停止。每包为一帧完整 JPEG，不重组、不重传。
 */
#ifndef ACCESSTERMINAL_CORE_NET_MONITOR_CLIENT_H
#define ACCESSTERMINAL_CORE_NET_MONITOR_CLIENT_H

#include <QHostAddress>
#include <QObject>
#include <QPixmap>

class QUdpSocket;

namespace accessterminal {

class MonitorClient : public QObject
{
    Q_OBJECT

public:
    explicit MonitorClient(QObject* parent = nullptr);
    ~MonitorClient() override;

    /**
     * @brief 绑定本地监看端口并准备接收。
     * @return 成功返回 true。
     */
    bool start();

    /// 停止接收并释放 socket。
    void stop();

    /// 是否正在接收画面。
    bool isActive() const { return m_active; }

    /**
     * @brief 开始/停止监看（带设备地址）。
     * @param deviceIp 门口机地址。
     *
     * 首次调用发送 getframe 并进入接收态；
     * 再次调用发送 stop 并退出接收态。
     * @return 调用后是否处于接收态。
     */
    bool toggle(const QString& deviceIp);

signals:
    /// 收到一帧画面。
    void frameReceived(const QPixmap& frame);
    /// 接收态发生变化。
    void activeChanged(bool active);
    /// 错误提示。
    void errorOccurred(const QString& message);

private:
    void onReadyRead();
    bool ensureSocket();

    QUdpSocket* m_socket = nullptr;
    QHostAddress m_deviceAddress;
    bool m_active = false;
};

} // namespace accessterminal

#endif // ACCESSTERMINAL_CORE_NET_MONITOR_CLIENT_H
