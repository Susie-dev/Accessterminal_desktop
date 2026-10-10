/**
 * @file call_session.h
 * @brief 通话期间的双向音频与单向视频通道。
 *
 * 从 Form_phonecall 中抽离，使窗口只负责界面交互：
 *   UDP 12345  双向音频，裸 PCM（S16_LE / 16000Hz / 单声道），无包头
 *   UDP 23456  单向视频，门口机→室内机，每包一帧完整 JPEG，不重组不重传
 *
 * 生命周期：仅在用户接通（accepted）后 start()，挂断时 stop()。
 * 空闲时不占用端口与声卡，与重构前一致。
 */
#ifndef ACCESSTERMINAL_CORE_MEDIA_CALL_SESSION_H
#define ACCESSTERMINAL_CORE_MEDIA_CALL_SESSION_H

#include <QByteArray>
#include <QHostAddress>
#include <QImage>
#include <QObject>
#include <QString>

class QAudioInput;
class QAudioOutput;
class QIODevice;
class QUdpSocket;

namespace accessterminal {

class CallSession : public QObject
{
    Q_OBJECT

public:
    explicit CallSession(QObject* parent = nullptr);
    ~CallSession() override;

    /**
     * @brief 建立音频/视频通道与声卡。
     *
     * 幂等：重复调用会先释放旧资源。任一步失败都会记录日志，
     * 但不抛出异常——通话界面仍可显示，只是没有声音/画面。
     */
    void start();

    /// 释放全部 socket、声卡与缓冲。
    void stop();

    /// 是否已启动。
    bool isRunning() const { return m_running; }

signals:
    /// 收到一帧视频画面（JPEG 已解码）。
    void videoFrameReady(const QImage& frame);
    /// 通道错误提示。
    void errorOccurred(const QString& message);

private:
    bool startAudioSocket();
    bool startVideoSocket();
    void startAudioOutput();
    void startAudioInput();

    void onAudioDataReady();
    void onVideoDataReady();
    void onInputReady();
    void writeAudioData();

    QUdpSocket* m_audioSocket = nullptr;
    QUdpSocket* m_videoSocket = nullptr;
    QAudioOutput* m_audioOutput = nullptr;
    QIODevice* m_audioDevice = nullptr;
    QAudioInput* m_audioInput = nullptr;
    QIODevice* m_inputDevice = nullptr;

    QByteArray m_audioBuffer;
    QByteArray m_inputBuffer;

    /// 回传语音的目标：学到门口机的实际地址后才发。
    QHostAddress m_deviceAddress;
    quint16 m_devicePort = 0;

    bool m_running = false;
};

} // namespace accessterminal

#endif // ACCESSTERMINAL_CORE_MEDIA_CALL_SESSION_H
