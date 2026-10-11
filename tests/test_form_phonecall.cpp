/**
 * @file test_form_phonecall.cpp
 * @brief 通话浮层 `src/ui/form_phonecall.cpp` 的行为测试（影子头方案）。
 *
 * 为什么值得单独钉
 * ----------------
 * `src/ui/form_phonecall.cpp`（206 行）是【P1】第 2 项，也是室内机信令链路上
 * 的关键一环：
 *   1. **接听**：用户把滑块拖到最右 -> `engageCall()` -> 发 `accepted` /
 *      `answered`。`accepted` 被 `Widget` 翻译成线上字节 `accept\n` —— 拖不到
 *      底就不该接通，这一点必须真的验（10px 容差是有含义的）。
 *   2. **挂断**：挂断按钮 -> `hangupClicked`（线上 `recstop\n`）+ `close()`。
 *   3. **会话生命周期**：接通才 `CallSession::start()`；关闭窗口 / 析构必须
 *      `stop()`，否则 socket 与声卡不释放。
 *   4. **响铃循环**：`stateChanged == StoppedState` 时要重新 `play()`，
 *      并且"离线状态"下传进来的 `playRing=false` 必须**一个播放器都不建**。
 *
 * 做法：影子头 + 真实 form_phonecall.cpp
 * --------------------------------------
 *   - `QMediaPlayer` 用 tests/fake_media/QMediaPlayer 替掉
 *     （define ACC_FORM_PHONECALL_TEST），于是本目标**不需要 Qt5::Multimedia**，
 *     也不碰开发机的声卡；
 *   - `core/media/call_session.h` 用 tests/shadows_form/core/media/call_session.h
 *     替掉 —— 音视频通道本身由 `desktop_test_call_session`（33 个用例，真实
 *     socket + 声卡替身）单独覆盖，这里只验浮层对它的编排（start/stop/收帧）；
 *   - `ui/slidehintwidget.cpp`、`app_config.cpp`、真实 `ui/form_phonecall.cpp`
 *     都照原样链接，后者一个字节不改。
 *
 * 交互一律用**真实事件**驱动：往 `label_slider` 发
 * 按下/移动/松开三件套，走的正是 `eventFilter` 的产线路径，
 * 而不是直接调私有的 `engageCall()`。
 */
#include <QApplication>
#include <QCloseEvent>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QImage>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QMediaPlayer>
#include <QMouseEvent>
#include <QPushButton>
#include <QScopedPointer>
#include <QSignalSpy>
#include <QTest>
#include <QTimer>
#include <QWidget>

#include "config/app_config.h"
#include "fake_media.h"
#include "ui/form_phonecall.h"
#include "ui/slidehintwidget.h"

using accessterminal::AppConfig;

namespace {

// 门铃音地址必须写成带 scheme 的 `qrc:/...`（与 config/appconfig.json 里的
// `qrc:/door.mp3` 一致）。实测：`QUrl(":/sound/x.mp3")` 的 toString() 是**空串**
// —— QUrl 会把裸的 `:/` 前缀吃掉，于是 setMedia 拿到空地址、门铃音静默不响。
// 这不是测试的怪癖，而是配置值的真实约束，所以这里的取值刻意与产线一致。
const char* const kRingtone = "qrc:/sound/test_ring.mp3";
const int kRingtoneVolume = 42;

/// 轮询等待（会跑事件循环 —— 定时器驱动的流光动画必须靠它推进）。
template <typename Predicate>
bool waitFor(Predicate pred, int timeoutMs = 3000)
{
    QElapsedTimer timer;
    timer.start();
    while (!pred()) {
        if (timer.elapsed() > timeoutMs) {
            return false;
        }
        QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
        QTest::qWait(5);
    }
    return true;
}

/// 造一张有内容的图（纯色也够，用于验证 pixmap 被设上）。
QImage makeImage(int w = 80, int h = 60)
{
    QImage img(w, h, QImage::Format_RGB32);
    img.fill(Qt::darkCyan);
    return img;
}

bool hasPixmap(QLabel* l)
{
#if QT_VERSION >= QT_VERSION_CHECK(5, 15, 0)
    return !l->pixmap(Qt::ReturnByValue).isNull();
#else
    const QPixmap* p = l->pixmap();
    return p != nullptr && !p->isNull();
#endif
}

/**
 * @brief 取 QLabel 内部 pixmap 的**指针**（区分"从未设置"与"设了个空的"）。
 *
 * 必须用这个被标记为 deprecated 的重载：Qt 5.15 新增的"按值返回"重载
 * **无法**区分这两种情形，两者都返回空 QPixmap。而指针版能区分 ——
 * 实测（Qt 5.15.3，offscreen）：
 *     从未 setPixmap / clear() 之后   -> nullptr
 *     setPixmap(QPixmap())           -> 非空指针，但 isNull() == true
 * 这正是"空帧门控"唯一的可观测量：`onVideoFrameReady` 若丢掉 `frame.isNull()`
 * 判断，就会走到 `setPixmap(空)`，指针随即从 nullptr 变成非空。
 * 门控失效在**画面上看不出区别**（都是不显示），所以只能这样验。
 * 就地屏蔽弃用警告，避免污染构建输出。
 */
const QPixmap* pixmapPtr(QLabel* l)
{
#if defined(__GNUC__)
#  pragma GCC diagnostic push
#  pragma GCC diagnostic ignored "-Wdeprecated-declarations"
#endif
    const QPixmap* p = l->pixmap();
#if defined(__GNUC__)
#  pragma GCC diagnostic pop
#endif
    return p;
}

} // namespace

