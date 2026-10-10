/**
 * @file app_config.cpp
 * @brief AppConfig 实现：内置默认值 → JSON → 环境变量。
 */
#include "config/app_config.h"

#include "core/net/protocol.h"

#include <QCoreApplication>
#include <QDebug>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>

namespace accessterminal {

namespace {

/// 读取 JSON 子对象；缺失或类型不符时返回空对象。
QJsonObject jsonObject(const QJsonObject& parent, const QString& key)
{
    const QJsonValue v = parent.value(key);
    return v.isObject() ? v.toObject() : QJsonObject();
}

QString jsonString(const QJsonObject& obj, const QString& key, const QString& fallback)
{
    const QJsonValue v = obj.value(key);
    return v.isString() ? v.toString() : fallback;
}

int jsonInt(const QJsonObject& obj, const QString& key, int fallback)
{
    const QJsonValue v = obj.value(key);
    return v.isDouble() ? v.toInt() : fallback;
}

/// 将 "FD 03 4C 12 04 5D DF" 或 "FD034C12045DDF" 解析为字节序列。
QByteArray parseHexBytes(const QString& text)
{
    QString compact = text;
    compact.remove(QChar(' '));
    compact.remove(QChar(','));
    compact.remove(QChar(':'));
    compact.remove(QStringLiteral("0x"), Qt::CaseInsensitive);
    if (compact.isEmpty() || compact.size() % 2 != 0) {
        return QByteArray();
    }
    return QByteArray::fromHex(compact.toLatin1());
}

/// 环境变量覆盖：存在且非空时生效。
template <typename T>
void envOverride(const char* name, T& target, T (*convert)(const QByteArray&))
{
    const QByteArray value = qgetenv(name);
    if (!value.isEmpty()) {
        target = convert(value);
    }
}

QString toQString(const QByteArray& v) { return QString::fromLocal8Bit(v); }
int toInt(const QByteArray& v) { return v.toInt(); }

} // namespace

AppConfig& AppConfig::instance()
{
    static AppConfig config;
    return config;
}

AppConfig::AppConfig()
{
    applyDefaults();
}

void AppConfig::applyDefaults()
{
    // 默认值与重构前的硬编码保持一致，确保行为不变。
    m_selfIp = QStringLiteral("192.168.1.4");
    m_deviceIp = QStringLiteral("192.168.1.8");
    m_signalingPort = protocol::kSignalingPort;
    m_serialPortName = QStringLiteral("/dev/ttyUSB0");
    m_weatherUrl = QStringLiteral("http://t.weather.itboy.net/api/weather/city/101230101");
    m_ringtonePath = QStringLiteral("qrc:/door.mp3");
    m_ringtoneVolume = 100;

    // 灯控指令：与重构前的 hexArray* 完全一致，禁止随意改动。
    m_lightCommands.insert(QStringLiteral("desk"),       QByteArray::fromHex("FD034C12045DDF"));
    m_lightCommands.insert(QStringLiteral("work"),       QByteArray::fromHex("FD034C12025DDF"));
    m_lightCommands.insert(QStringLiteral("work_round"), QByteArray::fromHex("FD039736F44FDF"));
    m_lightCommands.insert(QStringLiteral("desk_round"), QByteArray::fromHex("FD039736F250DF"));
    m_lightCommands.insert(QStringLiteral("wall"),       QByteArray::fromHex("FD039736F150DF"));
}

/// 按 Linux 常规约定查找配置文件。
static QStringList defaultConfigCandidates()
{
    QStringList paths;
    if (QCoreApplication::instance()) {
        paths << QCoreApplication::applicationDirPath() + QStringLiteral("/appconfig.json");
    }
    paths << QStringLiteral("config/appconfig.json");
    paths << QStringLiteral("/etc/accessterminal/appconfig.json");
    return paths;
}

bool AppConfig::load(const QString& filePath)
{
    applyDefaults();

    QStringList candidates;
    if (!filePath.isEmpty()) {
        candidates << filePath;
    } else {
        candidates = defaultConfigCandidates();
    }

    QString usedPath;
    QJsonObject root;
    for (const QString& candidate : candidates) {
        QFile file(candidate);
        if (!file.exists() || !file.open(QIODevice::ReadOnly)) {
            continue;
        }
        QJsonParseError error{};
        const QJsonDocument doc = QJsonDocument::fromJson(file.readAll(), &error);
        file.close();
        if (error.error != QJsonParseError::NoError) {
            qWarning() << "[配置] 解析失败" << candidate << error.errorString();
            continue;
        }
        if (!doc.isObject()) {
            qWarning() << "[配置] 顶层不是 JSON 对象，已忽略:" << candidate;
            continue;
        }
        root = doc.object();
        usedPath = candidate;
        break;
    }

    if (!usedPath.isEmpty()) {
        const QJsonObject net = jsonObject(root, QStringLiteral("network"));
        m_selfIp = jsonString(net, QStringLiteral("self_ip"), m_selfIp);
        m_deviceIp = jsonString(net, QStringLiteral("device_ip"), m_deviceIp);
        m_signalingPort = static_cast<quint16>(
            jsonInt(net, QStringLiteral("signaling_port"), m_signalingPort));

        const QJsonObject hw = jsonObject(root, QStringLiteral("hardware"));
        m_serialPortName = jsonString(hw, QStringLiteral("serial_port"), m_serialPortName);

        const QJsonObject weather = jsonObject(root, QStringLiteral("weather"));
        m_weatherUrl = jsonString(weather, QStringLiteral("url"), m_weatherUrl);

        const QJsonObject media = jsonObject(root, QStringLiteral("media"));
        m_ringtonePath = jsonString(media, QStringLiteral("ringtone"), m_ringtonePath);
        m_ringtoneVolume = jsonInt(media, QStringLiteral("ringtone_volume"), m_ringtoneVolume);

        // 灯控指令允许通过配置覆盖，便于现场调整。
        const QJsonObject lights = jsonObject(root, QStringLiteral("lights"));
        for (auto it = lights.constBegin(); it != lights.constEnd(); ++it) {
            if (!it.value().isString()) {
                continue;
            }
            const QByteArray bytes = parseHexBytes(it.value().toString());
            if (!bytes.isEmpty()) {
                m_lightCommands.insert(it.key(), bytes);
            } else {
                qWarning() << "[配置] 灯控指令格式非法，已忽略:" << it.key();
            }
        }

        m_loadedFromFile = true;
        m_configPath = usedPath;
    }

    applyEnvironment();
    return m_loadedFromFile;
}

void AppConfig::applyEnvironment()
{
    // 历史变量名：保持与旧版部署脚本兼容。
    envOverride("SMARTSERVER_SELF_IP", m_selfIp, toQString);
    envOverride("SMARTSERVER_DEVICE_IP", m_deviceIp, toQString);

    // 统一前缀：新部署建议使用这一组。
    envOverride("ACCESSTERMINAL_NETWORK_SELF_IP", m_selfIp, toQString);
    envOverride("ACCESSTERMINAL_NETWORK_DEVICE_IP", m_deviceIp, toQString);
    envOverride("ACCESSTERMINAL_NETWORK_SIGNALING_PORT", m_signalingPort,
                [](const QByteArray& v) { return static_cast<quint16>(v.toUShort()); });
    envOverride("ACCESSTERMINAL_HARDWARE_SERIAL_PORT", m_serialPortName, toQString);
    envOverride("ACCESSTERMINAL_WEATHER_URL", m_weatherUrl, toQString);
}

QByteArray AppConfig::lightCommand(const QString& name) const
{
    return m_lightCommands.value(name);
}

} // namespace accessterminal
