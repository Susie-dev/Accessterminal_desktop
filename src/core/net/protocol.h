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
#include <QList>
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

/**
 * @brief 判断一段文本是否是其它信令线上文本的**严格前缀**。
 *
 * 用于消除“宽容尾段匹配”带来的歧义：
 * `"stop"` 是 `"stopsend"` 的前缀。若 TCP 恰好把 `"stopsend\n"` 拆成
 * `"stop"` 与 `"send\n"`，仅凭 `"stop"` 就立即判定会得出**错误的信令**
 * （Stop 而非 StopSend）——比丢包更危险，因为它会触发错误的行为。
 * 因此这类有歧义的前缀必须继续缓冲等待后续字节。
 *
 * @param tail 已 trim 的候选文本。
 * @return 是某个其它信令的严格前缀则返回 true。
 */
inline bool isAmbiguousPrefix(const QByteArray& tail)
{
    static const char* const kAllSignals[] = {
        "call", "accept", "recstop", "unlock", "stopsend", "getframe", "stop"
    };
    const int count = static_cast<int>(sizeof(kAllSignals) / sizeof(kAllSignals[0]));
    for (int i = 0; i < count; ++i) {
        const QByteArray s = QByteArray::fromRawData(
            kAllSignals[i], static_cast<int>(qstrlen(kAllSignals[i])));
        if (s != tail && s.startsWith(tail)) {
            return true;
        }
    }
    return false;
}

/**
 * @brief TCP 信令字节流解码器（跨 readAll 保存半包）。
 *
 * TCP 是字节流，没有消息边界。一次 readyRead 可能拿到：
 *   - 正好一条信令：   "unlock\n"
 *   - 半条信令：       "unl"        （剩余部分在下一个 TCP 段里）
 *   - 粘包：           "call\nunlock\nstopsend\n"
 *
 * 前两者若用 `data.split('\n')` 就地解析，半包会被当成一条无法识别的
 * 信令而**静默丢弃**——"unlock\n" 被拆成 "unl" 与 "ock\n" 时，
 * 开锁指令就此丢失，而且没有任何报错。这是真实链路（尤其是弱网或
 * 分片发送）下会发生的缺陷。
 *
 * 本类把未以 '\n' 结尾的尾段暂存起来，与下一次数据拼接后再解析，
 * 因此对任意切分方式都能正确还原信令。
 *
 * 与旧实现的兼容（重要）
 * ----------------------
 * 重构前的解析是 `split('\n', QString::SkipEmptyParts)`，它把**末尾那段
 * 没有 '\n' 的内容也当作一条完整信令**去比较。因此旧版室内机发出的
 * `"recstop"`（注意：历史上这一条就漏了 '\n'，见 baseline
 * desktop/smartserver/widget.cpp:566）能被旧版门口机正确识别。
 *
 * 如果这里改成严格的“只认以 '\n' 结尾的完整行”，那么在新版门口机
 * 搭配**尚未升级的旧版室内机**时，`"recstop"` 会一直躺在缓冲区里，
 * 挂断指令永远送不到——这是混合部署下真实会发生的兼容性回归。
 *
 * 因此这里保留旧版的宽容语义：末尾那段未以 '\n' 结束的文本，若**恰好
 * 等于一条已知信令**，就立即当作完整信令处理；否则继续留在缓冲区等待
 * 后续字节。这样：
 *   - 旧版发的 `"recstop"`（无 '\n'）→ 立即识别，兼容旧设备；
 *   - 半包 `"unl"` / `"ock\n"` → "unl" 不是已知信令，继续缓冲，
 *     与 "ock\n" 拼接后还原出 unlock，修掉了旧版会丢包的缺陷。
 *
 * @note 使用方式：每次 readyRead 时构造（或用 reset() 复用）后喂入
 *       本次读到的全部字节，遍历 feed() 返回的信令列表。
 */
class StreamDecoder
{
public:
    StreamDecoder() {}

    /// 清空内部缓冲（重连后调用，避免陈旧的半包与新连接的数据拼接）。
    void reset() { m_buffer.clear(); }

    /**
     * @brief 喂入新到的字节，返回其中可完整解析出的信令。
     *
     * 无法识别的完整行会被忽略（与重构前一致：忽略而非断开连接）；
     * 末尾未以 '\n' 结束的片段会留在内部缓冲，等待下次 feed()。
     *
     * @param data 本次从 socket 读到的全部字节。
     * @return 按到达顺序排列的信令列表。
     */
    QList<Signal> feed(const QByteArray& data)
    {
        QList<Signal> out;
        m_buffer.append(data);

        // 反复截取第一段 '\n' 之前的内容，直到剩余部分不含 '\n'。
        int pos;
        while ((pos = m_buffer.indexOf(kSignalTerminator)) >= 0) {
            const QByteArray line = m_buffer.left(pos);
            m_buffer.remove(0, pos + 1);

            const QByteArray trimmed = line.trimmed();
            if (trimmed.isEmpty()) {
                continue; // 空行（例如 '\r\n' 或多余的 '\n'）
            }
            const Signal sig = fromWire(trimmed);
            if (sig == Signal::Unknown) {
                continue; // 无法识别的行：忽略，不断开
            }
            out.append(sig);
        }

        // 兼容旧版：末尾若有一段未以 '\n' 结束、但本身**已经是一条
        // 完整已知信令**的内容，按旧版语义立即处理（详见类注释）。
        // 典型场景是旧版室内机发出的无 '\n' 的 "recstop"。
        //
        // 例外：若有歧义（是其它信令的严格前缀，如 "stop" 之于
        // "stopsend"），则**必须继续等待**——立即判定会得到错误的信令。
        if (!m_buffer.isEmpty()) {
            const QByteArray tail = m_buffer.trimmed();
            if (fromWire(tail) != Signal::Unknown && !isAmbiguousPrefix(tail)) {
                out.append(fromWire(tail));
                m_buffer.clear();
            }
        }

        // 防御：若对端一直不发 '\n'（且尾段也不构成已知信令），缓冲会
        // 无限增长。信令最长 8 字节，超过一个宽松上限就说明数据已不是
        // 本协议的内容，直接丢弃。
        if (m_buffer.size() > kMaxBufferedBytes) {
            m_buffer.clear();
        }
        return out;
    }

    /// 当前是否残留未完成的半包。
    bool hasPartial() const { return !m_buffer.isEmpty(); }

    /// 尚未解析的字节数（供日志/断言使用）。
    int bufferedBytes() const { return m_buffer.size(); }

private:
    /// 未以 '\n' 结尾的残留数据上限。
    static const int kMaxBufferedBytes = 4096;

    QByteArray m_buffer;
};

} // namespace protocol
} // namespace accessterminal

#endif // ACCESSTERMINAL_CORE_NET_PROTOCOL_H
