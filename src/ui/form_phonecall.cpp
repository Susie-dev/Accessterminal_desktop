/**
 * @file form_phonecall.cpp
 * @brief 来电/通话浮层实现。
 *
 * 界面交互逻辑保持与重构前逐像素一致；音视频收发委托给 CallSession。
 */
#include "ui/form_phonecall.h"
#include "ui_form_phonecall.h"

#include "config/app_config.h"
#include "ui/slidehintwidget.h"

#include <QCloseEvent>
#include <QDebug>
#include <QMediaPlayer>
#include <QPixmap>
#include <QPushButton>
#include <QUrl>
#include <QImage>

using accessterminal::AppConfig;

Form_phonecall::Form_phonecall(QWidget* parent, bool playRing)
    : QWidget(parent)
    , ui(new Ui::Form_phonecall)
{
    // 透明背景、无边框、不作为任务栏窗口。
    setWindowFlags(windowFlags() | Qt::FramelessWindowHint | Qt::Tool);
    setAttribute(Qt::WA_TranslucentBackground, true);

    ui->setupUi(this);

    // ---- 接听滑块 ----
    ui->label_slider->installEventFilter(this);
    ui->label_slider->setAttribute(Qt::WA_TransparentForMouseEvents, false);
    ui->label_slider->setEnabled(true);
    ui->label_slider->raise();

    if (ui->label_image) {
        ui->label_image->setVisible(false);
    }

    // 流光引导效果。
    hint = new SlideHintWidget(ui->widget_slider_area);
    hint->setGeometry(ui->widget_slider_area->rect());
    hint->show();
    ui->label_slider->raise(); // 滑块需位于流光之上

    // ---- 挂断按钮（动态创建，接通后才显示）----
    btn_hangup = new QPushButton(ui->widget_slider_area->parentWidget());
    btn_hangup->setVisible(false);
    btn_hangup->setFixedSize(64, 64);
    btn_hangup->setStyleSheet(QStringLiteral(
        "QPushButton {"
        " border: none;"
        " background: transparent;"
        " border-image: url(:/pic/hangup.png) 0 0 0 0 stretch stretch;"
        "}"
        "QPushButton:pressed {"
        " opacity: 0.7;"
        "}"));
    btn_hangup->setCursor(Qt::PointingHandCursor);
    connect(btn_hangup, &QPushButton::clicked, this, [this]() {
        qDebug() << "[通话] 挂断按钮点击";
        emit hangupClicked();
        close();
    });

    // ---- 门铃音循环 ----
    if (playRing) {
        const AppConfig& cfg = AppConfig::instance();
        ringPlayer = new QMediaPlayer(this);
        ringPlayer->setMedia(QUrl(cfg.ringtonePath()));
        ringPlayer->setVolume(cfg.ringtoneVolume());
        ringPlayer->play();
        // 播放结束后重新播放，实现门铃音循环（沿用重构前的行为）。
        connect(ringPlayer, &QMediaPlayer::stateChanged, this,
                [this](QMediaPlayer::State state) {
                    if (state == QMediaPlayer::StoppedState && ringPlayer) {
                        ringPlayer->play();
                    }
                });
    }
}

Form_phonecall::~Form_phonecall()
{
    delete session;
    session = nullptr;
    stopRing();
    delete ui;
}

void Form_phonecall::closeEvent(QCloseEvent* event)
{
    if (session) {
        session->stop();
    }
    QWidget::closeEvent(event);
}

void Form_phonecall::stopRing()
{
    if (ringPlayer) {
        ringPlayer->stop();
        ringPlayer->deleteLater();
        ringPlayer = nullptr;
    }
}

bool Form_phonecall::eventFilter(QObject* watched, QEvent* event)
{
    if (watched != ui->label_slider) {
        return QWidget::eventFilter(watched, event);
    }

    if (event->type() == QEvent::MouseButtonPress) {
        auto* mouseEvent = static_cast<QMouseEvent*>(event);
        dragging = true;
        dragOffset = mouseEvent->pos().x();
        return true;
    }

    if (event->type() == QEvent::MouseMove) {
        if (dragging) {
            auto* mouseEvent = static_cast<QMouseEvent*>(event);
            int newX = ui->label_slider->x() + mouseEvent->pos().x() - dragOffset;
            newX = qBound(0, newX,
                          ui->widget_slider_area->width() - ui->label_slider->width());
            ui->label_slider->move(newX, ui->label_slider->y());
        }
        return true;
    }

    if (event->type() == QEvent::MouseButtonRelease) {
        if (dragging) {
            dragging = false;
            // 拖到最右（留 10px 容差）视为接听。
            const int threshold =
                ui->widget_slider_area->width() - ui->label_slider->width() - 10;
            if (ui->label_slider->x() > threshold) {
                engageCall();
            } else {
                // 未到底：滑块弹回起点。
                ui->label_slider->move(0, ui->label_slider->y());
                if (ui->label_image) {
                    ui->label_image->setVisible(false);
                }
            }
            ui->label_slider->raise();
        }
        return true;
    }

    return QWidget::eventFilter(watched, event);
}

void Form_phonecall::engageCall()
{
    if (ui->label_image) {
        ui->label_image->setVisible(true);
    }
    stopRing();

    // 建立音视频通道；画面通过信号回送到本窗口显示。
    if (!session) {
        session = new accessterminal::CallSession(this);
        connect(session, &accessterminal::CallSession::videoFrameReady,
                this, &Form_phonecall::onVideoFrameReady);
    }
    session->start();

    emit accepted();
    emit answered();

    // 隐藏接听控件，显示挂断按钮。
    ui->label_slider->setVisible(false);
    ui->widget_slider_area->setVisible(false);
    if (hint) {
        hint->setVisible(false);
    }

    const QSize btnSize(64, 64);
    const QRect areaRect = ui->widget_slider_area->geometry();
    const int btnX = areaRect.left() + (areaRect.width() - btnSize.width()) / 2;
    const int btnY = areaRect.top() + (areaRect.height() - btnSize.height()) / 2;
    btn_hangup->move(btnX, btnY);
    btn_hangup->setVisible(true);
    btn_hangup->raise();
}

void Form_phonecall::onVideoFrameReady(const QImage& frame)
{
    if (frame.isNull() || !ui->label_image) {
        return;
    }
    // 等比放大后居中裁剪到 label 尺寸（与重构前一致）。
    const QPixmap pix = QPixmap::fromImage(frame).scaled(
        ui->label_image->size(), Qt::KeepAspectRatioByExpanding,
        Qt::SmoothTransformation);
    const QRect targetRect((pix.width() - ui->label_image->width()) / 2,
                           (pix.height() - ui->label_image->height()) / 2,
                           ui->label_image->width(),
                           ui->label_image->height());
    ui->label_image->setPixmap(pix.copy(targetRect));
}
