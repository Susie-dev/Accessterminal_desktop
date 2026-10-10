/**
 * @file test_weather_service.cpp
 * @brief WeatherService（天气获取与文案格式化）行为断言。
 *
 * 为什么必须写这个测试
 * --------------------
 * `src/core/weather/weather_service.cpp` 此前**从未被任何测试目标链接**
 * （README 的"从未链接"清单里待了很久）。它做三件都会伤到用户的事：
 *
 *   1. 解析第三方 JSON 并**拼出用户直接看到的文案**；
 *   2. 管着一个在途的 `QNetworkReply`，要处理"新请求取消旧请求"；
 *   3. 出错时 emit `errorOccurred`，界面据此提示用户。
 *
 * 而它代码里那段最长的注释（`abandonReply()` 上方）断言的是一条
 * **从未被验证过的因果链**。本测试的起因就是去验它。
 *
 * 起因：一条写着"不能这样写"但从未被验证的注释
 * --------------------------------------------
 * 原注释说：不能写成 `m_reply->abort(); m_reply->deleteLater();`，因为
 * `abort()` 可能**同步**投递 `finished()` 从而重入 `onFinished()`，把
 * `m_reply` 置空，随后那行 `deleteLater()` 就是空指针解引用。
 *
 * 第 32 轮用探针实测了这条链（`%TEMP%\probe32\`）：
 *
 *   实测 1（result11.txt）：`abort()` **确实同步**投递 `finished()` ——
 *     5/5 次，在"尚未收到任何数据"、"已收响应头但 body 未完成"、"已
 *     finished 之后"三种状态下都成立。**注释的前提是对的。**
 *   实测 2（result12.txt）：但预测的"空指针解引用**崩溃**"**没有复现** ——
 *     `nullptr->deleteLater()` 是 UB，而 `QObject::deleteLater()` 只是把
 *     指针丢进事件队列、并不解引用，于是"侥幸活着"。
 *     **注释描述的具体后果过强了。**
 *   实测 3（result13.txt）：真正的、可观测的后果是**假错误**：
 *       正确顺序（先断连接 + 先摘成员）：finished 处理 0 次，错误信号 0 个
 *       错误顺序（直接 abort）        ：finished 处理 1 次，错误信号 1 个
 *                                       消息 = "天气请求失败: Operation canceled (HTTP 200)"
 *     `abort()` 同步触发 `onFinished()`，那里看到
 *     `error == OperationCanceledError` 就 emit `errorOccurred`。
 *     也就是说：**每次刷新天气取消上一个在途请求，界面都会闪一条假错误。**
 *
 * 所以本测试守的是实测 3 那条真实差异
 * （`refreshCancelsInFlightWithoutFalseError`），而不是一条不成立的崩溃断言。
 * 原注释已按实测改写（见 weather_service.cpp）。
 *
 * 测试方式：真实 HTTP 服务端 + 真实事件循环
 * ----------------------------------------
 * 不用 mock 网络，也不直接调私有槽。而是：
 *
 *   1. 起一个**真的** `QTcpServer`（绑定 127.0.0.1 的临时端口）当天气接口；
 *   2. 通过 `ACCESSTERMINAL_WEATHER_URL` 把 `AppConfig` 的 URL 指到它；
 *   3. WeatherService 用真实 `QNetworkAccessManager` 走真实 HTTP；
 *   4. 断言落在**信号**上（`weatherUpdated` / `errorOccurred`），也就是
 *      UI 真正消费的东西。
 *
 * 服务端可以只发响应头、把 body 挂着不发 —— 这样就能稳定造出
 * "请求在途但未完成"那一刻，从而真正走到取消逻辑，而不是靠 sleep 撞运气。
 *
 * 代码里若干实测边界（免得以后被"顺手简化"掉）
 * ------------------------------------------
 *   - 文案格式是与重构前逐字符一致的，**不是**随便拼的：见
 *     `successfulResponseEmitsExactText` 里那个独立写死的期望串。
 *   - `high`/`low` 用 `QString::remove("高温 ")`，是删除**所有**出现，
 *     不是只删前缀。测试按此断言。
 *   - `forecast` 只用第 0 项，多余项被忽略。
 */
#include <QCoreApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QHostAddress>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMap>
#include <QNetworkProxy>
#include <QSignalSpy>
#include <QStringList>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTest>

#include "config/app_config.h"
#include "core/weather/weather_service.h"

using namespace accessterminal;

