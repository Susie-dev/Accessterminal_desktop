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

/**
 * @brief 判断整串是否只由十六进制字符组成。
 *
 * 为什么必须自己逐字符校验，而不能指望 QByteArray::fromHex 报错：
 *
 * fromHex() **不会**因为遇到非法字符而返回空 —— 它会**跳过**非法字符，把
 * 剩下的合法字符**重新两两配对**。已在本机用真实 Qt 5.15.19 实测确认：
 *
 *   输入 "FD0G4C12045DDF"(14, 偶数) -> 0f d0 4c 12 04 5d df   （7 字节，全错）
 *   输入 "FD03Z412045DDF"(14, 偶数) -> 0f d0 34 12 04 5d df   （7 字节，全错）
 *   输入 "XX034C12045DDF"(14, 偶数) ->    03 4c 12 04 5d df   （6 字节，错位）
 *   输入 "FD034C12045DDZ"(14, 偶数) -> 0f d0 34 c1 20 45 dd   （7 字节，错位）
 *
 * 即：只要字符数恰好是偶数，解码**总是"成功"**，只是内容面目全非。于是
 * `!bytes.isEmpty()` 这道守卫完全拦不住，一条写错的灯控指令会被原样发给
 * 串口，灯只表现为"没反应"，排查时极易怀疑硬件。
 *
 * 注意 "FD0G…" 这类**偶数字符数**的输入恰恰是最容易写出的错法（把某一位
 * 敲成字母），所以这不是理论问题。
 */
bool isHexOnly(const QString& text)
{
    if (text.isEmpty()) {
        return false;
    }
    for (int i = 0; i < text.size(); ++i) {
        const QChar c = text.at(i);
        const bool ok = (c >= QChar('0') && c <= QChar('9')) ||
                        (c >= QChar('a') && c <= QChar('f')) ||
                        (c >= QChar('A') && c <= QChar('F'));
        if (!ok) {
            return false;
        }
    }
    return true;
}

/// 将 "FD 03 4C 12 04 5D DF" 或 "FD034C12045DDF" 解析为字节序列。
///
/// 任一条件不满足即返回空 QByteArray，由调用方告警并保留默认值：
///   - 清洗后为空；
///   - 清洗后长度为奇数（半字节对不齐）；
///   - 含有非十六进制字符（**必须显式检查**，理由见 isHexOnly 注释）。
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
    // 关键：fromHex 会静默跳过非法字符并重新配对，因此必须显式拒绝。
    if (!isHexOnly(compact)) {
        return QByteArray();
    }
    return QByteArray::fromHex(compact.toLatin1());
}

/// 环境变量覆盖：存在且非空时生效。
///
/// 转换器（convert）单独作为模板参数而非写死成函数指针：
/// 无捕获 lambda 虽然能隐式转换成函数指针，但该转换在模板实参推导
/// 阶段不参与，写死 T (*)(const QByteArray&) 会导致传入 lambda 时
/// 推导失败（编译错误）。此处放宽到任意可调用对象。
template <typename T, typename Converter>
void envOverride(const char* name, T& target, Converter convert)
{
    const QByteArray value = qgetenv(name);
    if (!value.isEmpty()) {
        target = static_cast<T>(convert(value));
    }
}

QString toQString(const QByteArray& v) { return QString::fromLocal8Bit(v); }

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
    // 关键：每次 load() 都必须把"是否已从文件载入"复位。
    //
    // applyDefaults() 只重置各字段，不碰 m_loadedFromFile / m_configPath。
    // 而 AppConfig 是**单例**且 load() 可被多次调用（测试里很常见，现场
    // 也可能重载），于是：
    //   1) 先 load(好文件) 成功 -> m_loadedFromFile = true；
    //   2) 再 load(坏文件)     -> 解析失败走 continue，**没有任何分支复位**
    //      这个标志，函数末尾 `return m_loadedFromFile;` 于是返回 **true**；
    //   3) 再 load(不存在的文件) -> 同样返回 true，configPath() 还指向那个
    //      早已不生效的旧路径。
    // 实测（真实 Qt）：load(bad) 返回 true 且 configPath 仍是上一个文件。
    // 调用方会据此认为"配置已按文件生效"，而实际用的是内置默认值 —— 一个会
    // 误导现场排查的错误返回值。
    m_loadedFromFile = false;
    m_configPath.clear();

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
        // 不能直接 static_cast<quint16>：那是**取模截断**而非夹取。
        // 实测（真实 Qt）：signaling_port = 65536 -> 0（=> 随机临时端口），
        // 999999 -> 16959，-1 -> 65535，-5 -> 65531。用户写成 65536/-1 这种
        // "明显想表达边界"的值时，得到的却是能成功监听的**错误端口** ——
        // 门口机连不上，而日志显示监听正常，极难定位。
        // 先按 int 读入并夹到 [1, 65535]，再交给 quint16。
        m_signalingPort = static_cast<quint16>(
            clampInt(jsonInt(net, QStringLiteral("signaling_port"), m_signalingPort),
                     1, 65535));

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
            // 以 '_' 开头的键是**注释**约定：JSON 没有注释语法，本工程的
            // config/appconfig.json 各段就都写了 "_comment"。
            //
            // 不跳过会怎样（实测）："_comment" 的值是一段中文说明，被当成一条
            // 灯控指令送进 parseHexBytes()，必然判为非法，于是**每次启动**都打
            //     [配置] 灯控指令格式非法，已忽略: "_comment"
            // 这既是噪声，又会把现场排障引向一个根本不存在的配置错误 ——
            // 而真正需要被看见的那条解析失败会被同样的文案盖住。
            if (it.key().startsWith(QLatin1Char('_'))) {
                continue;
            }
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
    // 端口同样要先夹取再转 quint16。toUShort() 对非法文本返回 0，而
    // static_cast<quint16> 会把 >=65536 的输入取模成小端口（65536 -> 0）。
    // 走 accessterminal::clampInt 的同一套规则，与 JSON 路径保持一致。
    envOverride("ACCESSTERMINAL_NETWORK_SIGNALING_PORT", m_signalingPort,
                [this](const QByteArray& v) {
                    bool ok = false;
                    const int raw = v.toInt(&ok);
                    return static_cast<quint16>(
                        clampInt(ok ? raw : m_signalingPort, 1, 65535));
                });
    envOverride("ACCESSTERMINAL_HARDWARE_SERIAL_PORT", m_serialPortName, toQString);
    envOverride("ACCESSTERMINAL_WEATHER_URL", m_weatherUrl, toQString);
    // 铃声音量：合法区间 [0,100]，非法文本 -> 0（静音，安全侧）。
    envOverride("ACCESSTERMINAL_MEDIA_RINGTONE_VOLUME", m_ringtoneVolume,
                [](const QByteArray& v) {
                    bool ok = false;
                    const int raw = v.toInt(&ok);
                    return clampInt(ok ? raw : 0, 0, 100);
                });
}

QByteArray AppConfig::lightCommand(const QString& name) const
{
    return m_lightCommands.value(name);
}

} // namespace accessterminal