class TestFormPhonecall : public QObject
{
    Q_OBJECT

private slots:
    void initTestCase();
    void init();

    void playRingFalseCreatesNoPlayer();
    void playRingTrueStartsRingtoneWithConfiguredVolume();
    void stoppedRingReplaysItself();

    void dragToRightAnswersAndEmitsAccepted();
    void dragNotFarEnoughSnapsBackWithoutAnswering();
    void hangupButtonEmitsHangupAndCloses();
    void closeEventStopsRunningSession();
    void videoFrameSetsLabelImage();
    void nullVideoFrameIsIgnored();
    void destructorStopsSessionAndRing();
    void slideHintIsPaintedAnimatedAndMouseTransparent();

private:
    /// 写一份隔离用 JSON 配置并 load（含门铃音路径与音量）。
    QString loadIsolatedConfig();
    /// 造一个已 show 的浮层；调用方负责生命周期。
    Form_phonecall* makeForm(bool playRing);
    /// 往 label_slider 发"按下 -> 移动 -> 松开"三件套；toEnd 决定是否拖到底。
    void dragSlider(Form_phonecall* f, bool toEnd);
};

void TestFormPhonecall::initTestCase()
{
    const char* const names[] = {
        "ACCESSTERMINAL_MEDIA_RINGTONE_VOLUME",
        "ACCESSTERMINAL_WEATHER_URL",
        "ACCESSTERMINAL_HARDWARE_SERIAL_PORT",
        "ACCESSTERMINAL_NETWORK_SIGNALING_PORT",
        "ACCESSTERMINAL_NETWORK_DEVICE_IP",
        "SMARTSERVER_DEVICE_IP",
    };
    for (const char* n : names) {
        qunsetenv(n);
    }
}

void TestFormPhonecall::init()
{
    resetFakeMediaPlayer();
    resetFakeCallSession();
}

QString TestFormPhonecall::loadIsolatedConfig()
{
    QJsonObject media;
    media.insert(QStringLiteral("ringtone"), QString::fromLatin1(kRingtone));
    media.insert(QStringLiteral("ringtone_volume"), kRingtoneVolume);

    // 天气/网络与本测试无关，但要显式隔离，避免真去请求外网。
    QJsonObject weather;
    weather.insert(QStringLiteral("url"), QString());

    QJsonObject root;
    root.insert(QStringLiteral("media"), media);
    root.insert(QStringLiteral("weather"), weather);

    const QString path =
        QDir(QDir::tempPath())
            .filePath(QStringLiteral("acc_form_phonecall_test_config.json"));
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        return QString();
    }
    file.write(QJsonDocument(root).toJson());
    file.close();

    AppConfig::instance().load(path);
    return path;
}

