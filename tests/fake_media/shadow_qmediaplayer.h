/**
 * @file shadow_qmediaplayer.h
 * @brief 影子 `QMediaPlayer` 的**类定义本体**（配合 tests/fake_media/QMediaPlayer）。
 *
 * 为什么要拆成两个文件
 * --------------------
 * `#include <QMediaPlayer>` 要找的文件名必须**恰好**是 `QMediaPlayer`
 * （真 Qt 头本身就没有扩展名）。而 AUTOMOC **只按扩展名**
 * （.h/.hpp/.hh/.hxx…）挑选要生成元对象的头 —— 一个叫 `QMediaPlayer`
 * 的无扩展名文件会被它**直接忽略**。
 *
 * 后果不是编译错误，而是**链接错误**，而且看着很像别的问题：
 *     undefined reference to `QMediaPlayer::staticMetaObject'
 *     undefined reference to `QMediaPlayer::stateChanged(QMediaPlayer::State)'
 *     undefined reference to `vtable for QMediaPlayer'
 * 本测试第一版就踩了这个坑（同一类坑在门口机影子 `ui/widget.h` 上出现过，
 * 那边是因为 AUTOMOC 不看 include 目录）。
 *
 * 所以：无扩展名的 `QMediaPlayer` 只做一次转发 include，真正的类定义放本文件，
 * 并把**本文件**列进 `add_executable` 源列表 —— 这样 AUTOMOC 才会处理它。
 */
#ifndef ACCESSTERMINAL_TESTS_SHADOW_QMEDIAPLAYER_H
#define ACCESSTERMINAL_TESTS_SHADOW_QMEDIAPLAYER_H

#ifndef ACC_FORM_PHONECALL_TEST
#  error "这个影子 QMediaPlayer 只能用于测试；请在测试目标上定义 ACC_FORM_PHONECALL_TEST"
#endif

#include <QObject>
#include <QString>
#include <QUrl>

class QMediaPlayer : public QObject
{
    Q_OBJECT

public:
    /// 与真 QMediaPlayer 同名同值的状态枚举（源码按名字使用）。
    enum State {
        StoppedState,
        PlayingState,
        PausedState
    };

    explicit QMediaPlayer(QObject* parent = nullptr);
    ~QMediaPlayer() override;

    void setMedia(const QUrl& media);
    void setVolume(int volume);
    void play();
    void stop();

    State state() const { return m_state; }

    /// 测试专用：模拟"这段音频播完了"，用于验证循环播放。
    void emitStateForTest(State state);

signals:
    void stateChanged(QMediaPlayer::State state);

private:
    State m_state = StoppedState;
};

#endif // ACCESSTERMINAL_TESTS_SHADOW_QMEDIAPLAYER_H
