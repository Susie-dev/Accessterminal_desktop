/**
 * @file fake_audio.cpp
 * @brief 声卡替身的全局记录定义。
 *
 * 这里包含的是**影子** `<QAudioFormat>`（靠 include 路径顺序命中），
 * 与 call_session.cpp 编译时看到的必须是同一个头，否则两边对类型布局的
 * 理解会不一致 —— 那是最难查的一类错乱。
 */
#include <QAudioFormat>

#include "fake_audio.h"

namespace {

FakeAudioRecord g_record;

} // namespace

FakeAudioRecord& fakeAudio()
{
    return g_record;
}

void resetFakeAudio()
{
    // 故意**不**重置 lastFormat 之外的指针字段为 nullptr 之外的东西：
    // outDevice/inDevice 由 QAudioInput/QAudioOutput 的构造/析构维护，
    // reset 只清空观测值，避免把仍在使用的设备指针弄丢。
    FakeAudioDevice* outDev = g_record.outDevice;
    FakeAudioDevice* inDev = g_record.inDevice;
    g_record = FakeAudioRecord();
    g_record.outDevice = outDev;
    g_record.inDevice = inDev;
}
