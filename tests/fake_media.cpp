/**
 * @file fake_media.cpp
 * @brief 影子 QMediaPlayer / CallSession 的实现与记录定义。
 *
 * 这里包含的是**影子**头（靠 include 路径顺序命中），与 `form_phonecall.cpp`
 * 编译时看到的必须是同一份，否则两边对类型布局的理解会不一致。
 */
#include <QMediaPlayer>

#include "core/media/call_session.h"
#include "fake_media.h"

// ---------------------------------------------------------------------------
// QMediaPlayer 替身
// ---------------------------------------------------------------------------
namespace {

FakeMediaPlayerRecord g_player;
FakeCallSessionRecord g_session;

} // namespace

FakeMediaPlayerRecord& fakeMediaPlayer()
{
    return g_player;
}

void resetFakeMediaPlayer()
{
    g_player = FakeMediaPlayerRecord();
}

QMediaPlayer::QMediaPlayer(QObject* parent)
    : QObject(parent)
{
    ++fakeMediaPlayer().constructed;
    fakeMediaPlayer().last = this;
}

QMediaPlayer::~QMediaPlayer()
{
    ++fakeMediaPlayer().destroyed;
    if (fakeMediaPlayer().last == this) {
        fakeMediaPlayer().last = nullptr;
    }
}

void QMediaPlayer::setMedia(const QUrl& media)
{
    ++fakeMediaPlayer().setMediaCalls;
    fakeMediaPlayer().media = media.toString();
}

void QMediaPlayer::setVolume(int volume)
{
    fakeMediaPlayer().volume = volume;
}

void QMediaPlayer::play()
{
    ++fakeMediaPlayer().playCalls;
    m_state = PlayingState;
}

void QMediaPlayer::stop()
{
    ++fakeMediaPlayer().stopCalls;
    m_state = StoppedState;
}

void QMediaPlayer::emitStateForTest(State state)
{
    m_state = state;
    emit stateChanged(state);
}

// ---------------------------------------------------------------------------
// CallSession 替身
//
// 注意命名空间：`fakeCallSession()` / `resetFakeCallSession()` 在 fake_media.h
// 里声明于**全局**作用域，故它们的定义也必须在全局作用域 —— 否则会出现
// `undefined reference to fakeCallSession()`（本测试第一版就这么错过一次）。
// 只有 CallSession 的成员函数属于 accessterminal。
// ---------------------------------------------------------------------------
FakeCallSessionRecord& fakeCallSession()
{
    return g_session;
}

void resetFakeCallSession()
{
    g_session = FakeCallSessionRecord();
}

namespace accessterminal {

CallSession::CallSession(QObject* parent)
    : QObject(parent)
{
    ++fakeCallSession().constructed;
    fakeCallSession().last = this;
}

CallSession::~CallSession()
{
    ++fakeCallSession().destroyed;
    if (fakeCallSession().last == this) {
        fakeCallSession().last = nullptr;
    }
}

void CallSession::start()
{
    ++fakeCallSession().startCalls;
    m_running = true;
    fakeCallSession().running = true;
}

void CallSession::stop()
{
    ++fakeCallSession().stopCalls;
    m_running = false;
    fakeCallSession().running = false;
}

} // namespace accessterminal
