/**
 * @file weather_service.cpp
 * @brief WeatherService 实现。
 */
#include "core/weather/weather_service.h"

#include "config/app_config.h"

#include <QDebug>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QUrl>

namespace accessterminal {

WeatherService::WeatherService(QObject* parent)
    : QObject(parent)
{
    m_manager = new QNetworkAccessManager(this);
}

WeatherService::~WeatherService()
{
    abandonReply();
}

void WeatherService::refresh()
{
    const QString url = AppConfig::instance().weatherUrl();
    if (url.isEmpty()) {
        qDebug() << "[天气] 未配置天气接口，跳过刷新";
        return;
    }

    // 避免请求堆积：新请求前取消在途请求。
    abandonReply();

    m_reply = m_manager->get(QNetworkRequest(QUrl(url)));
    connect(m_reply, &QNetworkReply::finished, this, &WeatherService::onFinished);
}

/**
 * 安全地丢弃当前在途请求。
 *
 * 不能直接写成 `m_reply->abort(); m_reply->deleteLater();`：QNetworkReply
 * 的 abort() 可能**同步**投递 finished()，从而在此处重入 onFinished()。
 * 而 onFinished() 的第一件事就是把成员 m_reply 置空、并对它调用
 * deleteLater()。于是回到本函数继续执行 `m_reply->deleteLater()` 时，
 * m_reply 已经是 nullptr —— 空指针解引用。
 *
 * 因此顺序必须是：
 *   1. 先断开信号，杜绝任何重入；
 *   2. 把句柄从成员搬到局部变量，让 onFinished() 看到的状态始终一致；
 *   3. 再 abort()/deleteLater()。
 * 这样无论 abort() 是否同步发信号都安全。
 */
void WeatherService::abandonReply()
{
    if (!m_reply) {
        return;
    }
    QNetworkReply* reply = m_reply;
    m_reply = nullptr; // 先摘除成员，后续重入也看不到它
    disconnect(reply, nullptr, this, nullptr);
    reply->abort();
    reply->deleteLater();
}

void WeatherService::onFinished()
{
    // 用 sender() 而不是成员 m_reply 取回本次响应的句柄：
    // 若期间已经发起了新请求（refresh() 再次被调用），成员 m_reply 指向的
    // 是新请求，用成员就会把新请求误当成已完成的旧请求处理（提前置空、
    // 甚至误读它的 body）。sender() 始终指向真正发出 finished 的那个对象。
    QNetworkReply* reply = qobject_cast<QNetworkReply*>(sender());
    if (!reply) {
        return;
    }
    // 只有当前在途请求才需要清空成员；陈旧响应到这里时成员已指向别的
    // 请求或已被 abandonReply() 置空，不应被覆盖。
    if (m_reply == reply) {
        m_reply = nullptr;
    }
    reply->deleteLater();

    const int statusCode =
        reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
    if (reply->error() != QNetworkReply::NoError || statusCode != 200) {
        const QString msg = QStringLiteral("天气请求失败: %1 (HTTP %2)")
                                .arg(reply->errorString())
                                .arg(statusCode);
        qWarning() << "[天气]" << msg;
        emit errorOccurred(msg);
        return;
    }

    const QJsonDocument doc = QJsonDocument::fromJson(reply->readAll());
    if (!doc.isObject()) {
        emit errorOccurred(QStringLiteral("天气响应不是 JSON 对象"));
        return;
    }
    const QJsonObject root = doc.object();

    const QString city = root.value(QStringLiteral("cityInfo")).toObject()
                             .value(QStringLiteral("city")).toString();

    // forecast 为空数组时不应越界访问。
    const QJsonArray forecast = root.value(QStringLiteral("data")).toObject()
                                    .value(QStringLiteral("forecast")).toArray();
    if (forecast.isEmpty()) {
        emit errorOccurred(QStringLiteral("天气数据缺少预报内容"));
        return;
    }
    const QJsonObject today = forecast.at(0).toObject();

    const QString type = today.value(QStringLiteral("type")).toString();
    const QString high = today.value(QStringLiteral("high")).toString()
                             .remove(QStringLiteral("高温 "));
    const QString low = today.value(QStringLiteral("low")).toString()
                            .remove(QStringLiteral("低温 "));
    const QString wind = today.value(QStringLiteral("fx")).toString();
    const QString notice = today.value(QStringLiteral("notice")).toString();

    // 文案格式与重构前保持完全一致。
    const QString text =
        QStringLiteral("%1，今日天气%2，\n高温%3，低温%4，\n%5\n每日提醒：%6")
            .arg(city, type, high, low, wind, notice);

    emit weatherUpdated(text);
}

} // namespace accessterminal