namespace {

/// 等到条件成立，或超时。**等属性，不等固定时长。**
template <typename Predicate>
bool waitFor(Predicate pred, int timeoutMs = 8000)
{
    QElapsedTimer timer;
    timer.start();
    while (timer.elapsed() < timeoutMs) {
        if (pred()) {
            return true;
        }
        QTest::qWait(5);
    }
    return pred();
}

/// 构造一份天气接口的 JSON 响应体（走 Qt 自己的 JSON 生成器，
/// 不手搓字符串，避免转义/编码问题掩盖被测逻辑）。
QByteArray weatherJson(const QString& city,
                       const QString& type,
                       const QString& high,
                       const QString& low,
                       const QString& fx,
                       const QString& notice,
                       int forecastCount = 1)
{
    QJsonArray forecast;
    for (int i = 0; i < forecastCount; ++i) {
        QJsonObject day;
        if (i == 0) {
            day.insert(QStringLiteral("type"), type);
            day.insert(QStringLiteral("high"), high);
            day.insert(QStringLiteral("low"), low);
            day.insert(QStringLiteral("fx"), fx);
            day.insert(QStringLiteral("notice"), notice);
        } else {
            // 后续项刻意用完全不同的值：若实现误取第 1 项，文案会明显不同。
            day.insert(QStringLiteral("type"), QStringLiteral("【不该出现】"));
            day.insert(QStringLiteral("high"), QStringLiteral("高温 999℃"));
            day.insert(QStringLiteral("low"), QStringLiteral("低温 -999℃"));
            day.insert(QStringLiteral("fx"), QStringLiteral("【不该出现】"));
            day.insert(QStringLiteral("notice"), QStringLiteral("【不该出现】"));
        }
        forecast.append(day);
    }

    QJsonObject data;
    data.insert(QStringLiteral("forecast"), forecast);

    QJsonObject cityInfo;
    cityInfo.insert(QStringLiteral("city"), city);

    QJsonObject root;
    root.insert(QStringLiteral("cityInfo"), cityInfo);
    root.insert(QStringLiteral("data"), data);

    return QJsonDocument(root).toJson(QJsonDocument::Compact);
}

} // namespace

/**
 * @brief 假天气接口：一个真实的 QTcpServer，可以精确控制"何时回、回什么"。
 *
 * 关键能力是 `HeadersOnly`：只把响应头发出去、body 一直不发。
 * 这样被测服务会稳定停在"请求在途且未完成"这一刻，
 * 取消逻辑（abandonReply）才能被**确定性地**走到。
 */
class FakeWeatherServer : public QObject
{
    Q_OBJECT

public:
    enum Behavior {
        Reply,             ///< 完整回一份响应
        HeadersOnly,       ///< 只回响应头，body 挂着不发
        Silent,            ///< 什么都不回，连接挂着
        CloseWithoutReply  ///< 直接断开（制造网络错误）
    };

    explicit FakeWeatherServer(QObject* parent = nullptr)
        : QObject(parent)
    {
        m_server = new QTcpServer(this);
        connect(m_server, &QTcpServer::newConnection,
                this, &FakeWeatherServer::onNewConnection);
    }

    bool listen()
    {
        m_listening = m_server->listen(QHostAddress::LocalHost, 0);
        return m_listening;
    }

    bool isListening() const { return m_listening; }
    quint16 port() const { return m_server->serverPort(); }

    /// 供 AppConfig 使用的完整 URL。
    QString url(const QString& path = QStringLiteral("/api/weather")) const
    {
        return QStringLiteral("http://127.0.0.1:%1%2")
            .arg(m_server->serverPort())
            .arg(path);
    }

    void setBehavior(Behavior b) { m_behavior = b; }

    void setReply(int status, const QByteArray& body,
                  const QByteArray& contentType = QByteArrayLiteral("application/json"))
    {
        m_status = status;
        m_body = body;
        m_contentType = contentType;
    }

    int requestCount() const { return m_requests.size(); }
    QByteArray requestAt(int i) const { return m_requests.value(i); }

    /// 已收到的请求行里的路径部分（GET 后面的那一串）。
    QStringList requestTargets() const
    {
        QStringList out;
        for (const QByteArray& r : m_requests) {
            const QList<QByteArray> parts = r.split(' ');
            if (parts.size() >= 2) {
                out << QString::fromLatin1(parts.at(1));
            }
        }
        return out;
    }

    bool waitForRequests(int n, int timeoutMs = 8000)
    {
        return waitFor([&]() { return m_requests.size() >= n; }, timeoutMs);
    }

    /// 把当前挂着的连接数（用于判断"取消"是否真的让 socket 断开）。
    int liveSocketCount() const { return m_buffers.size(); }

private slots:
    void onNewConnection()
    {
        QTcpSocket* sock = m_server->nextPendingConnection();
        m_buffers.insert(sock, QByteArray());
        connect(sock, &QTcpSocket::readyRead, this,
                [this, sock]() { onReadyRead(sock); });
        connect(sock, &QTcpSocket::disconnected, this, [this, sock]() {
            // 必须把**两张**表里的键都删掉，不能只删 m_buffers。
            //
            // 实测教训（本条用例曾 2/15 次随机失败）：
            // `m_answered` 用**裸指针**做键，而 socket 是 `deleteLater()` 释放的。
            // 只删 m_buffers 的话，m_answered 里会留下**悬空键**；堆地址被
            // 复用后，新建的 socket 很可能拿到同一个地址，于是
            // `m_answered.contains(sock)` 命中旧记录 -> `respond()` 永远不被
            // 调用 -> 客户端一直等不到响应，直到 8 秒超时失败。
            // 表现就是"偶发失败、单独跑又过"—— 极容易被误判成被测代码有竞态。
            m_buffers.remove(sock);
            m_answered.remove(sock);
            sock->deleteLater();
        });
    }

