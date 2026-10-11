/**
 * @file fake_audio.h
 * @brief QtMultimedia 音频类（QAudioFormat/QAudioInput/QAudioOutput）的替身记录。
 *
 * 为什么只替声音、不替 socket
 * ---------------------------
 * `call_session.cpp` 用的是**协议固定端口** UDP 12345（双向音频，裸 PCM）与
 * UDP 23456（单向视频，整帧 JPEG），不能像 monitor_client 那样挪到别的端口
 * 测。探针实测（%TEMP%\probe34\result17.txt）：
 *   bind(AnyIPv4,12345,ShareAddress) = true
 *   readDatagram -> 640 字节  sender=127.0.0.2:52803（与发送端一致）
 * 因此 **socket 一律用真的**，在真实协议端口上收发 —— 这才能证明"端口对了、
 * 报文语义对了"。
 *
 * 只有声卡部分必须替身：本机虽有可用音频设备（探针 result16.txt：
 * QAudioOutput::start() 非空、QAudioInput::start() 非空），但把单元测试
 * 绑在**开发机的真实声卡**上会让结果取决于机器配置（有无声卡、是否被独占、
 * 采样率支持与否）——那正是"在我这儿能跑"的坑。替身让音频路径完全确定。
 *
 * 本头文件只依赖真的 QIODevice，不依赖 QtMultimedia，因此测试文件可以安全包含。
 */
#ifndef ACCESSTERMINAL_TESTS_FAKE_AUDIO_H
#define ACCESSTERMINAL_TESTS_FAKE_AUDIO_H

#include <QByteArray>
#include <QIODevice>
#include <QString>

#include <cstring>

/**
 * @brief QAudioFormat 的替身记录。
 *
 * 各字段就是 true Qt 对应 setter 收到的**原值**，测试直接断言这些原值
 * （而不是断言替身算出来的派生值），避免"拿替身的算法验被测代码"。
 */
struct FakeAudioFormatRecord
{
    int sampleRate = -1;
    int channelCount = -1;
    int sampleSize = -1;
    QString codec;
    int byteOrder = -1;
    int sampleType = -1;

    int setSampleRateCalls = 0;
    int setChannelCountCalls = 0;
    int setSampleSizeCalls = 0;
    int setCodecCalls = 0;
    int setByteOrderCalls = 0;
    int setSampleTypeCalls = 0;
};

/**
 * @brief 声卡替身设备。
 *
 * - 作为**输出**（QAudioOutput::start() 返回它）时，被测代码往里 `write()`，
 *   字节被记进 `written`；
 * - 作为**输入**（QAudioInput::start() 返回它）时，测试用 `feed()` 投喂字节，
 *   被测代码用 `readAll()` 取走。
 *
 * 刻意**不加 Q_OBJECT**：本类所在头文件不在任何目标的源列表里，AUTOMOC 不会
 * 处理；而 `connect(device, &QIODevice::readyRead, ...)` 用的是 QIODevice 的
 * 信号，不需要本类自己的元对象。
 */
class FakeAudioDevice : public QIODevice
{
public:
    explicit FakeAudioDevice(QObject* parent = nullptr) : QIODevice(parent) {}

    // ---- 输出侧 ----
    /// 被测代码写进来的全部字节。
    QByteArray written;

    // ---- 输入侧 ----
    /// 测试投喂给被测代码的待读字节。
    QByteArray feed;
    /// 往输入侧投喂字节，并发 readyRead（模拟声卡送来数据）。
    void feedBytes(const QByteArray& data)
    {
        if (data.isEmpty()) {
            return;
        }
        feed.append(data);
        emit readyRead();
    }

    bool isSequential() const override { return true; }

    /// 让 `writeData()` 返回 0（模拟声卡暂时收不下）。
    /// 用于覆盖 writeAudioData() 里 `written > 0` 不成立时的 break 分支。
    bool writeReturnsZero = false;

protected:
    qint64 readData(char* data, qint64 maxSize) override
    {
        if (feed.isEmpty() || maxSize <= 0) {
            return 0;
        }
        const qint64 n = qMin<qint64>(maxSize, feed.size());
        memcpy(data, feed.constData(), static_cast<size_t>(n));
        feed.remove(0, static_cast<int>(n));
        return n;
    }

    qint64 writeData(const char* data, qint64 maxSize) override
    {
        if (maxSize <= 0) {
            return 0;
        }
        if (writeReturnsZero) {
            ++writeZeroCalls;
            return 0;
        }
        written.append(data, static_cast<int>(maxSize));
        return maxSize;
    }

public:
    /// `writeData()` 因 writeReturnsZero 而返回 0 的次数。
    int writeZeroCalls = 0;
};

/// 声卡替身的全局记录。
struct FakeAudioRecord
{
    /// QAudioFormat 每次构造后、由 setter 累积出的"最近一次格式"。
    /// QAudioInput / QAudioOutput 的构造函数会把它**快照**成 in/outFormat。
    FakeAudioFormatRecord lastFormat;

    FakeAudioFormatRecord outFormat;
    FakeAudioFormatRecord inFormat;

    int outCtorCalls = 0;
    int inCtorCalls = 0;

    int outBufferSize = -1;
    int outNotifyInterval = -1;
    int inBufferSize = -1;
    int inNotifyInterval = -1;

    int outStartCalls = 0;
    int inStartCalls = 0;
    int outStopCalls = 0;
    int inStopCalls = 0;

    /// 让 `start()` 返回 nullptr，用于覆盖"声卡启动失败"分支。
    bool failOutputStart = false;
    bool failInputStart = false;

    /// `error()` 的返回值。
    int outError = 0;
    int inError = 0;

    /// `bytesFree()` 的返回值（控制 writeAudioData 的循环）。
    int bytesFree = 4096;

    /// start() 返回出去的设备（由替身持有）。
    FakeAudioDevice* outDevice = nullptr;
    FakeAudioDevice* inDevice = nullptr;

    /// QAudioFormat::bytesPerFrame() 实际被算成了多少。
    int outBytesPerFrame = -1;
    int inBytesPerFrame = -1;
};

FakeAudioRecord& fakeAudio();
void resetFakeAudio();

#endif // ACCESSTERMINAL_TESTS_FAKE_AUDIO_H
