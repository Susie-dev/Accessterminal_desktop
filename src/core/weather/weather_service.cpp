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
    if (m_reply) {
        m_reply->abort();
        m_reply->deleteLater();
        m_reply = nullptr;
    }
}

void WeatherService::refresh()
{
    const QString url = AppConfig::instance().weatherUrl();
    if (url.isEmpty()) {
        qDebug() << "[天气] 未配置天气接口，跳过刷新";
        return;
    }

    // 避免请求堆积：新请求前取消在途请求。
    if (m_reply) {
        m_reply->abort();
        m_reply->deleteLater();
        m_reply = nullptr;
    }

    m_reply = m_manager->get(QNetworkRequest(QUrl(url)));
    connect(m_reply, &QNetworkReply::finished, this, &WeatherService::onFinished);
}

void WeatherService::onFinished()
{
    QNetworkReply* reply = m_reply;
    m_reply = nullptr;
    if (!reply) {
        return;
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