    void onReadyRead(QTcpSocket* sock)
    {
        QByteArray& buf = m_buffers[sock];
        buf += sock->readAll();
        // 请求头收全了才算是"一个完整请求"。
        if (buf.contains("\r\n\r\n") && !m_answered.contains(sock)) {
            m_requests.append(buf);
            m_answered.insert(sock, true);
            respond(sock);
        }
    }

private:
    void respond(QTcpSocket* sock)
    {
        switch (m_behavior) {
        case Silent:
            return;
        case CloseWithoutReply:
            sock->disconnectFromHost();
            return;
        case HeadersOnly:
            sock->write("HTTP/1.1 200 OK\r\n"
                        "Content-Type: application/json\r\n"
                        "Content-Length: 100\r\n\r\n");
            sock->flush();
            return;
        case Reply:
            break;
        }

        QByteArray head = QByteArrayLiteral("HTTP/1.1 ")
                          + QByteArray::number(m_status) + QByteArrayLiteral(" X\r\n");
        head += QByteArrayLiteral("Content-Type: ") + m_contentType + QByteArrayLiteral("\r\n");
        head += QByteArrayLiteral("Content-Length: ")
                + QByteArray::number(m_body.size()) + QByteArrayLiteral("\r\n");
        head += QByteArrayLiteral("Connection: close\r\n\r\n");
        sock->write(head);
        sock->write(m_body);
        sock->flush();
    }

    QTcpServer* m_server = nullptr;
    bool m_listening = false;
    Behavior m_behavior = Reply;
    int m_status = 200;
    QByteArray m_body;
    QByteArray m_contentType = QByteArrayLiteral("application/json");

    QList<QByteArray> m_requests;
    QMap<QTcpSocket*, QByteArray> m_buffers;
    QMap<QTcpSocket*, bool> m_answered;
};

class TestWeatherService : public QObject
{
    Q_OBJECT

private slots:
    void initTestCase();

    // ---- 夹具自证 ----
    void configFixtureRoundTripsTheUrl();
    void configFileCanSetEmptyUrl();
    void constructionDoesNotMakeRequest();

    // ---- 请求发出与取消 ----
    void emptyUrlMakesNoRequest();
    void emptyUrlEmitsNoError();
    void refreshIssuesGetToConfiguredPath();
    void secondRefreshReplacesInFlightRequest();

    // ---- 成功路径：文案 ----
    void successfulResponseEmitsExactText();
    void textStripsHighLowLabels();
    void textUsesOnlyFirstForecastEntry();
    void textToleratesMissingCity();
    void exactlyOneWeatherUpdatedPerResponse();

    // ---- 失败路径 ----
    void httpErrorEmitsErrorOccurred();
    void httpErrorMentionsStatusCode();
    void networkErrorEmitsErrorOccurred();
    void nonJsonBodyEmitsError();
    void jsonArrayBodyEmitsError();
    void emptyForecastEmitsError();

    // ---- 取消在途请求（本测试的核心，见文件头实测 3）----
    void refreshCancelsInFlightWithoutFalseError();
    void cancelInvalidatesTheCancelledReply();
    void cancelThenNewRequestStillDelivers();
    void cancelDoesNotEmitLateWeatherUpdated();

    // ---- 生命周期 ----
    void destructorWithInFlightRequestIsSafe();
    void destructorWithoutRequestIsSafe();
    void refreshAfterSuccessStartsFreshRequest();

private:
    /// 把 AppConfig 的天气 URL 指到假服务端。
    /// 传入一个不存在的文件路径，使 load() 走"内置默认值 + 环境变量覆盖"，
    /// 不依赖测试的工作目录里有没有 appconfig.json。
    void useUrl(const QString& url);

    /// 通过**真实配置文件**把天气 URL 设成指定值。
    ///
    /// 为什么需要它（而不是再走环境变量）：`envOverride()` 的判据是
    /// `if (!value.isEmpty())`，即**空串等于"没设置"**。所以"URL 为空"
    /// 这一状态**无法**用环境变量构造出来，只能走配置文件这一条路。
    /// 写死这个区别，是为了不写出"看上去在测空 URL、其实测的是空环境变量
    /// 被忽略"那种名不副实的用例（第 31 轮踩过同类坑）。
    void useConfigFileUrl(const QString& url);

    FakeWeatherServer* m_server = nullptr;
};

void TestWeatherService::initTestCase()
{
    // 假接口一定在 127.0.0.1 上。若系统里配了代理（本机就有 7890 端口
    // 的代理），走代理就会连不上或连到别处，测试结果取决于机器配置。
    // 显式禁用代理，让测试只依赖被测逻辑。
    QNetworkProxy::setApplicationProxy(QNetworkProxy(QNetworkProxy::NoProxy));
}

