/**
 * @file widget.cpp
 * @brief 室内机主界面实现。
 *
 * 仅做界面装配与事件编排；网络、串口、天气逻辑均委托给独立模块。
 * 界面行为（样式、动画、文案、坐标）与重构前保持一致。
 */
#include "ui/widget.h"
#include "ui_widget.h"

#include "config/app_config.h"
#include "core/net/monitor_client.h"
#include "core/net/signaling_server.h"
#include "core/weather/weather_service.h"
#include "hal/serial_light.h"
#include "ui/form_phonecall.h"

#include <QDateTime>
#include <QDebug>
#include <QGraphicsOpacityEffect>
#include <QParallelAnimationGroup>
#include <QPainterPath>
#include <QPropertyAnimation>
#include <QRegion>
#include <QTcpSocket>
#include <QTimer>

using accessterminal::AppConfig;
using accessterminal::MonitorClient;
using accessterminal::SerialLight;
using accessterminal::SignalingServer;
using accessterminal::WeatherService;

namespace {

/// 摄像头浮出动画时长。
constexpr int kCameraAnimMs = 1000;
/// 屏幕开关渐变时长。
constexpr int kScreenFadeMs = 500;
/// 接听滑块距右边的判定容差。
constexpr int kSlideTolerance = 10;
/// 界面背景图（与重构前一致）。
const char* const kBackgroundImage = ":/pic/smartbg.png";

} // namespace

Widget::Widget(QWidget* parent)
    : QWidget(parent)
    , ui(new Ui::Widget)
{
    ui->setupUi(this);

    setWindowFlags(Qt::FramelessWindowHint);

    // 圆角窗口：半径与重构前一致。
    const int radius = 10;
    QPainterPath path;
    path.addRoundedRect(rect(), radius, radius);
    setMask(QRegion(path.toFillPolygon().toPolygon()));

    // label_off 渐显渐隐效果初始化。
    auto* opacityEffect = new QGraphicsOpacityEffect(this);
    opacityEffect->setOpacity(0.0);
    ui->label_off->setGraphicsEffect(opacityEffect);
    ui->label_off->setVisible(false);

    ui->widget_light->setVisible(false);

    // 系统时间。
    m_sysTimeTimer = new QTimer(this);
    connect(m_sysTimeTimer, &QTimer::timeout, this, &Widget::time_reflash);
    m_sysTimeTimer->start(1000);
    time_reflash();

    setupModules();
}

Widget::~Widget()
{
    // 通话浮层是无父窗口的顶层窗口，需显式关闭，避免残留窗口与
    // 音频设备句柄。close() 会因 WA_DeleteOnClose 自动销毁对象。
    destroyCallForm();
    delete ui;
}

void Widget::setupModules()
{
    const AppConfig& cfg = AppConfig::instance();

    // ---- 信令服务端（TCP，门口机主动连接）----
    m_signaling = new SignalingServer(this);
    connect(m_signaling, &SignalingServer::signalReceived,
            this, &Widget::onSignalReceived);
    connect(m_signaling, &SignalingServer::clientConnected, this,
            [](const QString& peer) { qInfo() << "[信令] 在线门口机:" << peer; });
    connect(m_signaling, &SignalingServer::errorOccurred, this,
            [](const QString& msg) { qWarning() << "[信令]" << msg; });

    if (!m_signaling->listen(cfg.signalingPort())) {
        qWarning() << "[信令] 监听失败，通话功能不可用";
    } else {
        qInfo() << "[网络配置] 本机:" << cfg.selfIp() << "门口机:" << cfg.deviceIp();
    }

    // ---- 远程监看客户端（UDP 50000）----
    m_monitor = new MonitorClient(this);
    connect(m_monitor, &MonitorClient::frameReceived,
            this, &Widget::onVideoFrameReady);
    connect(m_monitor, &MonitorClient::errorOccurred, this,
            [](const QString& msg) { qWarning() << "[监看]" << msg; });

    // ---- 灯控串口 ----
    m_light = new SerialLight(this);
    connect(m_light, &SerialLight::errorOccurred, this,
            [](const QString& msg) { qWarning() << "[灯控]" << msg; });
    m_light->open(cfg.serialPortName());

    // ---- 天气 ----
    m_weather = new WeatherService(this);
    connect(m_weather, &WeatherService::weatherUpdated, this,
            [this](const QString& text) {
                if (ui->label_weather) {
                    ui->label_weather->setText(text);
                }
            });
    connect(m_weather, &WeatherService::errorOccurred, this,
            [](const QString& msg) { qWarning() << "[天气]" << msg; });
    m_weather->refresh();
}

