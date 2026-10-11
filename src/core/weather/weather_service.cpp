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
 * 的 abort() 会**同步**投递 finished()，从而在此处重入 onFinished()；
 * 而 onFinished() 的第一件事就是把成员 m_reply 置空。回到本函数继续执行时，
 * m_reply 已经被改了。
 *
 * 因此顺序必须是：
 *   1. 先断开信号，杜绝任何重入；
 *   2. 把句柄从成员搬到局部变量，让 onFinished() 看到的状态始终一致；
 *   3. 再 abort()/deleteLater()。
 * 这样无论 abort() 是否同步发信号都安全。
 *
 * 第 32 轮实测校准（原先的描述**不够准确**，此处按实测改写）
 * ------------------------------------------------------------------
 * 原先这里写的是"随后 `m_reply->deleteLater()` 就是**空指针解引用**"。
 * 探针实测（%TEMP%\probe32\）之后发现这句话一半对一半错：
 *
 *   实测 1（result11.txt）：`abort()` **确实同步**投递 finished() ——
 *     5/5 次，且"尚未收到任何数据"、"已收响应头但 body 未完成"、"已
 *     finished 之后"三种状态下都成立。**这段注释的前提是对的。**
 *
 *   实测 2（result12.txt）：但被预测的"空指针解引用**崩溃**"**没有复现**。
 *     `nullptr->deleteLater()` 形式上确是 UB，可 `QObject::deleteLater()`
 *     只是把指针丢进事件队列、并不解引用它，程序于是**侥幸活着**。
 *     把"UB"说成"必然崩溃"是**过头**的，容易让后来者做出错误判断
 *     （例如据此认为这条路径不可达，或反过来把防御删掉）。
 *
 *   实测 3（result13.txt）：真正的、**用户可见**的后果是**假错误**：
 *       正确顺序（先断连接 + 先摘成员）：finished 处理 0 次，错误信号 0 个
 *       错误顺序（直接 abort）        ：finished 处理 1 次，错误信号 1 个
 *                                       消息 = "天气请求失败: Operation canceled (HTTP 200)"
 *     同步重入让 onFinished() 看到 `error == OperationCanceledError`，于是
 *     emit errorOccurred —— **每次刷新天气取消上一个在途请求，界面都会闪
 *     一条"天气请求失败"**，而实际上并没有失败。
 *     这才是本函数真正在挡的东西，也正是单元测试
 *     `refreshCancelsInFlightWithoutFalseError` 所钉住的差异。
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
        // 约定：**错误日志由发出它的模块自己负责**。本文件里每一处
        // `emit errorOccurred` 都先 log 一遍，UI 侧不再重复打印。
        // 此前这两处只 emit 不 log，靠 Widget 兜底 —— 于是同一个天气错误
        // 时而打印两遍（走上面的分支）、时而一遍（走这里），
        // 现场看不出规律。补齐后全类一致。
        const QString msg = QStringLiteral("天气响应不是 JSON 对象");
        qWarning() << "[天气]" << msg;
        emit errorOccurred(msg);
        return;
    }
    const QJsonObject root = doc.object();

    const QString city = root.value(QStringLiteral("cityInfo")).toObject()
                             .value(QStringLiteral("city")).toString();

    // forecast 为空数组时不应越界访问。
    const QJsonArray forecast = root.value(QStringLiteral("data")).toObject()
                                    .value(QStringLiteral("forecast")).toArray();
    if (forecast.isEmpty()) {
        const QString msg = QStringLiteral("天气数据缺少预报内容");
        qWarning() << "[天气]" << msg;
        emit errorOccurred(msg);
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