void TestWeatherService::useUrl(const QString& url)
{
    qputenv("ACCESSTERMINAL_WEATHER_URL", url.toLocal8Bit());
    // 显式给一个不存在的文件：load() 会跳过文件、直接落到 applyEnvironment()，
    // 于是天气 URL 完全由环境变量决定，与工作目录无关。
    AppConfig::instance().load(QStringLiteral("__no_such_config__.json"));
}

void TestWeatherService::useConfigFileUrl(const QString& url)
{
    // 环境变量必须清掉，否则它会在 applyEnvironment() 里覆盖掉文件里的值
    // （including 覆盖成非空），让本函数失去意义。
    qunsetenv("ACCESSTERMINAL_WEATHER_URL");

    const QString path = QDir::temp().filePath(
        QStringLiteral("accessterminal_weather_test_%1.json")
            .arg(QCoreApplication::applicationPid()));

    QJsonObject weather;
    weather.insert(QStringLiteral("url"), url);
    QJsonObject root;
    root.insert(QStringLiteral("weather"), weather);

    QFile f(path);
    QVERIFY2(f.open(QIODevice::WriteOnly | QIODevice::Truncate),
             qPrintable(path));
    f.write(QJsonDocument(root).toJson(QJsonDocument::Compact));
    f.close();

    const bool loaded = AppConfig::instance().load(path);
    QVERIFY2(loaded, qPrintable(QStringLiteral("配置文件未被接受: %1").arg(path)));
    // 自证：加载后 URL 必须**恰好**是我们写进去的值（含空串）。
    QCOMPARE(AppConfig::instance().weatherUrl(), url);
    QFile::remove(path);
}

// ---------------------------------------------------------------------------
// 夹具自证：先证明"URL 确实按我们给的值生效了"。
//
// 必要性：这条测试之外的所有用例都建立在"AppConfig 会返回假服务端的 URL"
// 之上。若环境变量名写错、或 AppConfig 某天不再读这个变量，那么所有用例
// 都会去连真·第三方接口 —— 表现是"随机失败"或"全部超时"，
// 很容易被误判成被测代码有问题。先自证，失败信息才指向夹具本身。
// ---------------------------------------------------------------------------
void TestWeatherService::configFixtureRoundTripsTheUrl()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    const QString url = server.url(QStringLiteral("/api/weather?city=test"));
    useUrl(url);

    QCOMPARE(AppConfig::instance().weatherUrl(), url);
}

void TestWeatherService::configFileCanSetEmptyUrl()
{
    // 自证：配置文件这条路**确实**能把 URL 置空。
    // 没有这条，emptyUrlMakesNoRequest 可能因为"夹具根本设不进空值"
    // 而变成一个永远测不到目标的假用例（它仍然会通过）。
    useConfigFileUrl(QString());
    QVERIFY(AppConfig::instance().weatherUrl().isEmpty());

    // 顺带证明非空值也照常生效，排除"配置文件根本没被读"。
    useConfigFileUrl(QStringLiteral("http://127.0.0.1:1/x"));
    QCOMPARE(AppConfig::instance().weatherUrl(),
             QStringLiteral("http://127.0.0.1:1/x"));
}

void TestWeatherService::constructionDoesNotMakeRequest()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());

    {
        WeatherService service;
        QSignalSpy updated(&service, &WeatherService::weatherUpdated);
        QSignalSpy errors(&service, &WeatherService::errorOccurred);
        // 只构造、不 refresh()：不应有任何网络行为。
        QTest::qWait(300);
        QCOMPARE(server.requestCount(), 0);
        QCOMPARE(updated.count(), 0);
        QCOMPARE(errors.count(), 0);
    }
}

void TestWeatherService::emptyUrlMakesNoRequest()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());

    // 通过**真实配置文件**把 url 设成空串（环境变量做不到这件事：
    // envOverride 把空串当成"没设置"，见 useConfigFileUrl 的说明）。
    useConfigFileUrl(QString());

    WeatherService service;
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);
    QSignalSpy errors(&service, &WeatherService::errorOccurred);
    service.refresh();

    // 给足"本该发出请求"的时间。
    QTest::qWait(600);
    QCOMPARE(server.requestCount(), 0);
    QCOMPARE(updated.count(), 0);
    QCOMPARE(errors.count(), 0);
}

void TestWeatherService::emptyUrlEmitsNoError()
{
    // 与上一条配对，但断言的是"环境变量里的空值被忽略"这条**继承来的**边界：
    // envOverride 的判据是 `if (!value.isEmpty())`。若哪天改成允许空覆盖，
    // 这条会失败，提醒我们 emptyUrlMakesNoRequest 的构造方式仍需有效
    // （它走的是配置文件，不受影响），而"空环境变量=不覆盖"这个假设变了。
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());
    QVERIFY(!AppConfig::instance().weatherUrl().isEmpty());

    // 现在把环境变量设成空串，再 load 一次：URL 应**仍然**是非空的。
    qputenv("ACCESSTERMINAL_WEATHER_URL", QByteArray());
    AppConfig::instance().load(QStringLiteral("__no_such_config__.json"));
    QVERIFY2(!AppConfig::instance().weatherUrl().isEmpty(),
             "空环境变量不应覆盖已有 URL（envOverride 把空串当作未设置）");
}