// ============================================================================
// 电源与离线状态
// ============================================================================

void Widget::on_btn_power_clicked()
{
    // 屏幕开关：黑屏 / 还原背景图，与重构前一致。
    if (!m_screenOff) {
        ui->widget_main->setStyleSheet(QStringLiteral(
            "#widget_main {"
            "background-color: black;"
            "border-image: none;"
            "}"));
    } else {
        ui->widget_main->setStyleSheet(
            QStringLiteral("#widget_main {"
                           "background-color: rgb(255, 255, 255);"
                           "border-image: url(%1);"
                           "}")
                .arg(QString::fromLatin1(kBackgroundImage)));
    }
    m_screenOff = !m_screenOff;
}

void Widget::on_btn_offline_clicked()
{
    auto* effect =
        qobject_cast<QGraphicsOpacityEffect*>(ui->label_off->graphicsEffect());
    if (!effect) {
        return;
    }

    auto* animation = new QPropertyAnimation(effect, "opacity", this);
    animation->setDuration(kScreenFadeMs);

    if (!ui->label_off->isVisible()) {
        ui->label_off->setVisible(true);
        animation->setStartValue(0.0);
        animation->setEndValue(1.0);
    } else {
        animation->setStartValue(1.0);
        animation->setEndValue(0.0);
        connect(animation, &QPropertyAnimation::finished, this,
                [this]() { ui->label_off->setVisible(false); });
    }
    animation->start(QAbstractAnimation::DeleteWhenStopped);
}

// ============================================================================
// 时间显示
// ============================================================================

void Widget::time_reflash()
{
    const QDateTime now = QDateTime::currentDateTime();
    const QString date =
        now.date().toString(QStringLiteral("yyyy-MM-dd"));
    const QString time =
        now.time().toString(QStringLiteral("HH:mm:ss"));

    if (ui->labelDate) {
        ui->labelDate->setText(date);
    }
    if (ui->labelTime_2) {
        ui->labelTime_2->setText(time);
    }
}

// ============================================================================
// 信令处理
// ============================================================================

void Widget::onSignalReceived(accessterminal::protocol::Signal signal,
                              QTcpSocket* client)
{
    switch (signal) {
    case accessterminal::protocol::Signal::Call:
        handleCall(client);
        break;
    case accessterminal::protocol::Signal::StopSend:
        qInfo() << "[信令] 收到 stopsend，关闭通话窗口";
        handleStopSend();
        break;
    case accessterminal::protocol::Signal::Unlock:
        // 门口机请求开锁：室内机侧暂无本地动作（保留原有空实现）。
        qInfo() << "[信令] 收到 unlock";
        break;
    default:
        // accept/recstop/getframe/stop 不是门口机应有的上行信令。
        qWarning() << "[信令] 忽略非预期信令";
        break;
    }
}

void Widget::handleCall(QTcpSocket* client)
{
    // 离线状态下不响铃（与重构前一致）。
    const bool playRing = !ui->label_off->isVisible();

    // 记录本次呼叫的连接，供 accepted/hangupClicked 回执使用。
    // QPointer 在连接被销毁后自动变空，避免悬垂指针。
    m_callClient = client;

    if (m_callForm) {
        return; // 通话窗口已存在，不重复弹出
    }

    m_callForm = new Form_phonecall(nullptr, playRing); // 顶层窗口
    m_callForm->setAttribute(Qt::WA_DeleteOnClose);

    // 只在创建时连接一次，后续来电只更新 m_callClient。
    connect(m_callForm, &Form_phonecall::accepted, this, [this]() {
        if (m_callClient) {
            m_signaling->reply(m_callClient, accessterminal::protocol::Signal::Accept);
        }
    });
    connect(m_callForm, &Form_phonecall::hangupClicked, this, [this]() {
        if (m_callClient) {
            m_signaling->reply(m_callClient, accessterminal::protocol::Signal::RecStop);
        }
    });
    connect(m_callForm, &QObject::destroyed, this, [this]() {
        m_callForm = nullptr;
        m_callClient = nullptr;
    });

    m_callForm->show();
    centerOnMain(m_callForm);
}

