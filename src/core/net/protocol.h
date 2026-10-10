/**
 * @file protocol.h
 * @brief Accessterminal 通信协议常量与信令定义（唯一事实来源）。
 *
 * 本文件在 Accessterminal_T113（门口机）与 Accessterminal_desktop（室内机）
 * 两个仓库中各存一份，内容必须完全一致；修改时须同步两侧，
 * 并由 tests/test_protocol 校验一致性。
 *
 * 协议概要（重构前后逐字节兼容，禁止随意变更）：
 *
 *   TCP 8887   信令，UTF-8 文本行，'\n' 分隔
 *              门口机→室内机 : call, stopsend, unlock
 *              室内机→门口机 : accept, recstop, unlock
 *   UDP 12345  双向音频，裸 PCM 无包头
 *              S16_LE / 16000Hz / 单声道 / 无压缩
 *   UDP 23456  单向视频，室内机←门口机，每包一帧完整 JPEG，不重传不重组
 *   UDP 50000  远程监看，室内机发 getframe/stop，门口机按定时器推 JPEG 帧
 *
 * @note 端口与信令字符串是跨设备契约，任何改动都会导致两端不兼容。
 */
#ifndef ACCESSTERMINAL_CORE_NET_PROTOCOL_H
#define ACCESSTERMINAL_CORE_NET_PROTOCOL_H

#include <QByteArray>
#include <QString>

namespace accessterminal {
namespace protocol {

// ============================================================================
// 协议版本
// ============================================================================

/// 协议版本号。任何不兼容的线上格式变更都必须递增此值。
///
/// @note 以下常量刻意不使用 `inline`（C++17 才支持 inline 变量），
///       本工程目标为标准 C++11。命名空间作用域的 constexpr 常量
///       具有内部链接，每个 TU 各持一份副本，不存在 ODR 冲突；
///       这些常量仅按值使用，从不取地址。
constexpr int kProtocolVersion = 1;

// ============================================================================
// 网络端口
// ============================================================================

/// 信令 TCP 端口。室内机监听，门口机作为客户端连接。
constexpr quint16 kSignalingPort = 8887;

/// 双向音频 UDP 端口。两端均绑定该端口以收发裸 PCM。
constexpr quint16 kAudioPort = 12345;

/// 单向视频 UDP 端口。室内机监听，接收门口机推送的 JPEG 帧。
constexpr quint16 kVideoPort = 23456;

/// 远程监看 UDP 端口。门口机监听，收到 getframe 后才推帧。
constexpr quint16 kPreviewPort = 50000;

// ============================================================================
// 音频参数（ALSA 与网络两侧必须一致）
// ============================================================================

/// 采样率（Hz）。语音通信标准。
constexpr int kAudioSampleRate = 16000;

/// 声道数，单声道。
constexpr int kAudioChannels = 1;

/// 每样本字节数，S16_LE。
constexpr int kAudioBytesPerSample = 2;

/// 每包帧数，320 帧 ≈ 20ms。
constexpr int kAudioFramesPerPacket = 320;

/// 每包字节数 = 320 * 1 * 2 = 640。
constexpr int kAudioBytesPerPacket =
    kAudioFramesPerPacket * kAudioChannels * kAudioBytesPerSample;

// ============================================================================
// 信令
// ============================================================================

/**
 * @brief 信令类型，与线上文本一一对应。
 *
 * 使用枚举而非裸字符串，避免拼写错误并集中管理线格式。
 */
enum class Signal {
    Unknown,     ///< 无法识别的信令，需忽略而非报错
    Call,        ///< 门口机→室内机：请求呼叫
    Accept,      ///< 室内机→门口机：接通，门口机据此创建音视频线程
    RecStop,     ///< 室内机→门口机：挂断
    Unlock,      ///< 双向：远程开锁
    StopSend,    ///< 门口机→室内机：对端停止发送
    GetFrame,    ///< 室内机→门口机：开始远程监看推帧
    Stop         ///< 室内机→门口机：停止远程监看推帧
};

/// 信令终止符。TCP 为文本行协议，以 '\n' 分包。
constexpr char kSignalTerminator = '\n';

/**
 * @brief 将信令枚举转为线上文本（不含终止符）。
 * @param signal 信令类型。
 * @return 对应的线上字符串；Unknown 返回空 QByteArray。
 */
inline QByteArray toWire(Signal signal)
{
    switch (signal) {
    case Signal::Call:      return QByteArrayLiteral("call");
    case Signal::Accept:    return QByteArrayLiteral("accept");
    case Signal::RecStop:   return QByteArrayLiteral("recstop");
    case Signal::Unlock:    return QByteArrayLiteral("unlock");
    case Signal::StopSend:  return QByteArrayLiteral("stopsend");
    case Signal::GetFrame:  return QByteArrayLiteral("getframe");
    case Signal::Stop:      return QByteArrayLiteral("stop");
    case Signal::Unknown:   break;
    }
    return QByteArray();
}

/**
 * @brief 解析线上文本为信令枚举。
 * @param wire 已去除首尾空白的原始文本。
 * @return 解析结果；无法识别时返回 Signal::Unknown。
 */
inline Signal fromWire(const QByteArray& wire)
{
    const QByteArray t = wire.trimmed();
    if (t == QByteArrayLiteral("call"))     return Signal::Call;
    if (t == QByteArrayLiteral("accept"))   return Signal::Accept;
    if (t == QByteArrayLiteral("recstop"))  return Signal::RecStop;
    if (t == QByteArrayLiteral("unlock"))   return Signal::Unlock;
    if (t == QByteArrayLiteral("stopsend")) return Signal::StopSend;
    if (t == QByteArrayLiteral("getframe")) return Signal::GetFrame;
    if (t == QByteArrayLiteral("stop"))     return Signal::Stop;
    return Signal::Unknown;
}

/**
 * @brief 构造可直接写入 socket 的信令帧（含 '\n'）。
 * @param signal 信令类型。
 * @return 线上字节；Unknown 返回空 QByteArray。
 */
inline QByteArray frame(Signal signal)
{
    QByteArray out = toWire(signal);
    if (!out.isEmpty()) {
        out.append(kSignalTerminator);
    }
    return out;
}

} // namespace protocol
} // namespace accessterminal

#endif // ACCESSTERMINAL_CORE_NET_PROTOCOL_H
