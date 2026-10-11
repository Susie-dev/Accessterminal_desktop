/**
 * @file call_session.h
 * @brief **测试专用**的 `core/media/call_session.h` 影子头。
 *
 * 命名为真头的名字（`core/media/call_session.h`），用
 * `target_include_directories(... BEFORE PRIVATE ...)` 插到真头之前命中。
 *
 * 为什么必须替掉
 * --------------
 * `ui/form_phonecall.h` 会 `#include "core/media/call_session.h"`。真头把
 * 音频/视频 socket 与声卡（QAudioInput/QAudioOutput）都摆进类里；本测试要验
 * 的是**通话浮层的交互编排**（接通要 start、挂断/关闭要 stop、视频帧要显示），
 * 不是音视频通道本身 —— 后者已由 `desktop_test_call_session`（33 个用例）
 * 用真实 socket + 声卡替身单独覆盖。
 *
 * 用替身还带来两个好处：
 *   1. 浮层测试**不占用** UDP 12345 / 23456，可与其它目标并行跑；
 *   2. 可以精确构造"门口机送来一帧"这一事件（真实路径需要发 JPEG 到端口）。
 *
 * 因此这里替掉的只是**被测量之外**的协作者，`form_phonecall.cpp` 一个字节
 * 不改，仍在真实代码路径上。
 *
 * 安全阀：未定义 `ACC_FORM_PHONECALL_TEST` 直接 `#error`。
 * 带 Q_OBJECT：`form_phonecall.cpp` 用函数指针 connect 了 `videoFrameReady`，
 * 且本替身也要能发信号；因此本头已显式列进 `add_executable` 源列表。
 */
#ifndef ACCESSTERMINAL_TESTS_SHADOWS_CALL_SESSION_H
#define ACCESSTERMINAL_TESTS_SHADOWS_CALL_SESSION_H

#ifndef ACC_FORM_PHONECALL_TEST
#  error "这个影子 core/media/call_session.h 只能用于测试；请定义 ACC_FORM_PHONECALL_TEST"
#endif

#include <QImage>
#include <QObject>
#include <QString>

namespace accessterminal {

class CallSession : public QObject
{
    Q_OBJECT

public:
    explicit CallSession(QObject* parent = nullptr);
    ~CallSession() override;

    void start();
    void stop();

    bool isRunning() const { return m_running; }

    /// 测试专用：模拟门口机送来一帧。
    void emitVideoFrameForTest(const QImage& frame) { emit videoFrameReady(frame); }

signals:
    void videoFrameReady(const QImage& frame);
    void errorOccurred(const QString& message);

private:
    bool m_running = false;
};

} // namespace accessterminal

#endif // ACCESSTERMINAL_TESTS_SHADOWS_CALL_SESSION_H