void Widget::handleStopSend()
{
    destroyCallForm();
}

void Widget::destroyCallForm()
{
    if (m_callForm) {
        // WA_DeleteOnClose 已设置，close() 会触发 destroyed 并清空指针。
        m_callForm->close();
    }
}

void Widget::centerOnMain(QWidget* window)
{
    if (!window) {
        return;
    }
    const QRect mainRect = ui->widget_main->geometry();
    const QPoint globalTopLeft = ui->widget_main->mapToGlobal(mainRect.topLeft());
    const QRect globalRect(globalTopLeft, mainRect.size());
    const QSize size = window->size();
    const QPoint center = globalRect.center();
    window->move(center.x() - size.width() / 2, center.y() - size.height() / 2);
}

// ============================================================================
// 门锁与灯控
// ============================================================================

void Widget::on_btn_lock_clicked()
{
    // 广播开锁给所有在线门口机。
    const int sent = m_signaling->broadcast(accessterminal::protocol::Signal::Unlock);
    qInfo() << "[开锁] unlock 已发送到" << sent << "台门口机";
}

void Widget::on_btn_home_clicked()
{
    // 灯光控制面板显隐。
    ui->widget_light->setVisible(!ui->widget_light->isVisible());
}

void Widget::on_btn_tea_clicked()
{
    m_light->sendCommand(QStringLiteral("desk_round"));
}

void Widget::on_btn_teab_clicked()
{
    m_light->sendCommand(QStringLiteral("work_round"));
}

void Widget::on_btn_white_clicked()
{
    m_light->sendCommand(QStringLiteral("desk"));
}

// ============================================================================
// 远程监看
// ============================================================================

void Widget::on_btngetframe_clicked()
{
    m_cameraActive = m_monitor->toggle(AppConfig::instance().deviceIp());

    if (!m_cameraActive) {
        // 停止监看：立即隐藏画面，避免保留最后一帧造成误解。
        ui->labelcam->setVisible(false);
    }
    // 无论开关，下次出现时都重新播放"由小放大 + 淡入"动画。
    m_cameraFirstShow = true;
}

void Widget::onVideoFrameReady(const QPixmap& frame)
{
    if (frame.isNull() || !m_cameraActive) {
        return;
    }
    showCameraFrame(frame);
}

void Widget::showCameraFrame(const QPixmap& frame)
{
    // 首次出现时播放"由小放大 + 淡入"动画。
    if (m_cameraFirstShow || !ui->labelcam->isVisible()) {
        const QRect endRect = ui->labelcam->geometry();
        QRect startRect = endRect;
        startRect.setWidth(static_cast<int>(endRect.width() * 0.2));
        startRect.setHeight(static_cast<int>(endRect.height() * 0.2));
        startRect.moveCenter(endRect.center());
        ui->labelcam->setGeometry(startRect);
        ui->labelcam->setVisible(true);

        auto* effect = new QGraphicsOpacityEffect(ui->labelcam);
        ui->labelcam->setGraphicsEffect(effect);
        effect->setOpacity(0.0);

        auto* opacityAnim = new QPropertyAnimation(effect, "opacity");
        opacityAnim->setDuration(kCameraAnimMs);
        opacityAnim->setStartValue(0.0);
        opacityAnim->setEndValue(1.0);

        auto* scaleAnim =
            new QPropertyAnimation(ui->labelcam, "geometry");
        scaleAnim->setDuration(kCameraAnimMs);
        scaleAnim->setStartValue(startRect);
        scaleAnim->setEndValue(endRect);
        scaleAnim->setEasingCurve(QEasingCurve::OutElastic);

        auto* group = new QParallelAnimationGroup(this);
        group->addAnimation(opacityAnim);
        group->addAnimation(scaleAnim);
        group->start(QAbstractAnimation::DeleteWhenStopped);

        m_cameraFirstShow = false;
    }

    ui->labelcam->setPixmap(frame.scaled(ui->labelcam->size(),
                                         Qt::KeepAspectRatio,
                                         Qt::SmoothTransformation));
}
