/**
 * @file form_phonecall.h
 * @brief 来电/通话浮层。
 *
 * 重构说明：原实现把界面交互与音视频收发混在同一个类里（575 行）。
 * 现拆为两部分：
 *   - 本类       : 滑块接听交互、挂断按钮、门铃音、画面与状态显示
 *   - CallSession: UDP 12345 双向音频、UDP 23456 单向视频
 *
 * 对外行为不变：滑到最右触发 accepted/answered，挂断触发 hangupClicked。
 */
#ifndef FORM_PHONECALL_H
#define FORM_PHONECALL_H

#include <QImage>
#include <QMouseEvent>
#include <QWidget>

#include "core/media/call_session.h"

class QMediaPlayer;
class QPushButton;
class SlideHintWidget;

namespace Ui {
class Form_phonecall;
}

class Form_phonecall : public QWidget
{
    Q_OBJECT

public:
    explicit Form_phonecall(QWidget* parent = nullptr, bool playRing = true);
    ~Form_phonecall() override;

signals:
    void answered();
    void accepted();
    void hangupClicked();

protected:
    bool eventFilter(QObject* watched, QEvent* event) override;
    void closeEvent(QCloseEvent* event) override;

private slots:
    void onVideoFrameReady(const QImage& frame);

private:
    /// 建立音视频通道并切换到"通话中"界面。
    void engageCall();
    /// 停止门铃音。
    void stopRing();

    Ui::Form_phonecall* ui = nullptr;

    // 滑块拖拽状态
    bool dragging = false;
    int dragOffset = 0;

    // 通话通道（仅在接通后启动）
    accessterminal::CallSession* session = nullptr;

    QPushButton* btn_hangup = nullptr;
    SlideHintWidget* hint = nullptr;
    QMediaPlayer* ringPlayer = nullptr;
};

#endif // FORM_PHONECALL_H