void TestWeatherService::refreshIssuesGetToConfiguredPath()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    const QString path = QStringLiteral("/api/weather/city/101230101");
    useUrl(server.url(path));

    server.setBehavior(FakeWeatherServer::Reply);
    server.setReply(200, weatherJson(QStringLiteral("厦门"), QStringLiteral("晴"),
                                     QStringLiteral("高温 25℃"),
                                     QStringLiteral("低温 15℃"),
                                     QStringLiteral("东风3级"),
                                     QStringLiteral("注意防晒")));

    WeatherService service;
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);
    service.refresh();

    QVERIFY(server.waitForRequests(1));
    // 请求行必须是 GET，且打到配置里那个路径上（含查询串）。
    const QByteArray req = server.requestAt(0);
    QVERIFY2(req.startsWith("GET "), req.left(40).constData());
    QCOMPARE(server.requestTargets().at(0), path);
    QVERIFY(waitFor([&]() { return updated.count() > 0; }));
}

void TestWeatherService::successfulResponseEmitsExactText()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());

    server.setBehavior(FakeWeatherServer::Reply);
    server.setReply(200, weatherJson(QStringLiteral("厦门"), QStringLiteral("晴"),
                                     QStringLiteral("高温 25℃"),
                                     QStringLiteral("低温 15℃"),
                                     QStringLiteral("东风3级"),
                                     QStringLiteral("注意防晒")));

    WeatherService service;
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);
    QSignalSpy errors(&service, &WeatherService::errorOccurred);
    service.refresh();

    QVERIFY(waitFor([&]() { return updated.count() > 0 || errors.count() > 0; }));
    QCOMPARE(errors.count(), 0);
    QCOMPARE(updated.count(), 1);

    // 期望串是**独立写死**的，不是照着实现再拼一遍 —— 否则实现怎么改测试
    // 都跟着改，等于没测。格式取自重构前基线，逐字符一致。
    const QString expected = QStringLiteral(
        "厦门，今日天气晴，\n"
        "高温25℃，低温15℃，\n"
        "东风3级\n"
        "每日提醒：注意防晒");
    QCOMPARE(updated.at(0).at(0).toString(), expected);
}

void TestWeatherService::textStripsHighLowLabels()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());

    // "高温 25℃高温 26℃" -> remove("高温 ") 删除**所有**出现 -> "25℃26℃"
    // 实测边界：remove 不是"只删前缀"，而是删全部。措辞按此钉住。
    server.setBehavior(FakeWeatherServer::Reply);
    server.setReply(200, weatherJson(QStringLiteral("北京"), QStringLiteral("多云"),
                                     QStringLiteral("高温 25℃高温 26℃"),
                                     QStringLiteral("低温 15℃"),
                                     QStringLiteral("微风"),
                                     QStringLiteral("适宜出行")));

    WeatherService service;
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);
    service.refresh();
    QVERIFY(waitFor([&]() { return updated.count() > 0; }));

    const QString text = updated.at(0).at(0).toString();
    QCOMPARE(text, QStringLiteral(
                      "北京，今日天气多云，\n"
                      "高温25℃26℃，低温15℃，\n"
                      "微风\n"
                      "每日提醒：适宜出行"));
}

void TestWeatherService::textUsesOnlyFirstForecastEntry()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());

    // 第 1 项的值都是"【不该出现】"，只要它出现在文案里就说明取错了下标。
    server.setBehavior(FakeWeatherServer::Reply);
    server.setReply(200, weatherJson(QStringLiteral("上海"), QStringLiteral("雨"),
                                     QStringLiteral("高温 20℃"),
                                     QStringLiteral("低温 12℃"),
                                     QStringLiteral("东北风"),
                                     QStringLiteral("带伞"),
                                     5));

    WeatherService service;
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);
    service.refresh();
    QVERIFY(waitFor([&]() { return updated.count() > 0; }));

    const QString text = updated.at(0).at(0).toString();
    QVERIFY2(!text.contains(QStringLiteral("不该出现")), qPrintable(text));
    QVERIFY2(!text.contains(QStringLiteral("999")), qPrintable(text));
    QVERIFY2(text.startsWith(QStringLiteral("上海，今日天气雨，")), qPrintable(text));
}

