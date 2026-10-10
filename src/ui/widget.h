/**
 * @file widget.h
 * @brief 室内机主界面：只负责 UI 装配与交互编排。
 *
 * 重构说明：原实现把网络、串口、天气、灯控、动画全部塞进 Widget（718 行）。
 * 现按职责拆分，Widget 仅保留界面控件操作与模块间编排：
 *   - 信令服务   -> core/net/SignalingServer
 *   - 远程监看   -> core/net/MonitorClient
 *   - 通话音视频 -> core/media/CallSession（由 Form_phonecall 持有）
 *   - 灯控串口   -> hal/SerialLight
 *   - 天气       -> core/weather/WeatherService
 *   - 参数       -> config/AppConfig
 */
#ifndef WIDGET_H
#define WIDGET_H

#include <QPointer>
#include <QSet>
#include <QTcpSocket>
#include <QTimer>
#include <QWidget>

#include "core/net/protocol.h"
class QPixmap;

namespace Ui {
class Widget;
}

class Form_phonecall;

namespace accessterminal {
class MonitorClient;
class SerialLight;
class SignalingServer;
class WeatherService;
} // namespace accessterminal

class Widget : public QWidget
{
    Q_OBJECT

public:
    explicit Widget(QWidget* parent = nullptr);
    ~Widget() override;

private slots:
    // ---- 主界面按钮（名称由 .ui 自动连接决定，不可重命名）----
    void on_btn_power_clicked();
    void on_btn_offline_clicked();
    void on_btngetframe_clicked();
    void on_btn_lock_clicked();
    void on_btn_home_clicked();
    void on_btn_tea_clicked();
    void on_btn_teab_clicked();
    void on_btn_white_clicked();

    // ---- 定时与网络回调 ----
    void time_reflash();
    void onSignalReceived(accessterminal::protocol::Signal signal, QTcpSocket* client);
    void onVideoFrameReady(const QPixmap& frame);

private:
    /// 装配网络、串口、天气等模块并连接信号。
    void setupModules();

    /// 处理门口机的 call 信令：弹出通话浮层并连接其信号。
    void handleCall(QTcpSocket* client);
    /// 处理 stopsend 信令：关闭通话浮层。
    void handleStopSend();
    /// 关闭并销毁通话浮层。
    void destroyCallForm();

    /// 以 widget_main 为参照把浮层居中。
    void centerOnMain(QWidget* window);

    /// 切换 labelcam 的显示/隐藏（含首次出现的动画）。
    void showCameraFrame(const QPixmap& frame);

    Ui::Widget* ui = nullptr;

    // ---- 模块 ----
    accessterminal::SignalingServer* m_signaling = nullptr;
    accessterminal::MonitorClient* m_monitor = nullptr;
    accessterminal::SerialLight* m_light = nullptr;
    accessterminal::WeatherService* m_weather = nullptr;

    // ---- 状态 ----
    bool m_screenOff = false;
    bool m_cameraActive = false;
    bool m_cameraFirstShow = true;
    Form_phonecall* m_callForm = nullptr;
    /// 触发当前呼叫的门口机连接；连接断开后自动置空。
    QPointer<QTcpSocket> m_callClient;
    QTimer* m_sysTimeTimer = nullptr;
};

#endif // WIDGET_H