Form_phonecall* TestFormPhonecall::makeForm(bool playRing)
{
    Form_phonecall* f = new Form_phonecall(nullptr, playRing);
    f->resize(600, 400);
    f->show();
    return f;
}

void TestFormPhonecall::dragSlider(Form_phonecall* f, bool toEnd)
{
    QWidget* slider = f->findChild<QWidget*>(QStringLiteral("label_slider"));
    QWidget* area = f->findChild<QWidget*>(QStringLiteral("widget_slider_area"));
    QVERIFY(slider);
    QVERIFY(area);

    // UI 尺寸前提：滑道必须明显宽于滑块，否则"拖到底"与"没拖到底"
    // 区分不开，断言会失去判别力。这里把它变成显式前提。
    QVERIFY2(area->width() > slider->width() + 40,
             qPrintable(QStringLiteral("滑道宽 %1 必须显著大于滑块宽 %2")
                            .arg(area->width())
                            .arg(slider->width())));

    // 按下：记下 dragOffset（= 0）。
    QMouseEvent press(QEvent::MouseButtonPress, QPoint(0, 0), Qt::LeftButton,
                      Qt::LeftButton, Qt::NoModifier);
    QApplication::sendEvent(slider, &press);

    // 移动：newX = slider->x() + pos().x() - dragOffset，再被 qBound 夹住。
    const int moveX = toEnd ? (area->width() + 50) : 5;
    QMouseEvent move(QEvent::MouseMove, QPoint(moveX, 0), Qt::NoButton,
                     Qt::LeftButton, Qt::NoModifier);
    QApplication::sendEvent(slider, &move);

    // 松开：超过"滑道宽 - 滑块宽 - 10"即视为接听。
    QMouseEvent release(QEvent::MouseButtonRelease, QPoint(moveX, 0),
                        Qt::LeftButton, Qt::NoButton, Qt::NoModifier);
    QApplication::sendEvent(slider, &release);
}

// ===========================================================================

void TestFormPhonecall::playRingFalseCreatesNoPlayer()
{
    QVERIFY(!loadIsolatedConfig().isEmpty());
    QScopedPointer<Form_phonecall> f(makeForm(false));

    // 离线状态下来电：ui 传 playRing=false，必须一个播放器都不建
    // （否则会在"离线"时也响铃）。
    QCOMPARE(fakeMediaPlayer().constructed, 0);
}

void TestFormPhonecall::playRingTrueStartsRingtoneWithConfiguredVolume()
{
    QVERIFY(!loadIsolatedConfig().isEmpty());
    QScopedPointer<Form_phonecall> f(makeForm(true));

    QCOMPARE(fakeMediaPlayer().constructed, 1);
    QVERIFY2(fakeMediaPlayer().setMediaCalls >= 1, "应把门铃音地址交给播放器");
    QCOMPARE(fakeMediaPlayer().media, QString::fromLatin1(kRingtone));
    QCOMPARE(fakeMediaPlayer().volume, kRingtoneVolume);
    QVERIFY2(fakeMediaPlayer().playCalls >= 1, "建好播放器就该开始响铃");
}

void TestFormPhonecall::stoppedRingReplaysItself()
{
    QVERIFY(!loadIsolatedConfig().isEmpty());
    QScopedPointer<Form_phonecall> f(makeForm(true));

    QVERIFY(fakeMediaPlayer().last);
    const int before = fakeMediaPlayer().playCalls;

    // 模拟"这段音频播完了" —— 产线行为是重新 play()，实现循环响铃。
    fakeMediaPlayer().last->emitStateForTest(QMediaPlayer::StoppedState);
    QCOMPARE(fakeMediaPlayer().playCalls, before + 1);
}