void TestWeatherService::textToleratesMissingCity()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());

    // 缺 cityInfo：city 应是空串，其余照常，不应崩、不应报错。
    QJsonObject data;
    QJsonArray forecast;
    QJsonObject day;
    day.insert(QStringLiteral("type"), QStringLiteral("阴"));
    day.insert(QStringLiteral("high"), QStringLiteral("高温 18℃"));
    day.insert(QStringLiteral("low"), QStringLiteral("低温 9℃"));
    day.insert(QStringLiteral("fx"), QStringLiteral("无持续风向"));
    day.insert(QStringLiteral("notice"), QStringLiteral("较舒适"));
    forecast.append(day);
    data.insert(QStringLiteral("forecast"), forecast);
    QJsonObject root;
    root.insert(QStringLiteral("data"), data);

    server.setBehavior(FakeWeatherServer::Reply);
    server.setReply(200, QJsonDocument(root).toJson(QJsonDocument::Compact));

    WeatherService service;
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);
    QSignalSpy errors(&service, &WeatherService::errorOccurred);
    service.refresh();
    QVERIFY(waitFor([&]() { return updated.count() > 0 || errors.count() > 0; }));

    QCOMPARE(errors.count(), 0);
    QCOMPARE(updated.count(), 1);
    QCOMPARE(updated.at(0).at(0).toString(), QStringLiteral(
                 "，今日天气阴，\n"
                 "高温18℃，低温9℃，\n"
                 "无持续风向\n"
                 "每日提醒：较舒适"));
}

void TestWeatherService::exactlyOneWeatherUpdatedPerResponse()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());

    server.setBehavior(FakeWeatherServer::Reply);
    server.setReply(200, weatherJson(QStringLiteral("广州"), QStringLiteral("晴"),
                                     QStringLiteral("高温 30℃"),
                                     QStringLiteral("低温 22℃"),
                                     QStringLiteral("南风"),
                                     QStringLiteral("注意补水")));

    WeatherService service;
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);
    service.refresh();
    QVERIFY(waitFor([&]() { return updated.count() > 0; }));
    // 再等一段，确认没有"重复上报"（例如 finished 被处理两次）。
    QTest::qWait(500);
    QCOMPARE(updated.count(), 1);
}

void TestWeatherService::httpErrorEmitsErrorOccurred()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());

    server.setBehavior(FakeWeatherServer::Reply);
    server.setReply(500, QByteArrayLiteral("{\"error\":\"boom\"}"));

    WeatherService service;
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);
    QSignalSpy errors(&service, &WeatherService::errorOccurred);
    service.refresh();
    QVERIFY(waitFor([&]() { return errors.count() > 0 || updated.count() > 0; }));

    QCOMPARE(updated.count(), 0);
    QCOMPARE(errors.count(), 1);
}

void TestWeatherService::httpErrorMentionsStatusCode()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());

    server.setBehavior(FakeWeatherServer::Reply);
    server.setReply(503, QByteArrayLiteral("{}"));

    WeatherService service;
    QSignalSpy errors(&service, &WeatherService::errorOccurred);
    service.refresh();
    QVERIFY(waitFor([&]() { return errors.count() > 0; }));

    // 文案要能让人定位问题：必须带上 HTTP 状态码。
    const QString msg = errors.at(0).at(0).toString();
    QVERIFY2(msg.contains(QStringLiteral("503")), qPrintable(msg));
    QVERIFY2(msg.contains(QStringLiteral("天气请求失败")), qPrintable(msg));
}

void TestWeatherService::networkErrorEmitsErrorOccurred()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    const QString url = server.url();
    useUrl(url);

    server.setBehavior(FakeWeatherServer::CloseWithoutReply);

    WeatherService service;
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);
    QSignalSpy errors(&service, &WeatherService::errorOccurred);
    service.refresh();

    // 这条曾经偶发失败（1/15 次）。失败时把夹具状态一并打出来，
    // 否则只能看到一句 "waitFor returned FALSE"，无从判断是夹具没收到
    // 请求、还是真的没报错 —— 而这两者的修法完全不同。
    const bool got = waitFor([&]() {
        return errors.count() > 0 || updated.count() > 0;
    });
    QVERIFY2(got, qPrintable(
                 QStringLiteral("既没报错也没成功；URL=%1 请求数=%2 "
                                "活连接=%3 错误数=%4")
                     .arg(url)
                     .arg(server.requestCount())
                     .arg(server.liveSocketCount())
                     .arg(errors.count())));

    QCOMPARE(updated.count(), 0);
    QCOMPARE(errors.count(), 1);
}

void TestWeatherService::nonJsonBodyEmitsError()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());

    server.setBehavior(FakeWeatherServer::Reply);
    server.setReply(200, QByteArrayLiteral("this is not json at all"));

    WeatherService service;
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);
    QSignalSpy errors(&service, &WeatherService::errorOccurred);
    service.refresh();
    QVERIFY(waitFor([&]() { return errors.count() > 0 || updated.count() > 0; }));

    QCOMPARE(updated.count(), 0);
    QCOMPARE(errors.count(), 1);
    QVERIFY2(errors.at(0).at(0).toString().contains(QStringLiteral("JSON")),
             qPrintable(errors.at(0).at(0).toString()));
}

void TestWeatherService::jsonArrayBodyEmitsError()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());

    // 合法 JSON，但顶层是数组而不是对象 —— 必须走错误分支，不能越界/崩溃。
    server.setBehavior(FakeWeatherServer::Reply);
    server.setReply(200, QByteArrayLiteral("[1,2,3]"));

    WeatherService service;
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);
    QSignalSpy errors(&service, &WeatherService::errorOccurred);
    service.refresh();
    QVERIFY(waitFor([&]() { return errors.count() > 0 || updated.count() > 0; }));

    QCOMPARE(updated.count(), 0);
    QCOMPARE(errors.count(), 1);
}

