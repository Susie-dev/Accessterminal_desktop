/**
 * @file weather_service.h
 * @brief 天气信息获取。
 *
 * 把原实现中散落在 Widget 里的 QNetworkAccessManager/JSON 解析
 * 收敛为独立服务，UI 只接收格式化后的文本。
 */
#ifndef ACCESSTERMINAL_CORE_WEATHER_WEATHER_SERVICE_H
#define ACCESSTERMINAL_CORE_WEATHER_WEATHER_SERVICE_H

#include <QObject>
#include <QString>

class QNetworkAccessManager;
class QNetworkReply;

namespace accessterminal {

class WeatherService : public QObject
{
    Q_OBJECT

public:
    explicit WeatherService(QObject* parent = nullptr);
    ~WeatherService() override;

    /**
     * @brief 刷新天气。
     *
     * URL 取自 AppConfig.weather.url；为空则不做任何请求。
     * 同一时刻只保留一个在途请求，重复调用会先取消前一个。
     */
    void refresh();

signals:
    /// 解析成功，text 为可直接显示的天气文案。
    void weatherUpdated(const QString& text);
    /// 请求或解析失败。
    void errorOccurred(const QString& message);

private:
    void onFinished();

    QNetworkAccessManager* m_manager = nullptr;
    QNetworkReply* m_reply = nullptr;
};

} // namespace accessterminal

#endif // ACCESSTERMINAL_CORE_WEATHER_WEATHER_SERVICE_H