void TestFormPhonecall::dragToRightAnswersAndEmitsAccepted()
{
    QVERIFY(!loadIsolatedConfig().isEmpty());
    QScopedPointer<Form_phonecall> f(makeForm(false));

    QSignalSpy acceptedSpy(f.data(), &Form_phonecall::accepted);
    QSignalSpy answeredSpy(f.data(), &Form_phonecall::answered);

    dragSlider(f.data(), true);

    QCOMPARE(acceptedSpy.count(), 1);
    QCOMPARE(answeredSpy.count(), 1);

    // 接通后必须真的把通道拉起来。
    QCOMPARE(fakeCallSession().constructed, 1);
    QCOMPARE(fakeCallSession().startCalls, 1);

    // 接听控件让位给挂断按钮。
    QVERIFY2(!f->findChild<QWidget*>(QStringLiteral("label_slider"))->isVisible(),
             "接通后接听滑块应隐藏");
    QPushButton* hangup = f->findChild<QPushButton*>();
    QVERIFY(hangup);
    QVERIFY2(hangup->isVisible(), "接通后应显示挂断按钮");
}

void TestFormPhonecall::dragNotFarEnoughSnapsBackWithoutAnswering()
{
    QVERIFY(!loadIsolatedConfig().isEmpty());
    QScopedPointer<Form_phonecall> f(makeForm(false));

    QSignalSpy acceptedSpy(f.data(), &Form_phonecall::accepted);
    QWidget* slider = f->findChild<QWidget*>(QStringLiteral("label_slider"));
    QVERIFY(slider);

    dragSlider(f.data(), false);

    QCOMPARE(acceptedSpy.count(), 0);
    QCOMPARE(fakeCallSession().constructed, 0);
    // 没拖到底：滑块弹回起点。
    QCOMPARE(slider->x(), 0);
}

void TestFormPhonecall::hangupButtonEmitsHangupAndCloses()
{
    QVERIFY(!loadIsolatedConfig().isEmpty());
    QScopedPointer<Form_phonecall> f(makeForm(false));

    dragSlider(f.data(), true); // 先接通，挂断按钮才会出现
    QPushButton* hangup = f->findChild<QPushButton*>();
    QVERIFY(hangup);
    QVERIFY(hangup->isVisible());

    QSignalSpy hangupSpy(f.data(), &Form_phonecall::hangupClicked);
    hangup->click();

    QCOMPARE(hangupSpy.count(), 1);
    QVERIFY2(!f->isVisible(), "点挂断应关闭浮层");
}

void TestFormPhonecall::closeEventStopsRunningSession()
{
    QVERIFY(!loadIsolatedConfig().isEmpty());
    QScopedPointer<Form_phonecall> f(makeForm(false));

    dragSlider(f.data(), true);
    QCOMPARE(fakeCallSession().startCalls, 1);
    QCOMPARE(fakeCallSession().stopCalls, 0);

    f->close();

    QVERIFY2(fakeCallSession().stopCalls >= 1,
             "关闭窗口必须停掉通话通道（否则 socket 与声卡不释放）");
}

void TestFormPhonecall::videoFrameSetsLabelImage()
{
    QVERIFY(!loadIsolatedConfig().isEmpty());
    QScopedPointer<Form_phonecall> f(makeForm(false));

    QLabel* image = f->findChild<QLabel*>(QStringLiteral("label_image"));
    QVERIFY(image);
    QVERIFY2(!image->isVisible(), "接通前画面标签应隐藏");

    dragSlider(f.data(), true);
    QVERIFY2(image->isVisible(), "接通后画面标签应显示");

    QVERIFY(fakeCallSession().last);
    fakeCallSession().last->emitVideoFrameForTest(makeImage());

    QVERIFY2(hasPixmap(image), "收到视频帧后应把画面设到 label_image 上");
}

void TestFormPhonecall::nullVideoFrameIsIgnored()
{
    QVERIFY(!loadIsolatedConfig().isEmpty());
    QScopedPointer<Form_phonecall> f(makeForm(false));

    dragSlider(f.data(), true);
    QLabel* image = f->findChild<QLabel*>(QStringLiteral("label_image"));
    QVERIFY(image);
    QVERIFY(fakeCallSession().last);

    image->clear();
    QVERIFY(!hasPixmap(image));
    QVERIFY2(pixmapPtr(image) == nullptr,
             "clear() 之后 pixmap 指针应为 nullptr（本用例的基线）");

    // 门控若失效，这里会执行 setPixmap(空 QPixmap)，指针立刻变成非空。
    // 画面上两者都不显示，所以只能靠指针来判别 —— 见 pixmapPtr 的说明。
    fakeCallSession().last->emitVideoFrameForTest(QImage());
    QVERIFY2(pixmapPtr(image) == nullptr,
             "空帧必须被 frame.isNull() 门控挡住：连 setPixmap 都不该调用");
    QVERIFY(!hasPixmap(image));

    // 反证：真帧仍能设上（说明上一条不是因为整条路断了）。
    fakeCallSession().last->emitVideoFrameForTest(makeImage());
    QVERIFY2(hasPixmap(image), "真实帧仍应能显示");
}

