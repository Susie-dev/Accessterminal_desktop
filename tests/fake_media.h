/**
 * @file fake_media.h
 * @brief `Form_phonecall` 测试用替身的全局记录访问入口。
 *
 * 与 tests/fake_serial_port.h 同一套路：测试文件包含本头即可读取记录，
 * 不必（也不能）去包含真的 Qt 多媒体头。
 */
#ifndef ACCESSTERMINAL_TESTS_FAKE_MEDIA_H
#define ACCESSTERMINAL_TESTS_FAKE_MEDIA_H

#include <QString>

class QMediaPlayer;
namespace accessterminal {
class CallSession;
}

/// 影子 QMediaPlayer 记录下来的可观测量（门铃音路径）。
struct FakeMediaPlayerRecord
{
    int constructed = 0;
    int destroyed = 0;
    /// setMedia() 收到的媒体地址。
    QString media;
    int setMediaCalls = 0;
    /// setVolume() 收到的音量；-1 表示没调用过。
    int volume = -1;
    int playCalls = 0;
    int stopCalls = 0;
    /// 当前存活实例；销毁后置空（供测试触发 stateChanged）。
    QMediaPlayer* last = nullptr;
};

FakeMediaPlayerRecord& fakeMediaPlayer();
void resetFakeMediaPlayer();

/// 影子 CallSession 记录下来的可观测量（通话通道生命周期）。
struct FakeCallSessionRecord
{
    int constructed = 0;
    int destroyed = 0;
    int startCalls = 0;
    int stopCalls = 0;
    bool running = false;
    /// 当前存活实例；销毁后置空（供测试回送一帧视频）。
    accessterminal::CallSession* last = nullptr;
};

FakeCallSessionRecord& fakeCallSession();
void resetFakeCallSession();

#endif // ACCESSTERMINAL_TESTS_FAKE_MEDIA_H