void TestWeatherService::emptyForecastEmitsError()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());

    // forecast 为空数组：基线注释特别提到"不应越界访问"。
    server.setBehavior(FakeWeatherServer::Reply);
    server.setReply(200, weatherJson(QStringLiteral("深圳"), QStringLiteral("晴"),
                                     QStringLiteral("高温 28℃"),
                                     QStringLiteral("低温 20℃"),
                                     QStringLiteral("东风"),
                                     QStringLiteral("舒适"),
                                     0)); // 0 项

    WeatherService service;
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);
    QSignalSpy errors(&service, &WeatherService::errorOccurred);
    service.refresh();
    QVERIFY(waitFor([&]() { return errors.count() > 0 || updated.count() > 0; }));

    QCOMPARE(updated.count(), 0);
    QCOMPARE(errors.count(), 1);
}

// ---------------------------------------------------------------------------
// 本测试的核心（见文件头"实测 3"）。
//
// 取消一个**在途**请求时，绝不能因为"取消"本身而 emit errorOccurred。
//
// 实测依据：abort() 会**同步**投递 finished()。
//   - 正确顺序（先 disconnect、先摘成员）：finished 到不了 onFinished
//     -> 错误信号 0 个；
//   - 错误顺序（直接 abort）：onFinished 看到 OperationCanceledError
//     -> 错误信号 1 个，文案 "天气请求失败: Operation canceled (HTTP 200)"。
//
// 用 service.refresh() 本身作为"取消旧请求"的触发点（这正是产线路径：
// 定时刷新时上一个请求可能还没回来）。
//
// 正对照：`httpErrorEmitsErrorOccurred` 证明本文件的 errorOccurred 探针
// 在**真的有错**时确实会响 —— 否则这里的"0 个错误"就是假绿。
// ---------------------------------------------------------------------------
void TestWeatherService::refreshCancelsInFlightWithoutFalseError()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());

    // 只发响应头、body 挂着：请求停在"在途未完成"。
    server.setBehavior(FakeWeatherServer::HeadersOnly);

    WeatherService service;
    QSignalSpy errors(&service, &WeatherService::errorOccurred);
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);

    service.refresh();
    QVERIFY(server.waitForRequests(1));
    // 等到响应头真的被处理过（此刻才处于"能同步 finished"的状态）。
    QTest::qWait(300);
    QCOMPARE(errors.count(), 0);

    // 第二次刷新：内部会先取消第一个在途请求。
    service.refresh();
    QTest::qWait(300);

    QVERIFY2(errors.count() == 0,
             qPrintable(QStringLiteral("取消在途请求不应报错，却收到 %1 条：%2")
                            .arg(errors.count())
                            .arg(errors.isEmpty()
                                     ? QString()
                                     : errors.at(0).at(0).toString())));
    QCOMPARE(updated.count(), 0);
}

void TestWeatherService::cancelInvalidatesTheCancelledReply()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());
    server.setBehavior(FakeWeatherServer::HeadersOnly);

    WeatherService service;
    QSignalSpy errors(&service, &WeatherService::errorOccurred);

    service.refresh();
    QVERIFY(server.waitForRequests(1));
    QTest::qWait(300);

    // 反复取消：内部顺序若会被重入打乱，异常会在多次之后暴露得更明显。
    for (int i = 0; i < 5; ++i) {
        service.refresh();
        QTest::qWait(60);
    }
    QVERIFY2(errors.count() == 0,
             qPrintable(QStringLiteral("反复取消产生了 %1 条错误信号")
                            .arg(errors.count())));
}

/**
 * 第二次 refresh() 必须**替换**在途请求，而不是让两个请求并存。
 *
 * 判据分两半：
 *   1. 服务端确实收到了**第二个**请求；
 *   2. 原来的连接被取消 —— 这一点从服务端侧看是"那条 socket 断开了"。
 *
 * 第 2 条是真正区分"替换"与"并存"的地方：若实现只是又发一个 get() 而不
 * 取消旧的（即 abandonReply() 被删掉/空实现），两个请求会同时在途，
 * 服务端会看到 2 条**活着的**连接。这里等它掉到 1 条。
 *
 * 注意不能只断言 requestCount()==2 —— 那只说明"发了两次"，
 * 不说明"旧的被取消了"。
 */
void TestWeatherService::secondRefreshReplacesInFlightRequest()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());
    server.setBehavior(FakeWeatherServer::HeadersOnly);

    WeatherService service;
    QSignalSpy errors(&service, &WeatherService::errorOccurred);

    service.refresh();
    QVERIFY(server.waitForRequests(1));
    QTest::qWait(300);
    QCOMPARE(server.liveSocketCount(), 1);

    service.refresh();
    QVERIFY(server.waitForRequests(2));

    // 旧连接应当被取消（abort -> 服务端看到断开）。
    // 允许短暂延迟：断开是异步的网络事件。
    QVERIFY2(waitFor([&]() { return server.liveSocketCount() <= 1; }, 3000),
             qPrintable(QStringLiteral("取消旧请求后仍有 %1 条活连接 —— "
                                       "说明新旧请求并存，旧请求没被取消")
                            .arg(server.liveSocketCount())));
    QCOMPARE(errors.count(), 0);
}