void TestFormPhonecall::destructorStopsSessionAndRing()
{
    QVERIFY(!loadIsolatedConfig().isEmpty());

    {
        QScopedPointer<Form_phonecall> f(makeForm(true));
        dragSlider(f.data(), true);
        QCOMPARE(fakeCallSession().constructed, 1);
        QVERIFY(fakeMediaPlayer().constructed == 1);
    } // <- 析构

    QVERIFY2(fakeCallSession().destroyed == 1,
             "析构必须释放通话通道");
    QVERIFY2(fakeMediaPlayer().destroyed == 1,
             "析构必须释放门铃音播放器");
}

/**
 * `SlideHintWidget`（79 行）随本目标被链接，但它自己的行为此前**一条断言都没有**。
 * 它有三件事会直接影响接听交互，都不是"看着像装饰"那么简单：
 *   1. 它盖在接听滑块所在的滑道上，**必须不拦截鼠标事件**
 *      （WA_TransparentForMouseEvents），否则滑块根本拖不动；
 *   2. 它靠一个 10ms 的 QTimer 推进 `pos` 再 `update()` 重绘 ——
 *      定时器不启动，流光就是一张静止的图（视觉上"卡住"）；
 *   3. `paintEvent` 必须真的画（胶囊背景 + 流光）；若整段不画，
 *      用户看到的是空白，而代码不会报任何错。
 *
 * 这里把三条都变成断言。"动画在推进"用**抓图前后必须不同**来验 ——
 * `pos` 是私有的，但它的效果（画出来的像素）是可观测的。
 */
void TestFormPhonecall::slideHintIsPaintedAnimatedAndMouseTransparent()
{
    QVERIFY(!loadIsolatedConfig().isEmpty());
    QScopedPointer<Form_phonecall> f(makeForm(false));

    QWidget* area = f->findChild<QWidget*>(QStringLiteral("widget_slider_area"));
    QVERIFY(area);
    // 构造时以滑道为父：必须是滑道的子控件，否则盖不住滑道。
    SlideHintWidget* hint = area->findChild<SlideHintWidget*>();
    QVERIFY2(hint, "滑道里应当有流光引导控件");
    QVERIFY2(hint->testAttribute(Qt::WA_TransparentForMouseEvents),
             "流光控件不得拦截鼠标事件，否则接听滑块拖不动");

    QTimer* timer = hint->findChild<QTimer*>();
    QVERIFY(timer);
    QVERIFY2(timer->isActive(), "流光动画的定时器必须处于激活状态");
    QCOMPARE(timer->interval(), 10);

    // 抓图：必须真的画了东西（全透明 = 什么都没画）。
    const QImage first = hint->grab().toImage();
    QVERIFY2(!first.isNull(), "抓图失败（控件尺寸可能为 0）");
    bool painted = false;
    for (int y = 0; y < first.height() && !painted; y += 2) {
        for (int x = 0; x < first.width(); x += 2) {
            if (first.pixelColor(x, y).alpha() > 0) {
                painted = true;
                break;
            }
        }
    }
    QVERIFY2(painted, "paintEvent 必须真的画出胶囊背景/流光，而不是全透明");

    // 动画在推进：稍后再抓一张，像素应当变了。
    QVERIFY2(waitFor([&]() { return hint->grab().toImage() != first; }, 2000),
             "流光动画没有推进（定时器/pos 推进/update 之一失效）");
}

int main(int argc, char** argv)
{
    if (qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM")) {
        qputenv("QT_QPA_PLATFORM", QByteArrayLiteral("offscreen"));
    }
    QApplication app(argc, argv);
    TestFormPhonecall tc;
    return QTest::qExec(&tc, argc, argv);
}

#include "test_form_phonecall.moc"
