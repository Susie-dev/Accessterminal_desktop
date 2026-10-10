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
 * @brief 把配置中的整数值限制到 [lo, hi]。
 *
 * 配置来源（JSON 文件、环境变量）都是不可信输入：
 *   - 环境变量用 QString::toInt()/toUShort() 解析，**非法文本返回 0**；
 *   - JSON 里也可以直接写 0、负数或超出 quint16 的值。
 *
 * 在取值出口统一兜底，合法配置的行为与重构前逐字节一致。
 * 与门口机 app_config.h 中的同名辅助函数保持对称。
 */
inline int clampInt(int value, int lo, int hi)
{
    if (value < lo) return lo;
    if (value > hi) return hi;
    return value;
}

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
    /**
     * @brief 信令 TCP 端口（室内机监听）。
     *
     * 下限取 1：端口 0 会让 QTcpServer 绑定到一个随机临时端口，
     * 门口机仍按 8887 连接，结果是永远连不上且日志里看不出原因。
     * 默认值 8887 不受影响。
     */
    quint16 signalingPort() const { return static_cast<quint16>(clampInt(m_signalingPort, 1, 65535)); }

    // ---- 硬件 ----
    /// 灯控串口设备名。Linux 下形如 /dev/ttyUSB0，不再是 Windows 的 COM24。
    QString serialPortName() const { return m_serialPortName; }

    // ---- 天气 ----
    /// 天气接口 URL；为空表示禁用天气功能。
    QString weatherUrl() const { return m_weatherUrl; }

    // ---- 音视频 ----
    /// 门铃音资源路径。
    QString ringtonePath() const { return m_ringtonePath; }
    /// 门铃音音量（0-100）。QMediaPlayer::setVolume 超出范围的行为未定义，
    /// 这里收敛到 0~100；默认值 100 不受影响。
    int ringtoneVolume() const { return clampInt(m_ringtoneVolume, 0, 100); }

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