void TestWeatherService::cancelThenNewRequestStillDelivers()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());

    // 第一个请求挂着不回，第二个才正常回。
    server.setBehavior(FakeWeatherServer::HeadersOnly);

    WeatherService service;
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);
    QSignalSpy errors(&service, &WeatherService::errorOccurred);

    service.refresh();
    QVERIFY(server.waitForRequests(1));
    QTest::qWait(250);

    // 让第二个请求得到完整响应。
    server.setBehavior(FakeWeatherServer::Reply);
    server.setReply(200, weatherJson(QStringLiteral("杭州"), QStringLiteral("晴"),
                                     QStringLiteral("高温 26℃"),
                                     QStringLiteral("低温 16℃"),
                                     QStringLiteral("西风"),
                                     QStringLiteral("适合外出")));
    service.refresh();

    QVERIFY(server.waitForRequests(2));
    QVERIFY(waitFor([&]() { return updated.count() > 0; }));

    // 取消旧请求不能影响新请求拿到结果。
    QCOMPARE(errors.count(), 0);
    QCOMPARE(updated.count(), 1);
    QCOMPARE(updated.at(0).at(0).toString(), QStringLiteral(
                 "杭州，今日天气晴，\n"
                 "高温26℃，低温16℃，\n"
                 "西风\n"
                 "每日提醒：适合外出"));
}

void TestWeatherService::cancelDoesNotEmitLateWeatherUpdated()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());
    server.setBehavior(FakeWeatherServer::HeadersOnly);

    WeatherService service;
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);
    QSignalSpy errors(&service, &WeatherService::errorOccurred);

    service.refresh();
    QVERIFY(server.waitForRequests(1));
    QTest::qWait(250);

    // 取消，然后让服务端"迟到地"把 body 补上。
    service.refresh();
    QTest::qWait(150);
    server.setBehavior(FakeWeatherServer::Reply);
    server.setReply(200, weatherJson(QStringLiteral("南京"), QStringLiteral("晴"),
                                     QStringLiteral("高温 27℃"),
                                     QStringLiteral("低温 17℃"),
                                     QStringLiteral("北风"),
                                     QStringLiteral("注意温差")));
    QTest::qWait(600);

    // 被取消的那个请求即使数据到达，也不该上报 —— 它已经不是当前请求了。
    QCOMPARE(updated.count(), 0);
    QCOMPARE(errors.count(), 0);
}

void TestWeatherService::destructorWithInFlightRequestIsSafe()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());
    server.setBehavior(FakeWeatherServer::HeadersOnly);

    {
        WeatherService service;
        service.refresh();
        QVERIFY(server.waitForRequests(1));
        QTest::qWait(250);
        // 请求仍在途时析构：必须安全（内部走 abandonReply()）。
    }
    // 析构后跑一会儿事件循环，确认没有延迟到析构之后的崩溃或信号。
    QTest::qWait(400);
    QVERIFY(true); // 能走到这里就说明没有崩
}

void TestWeatherService::destructorWithoutRequestIsSafe()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());

    {
        WeatherService service;
        // 从未 refresh()：m_reply 为 nullptr，析构不应解引用它。
    }
    QTest::qWait(200);
    QCOMPARE(server.requestCount(), 0);
}

void TestWeatherService::refreshAfterSuccessStartsFreshRequest()
{
    FakeWeatherServer server;
    QVERIFY(server.listen());
    useUrl(server.url());

    server.setBehavior(FakeWeatherServer::Reply);
    server.setReply(200, weatherJson(QStringLiteral("天津"), QStringLiteral("晴"),
                                     QStringLiteral("高温 24℃"),
                                     QStringLiteral("低温 14℃"),
                                     QStringLiteral("东南风"),
                                     QStringLiteral("天气不错")));

    WeatherService service;
    QSignalSpy updated(&service, &WeatherService::weatherUpdated);
    QSignalSpy errors(&service, &WeatherService::errorOccurred);

    service.refresh();
    QVERIFY(waitFor([&]() { return updated.count() >= 1; }));

    // 上一次已经成功结束（m_reply 已置空），再刷一次必须能发新请求。
    // 若 m_reply 没被正确清空，这里要么复用坏句柄、要么什么都不发。
    service.refresh();
    QVERIFY(server.waitForRequests(2));
    QVERIFY(waitFor([&]() { return updated.count() >= 2; }));

    QCOMPARE(errors.count(), 0);
    QCOMPARE(updated.count(), 2);

    // 每次刷新各自对应一次上报，不能把新请求算成旧的。
    QTest::qWait(300);
    QCOMPARE(updated.count(), 2);
}

QTEST_MAIN(TestWeatherService)
#include "test_weather_service.moc"
