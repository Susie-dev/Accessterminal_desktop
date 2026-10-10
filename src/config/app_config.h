/**
 * @file app_config.h
 * @brief 室内机运行时配置（单一事实来源）。
 *
 * 取代原先分散在 appconfig.h、widget.cpp、form_phonecall.cpp 中的
 * 硬编码值（IP、端口、串口名、天气城市、灯控指令）。
 *
 * 取值优先级（后者覆盖前者）：
 *   1. 内置默认值（与重构前行为一致）
 *   2. JSON 配置文件
 *   3. 环境变量
 *
 * 环境变量沿用历史命名以保持兼容（SMARTSERVER_SELF_IP 等），
 * 同时提供统一的 ACCESSTERMINAL_* 前缀。
 */
#ifndef ACCESSTERMINAL_CONFIG_APP_CONFIG_H
#define ACCESSTERMINAL_CONFIG_APP_CONFIG_H

#include <QByteArray>
#include <QHash>
#include <QString>

namespace accessterminal {

/**
 * @brief 应用配置单例。
 *
 * 在 QApplication 构造后、任何模块创建前调用一次 load()。
 */
class AppConfig
{
public:
    static AppConfig& instance();

    /**
     * @brief 载入配置。
     * @param filePath 配置文件路径；为空时按默认顺序查找。
     * @return 成功读取到配置文件返回 true；全部使用默认值返回 false。
     */
    bool load(const QString& filePath = QString());

    // ---- 网络 ----
    /// 室内机（本机）地址，仅用于日志与绑定提示。
    QString selfIp() const { return m_selfIp; }
    /// T113 门口机地址，远程监看时作为 UDP 目标。
    QString deviceIp() const { return m_deviceIp; }
    /// 信令 TCP 端口（室内机监听）。
    quint16 signalingPort() const { return m_signalingPort; }

    // ---- 硬件 ----
    /// 灯控串口设备名。Linux 下形如 /dev/ttyUSB0，不再是 Windows 的 COM24。
    QString serialPortName() const { return m_serialPortName; }

    // ---- 天气 ----
    /// 天气接口 URL；为空表示禁用天气功能。
    QString weatherUrl() const { return m_weatherUrl; }

    // ---- 音视频 ----
    /// 门铃音资源路径。
    QString ringtonePath() const { return m_ringtonePath; }
    /// 门铃音音量（0-100）。
    int ringtoneVolume() const { return m_ringtoneVolume; }

    // ---- 灯控指令 ----
    /// 灯控串口指令（十六进制字节序列）。
    QByteArray lightCommand(const QString& name) const;

    /// 是否已从配置文件载入。
    bool loadedFromFile() const { return m_loadedFromFile; }

    /// 当前使用的配置文件路径（用于日志）。
    QString configPath() const { return m_configPath; }

private:
    AppConfig();
    AppConfig(const AppConfig&) = delete;
    AppConfig& operator=(const AppConfig&) = delete;

    void applyDefaults();
    void applyEnvironment();

    QString m_selfIp;
    QString m_deviceIp;
    quint16 m_signalingPort = 0;
    QString m_serialPortName;
    QString m_weatherUrl;
    QString m_ringtonePath;
    int m_ringtoneVolume = 100;
    QHash<QString, QByteArray> m_lightCommands{};

    bool m_loadedFromFile = false;
    QString m_configPath;
};

} // namespace accessterminal

#endif // ACCESSTERMINAL_CONFIG_APP_CONFIG_H
