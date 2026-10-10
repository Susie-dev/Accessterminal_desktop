// 引入项目内部头文件 "widget.h"。
#include "widget.h"
// 引入项目内部头文件 "ui_widget.h"。
#include "ui_widget.h"
#include "appconfig.h"
// 引入系统或第三方头文件 <QRegion>。
#include <QRegion>
// 引入系统或第三方头文件 <QPainterPath>。
#include <QPainterPath>
// 引入系统或第三方头文件 <QNetworkAccessManager>。
#include <QNetworkAccessManager>
// 引入系统或第三方头文件 <QNetworkRequest>。
#include <QNetworkRequest>
// 引入系统或第三方头文件 <QJsonDocument>。
#include <QJsonDocument>
// 引入系统或第三方头文件 <QJsonObject>。
#include <QJsonObject>
// 引入系统或第三方头文件 <QJsonArray>。
#include <QJsonArray>
// 引入系统或第三方头文件 <QUrl>。
#include <QUrl>
// 引入系统或第三方头文件 <QDateTime>。
#include <QDateTime>
// 引入系统或第三方头文件 <QDate>。
#include <QDate>
// 引入系统或第三方头文件 <QTime>。
#include <QTime>
// 引入系统或第三方头文件 <QPixmap>。
#include <QPixmap>
// 引入系统或第三方头文件 <QGraphicsOpacityEffect>。
#include <QGraphicsOpacityEffect>
// 引入系统或第三方头文件 <QPropertyAnimation>。
#include <QPropertyAnimation>


// 引入系统或第三方头文件 <QParallelAnimationGroup>。
#include <QParallelAnimationGroup>

// 引入系统或第三方头文件 <QParallelAnimationGroup>。
#include <QParallelAnimationGroup>
// 引入项目内部头文件 "form_phonecall.h"。
#include "form_phonecall.h"

// 定义类 Widget 的成员函数 Widget。
Widget::Widget(QWidget *parent)
    // 继续当前代码块的参数、表达式或结构定义。
    : QWidget(parent)
    // 继续当前代码块的参数、表达式或结构定义。
    , ui(new Ui::Widget)
// 进入新的代码块作用域。
{
    // 访问或更新 Qt 界面控件。
    ui->setupUi(this);
    // 执行本行语句完成对应变量、对象或业务状态处理。
    offmark = false;

    // 设置窗口为无边框（可选）
    // 执行本行语句完成对应变量、对象或业务状态处理。
    setWindowFlags(Qt::FramelessWindowHint);

    // 设置圆角
    // 继续当前代码块的参数、表达式或结构定义。
    int radius = 10; // 圆角半径
    // 创建绘图对象用于在图像或控件上绘制内容。
    QPainterPath path;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    path.addRoundedRect(rect(), radius, radius);
    // 执行本行语句完成对应变量、对象或业务状态处理。
    setMask(QRegion(path.toFillPolygon().toPolygon()));

    // label_off 渐显渐隐动画初始化
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QGraphicsOpacityEffect *opacityEffect = new QGraphicsOpacityEffect(this);
    // 执行本行语句完成对应变量、对象或业务状态处理。
    opacityEffect->setOpacity(0.0);
    // 访问或更新 Qt 界面控件。
    ui->label_off->setGraphicsEffect(opacityEffect);
    // 访问或更新 Qt 界面控件。
    ui->label_off->setVisible(false);

    // 天气功能集成
    // 执行本行语句完成对应变量、对象或业务状态处理。
    requestWeather();

    // 系统时间定时器
    // 执行本行语句完成对应变量、对象或业务状态处理。
    sysTimeTimer = new QTimer(this);
    // 建立 Qt 信号与槽或 lambda 回调连接。
    connect(sysTimeTimer, &QTimer::timeout, this, &Widget::time_reflash);
    // 继续当前代码块的参数、表达式或结构定义。
    sysTimeTimer->start(1000); // 每秒刷新一次
    // 继续当前代码块的参数、表达式或结构定义。
    time_reflash(); // 启动时立即刷新一次

    // 启动TCP服务端监听8887
    // 执行本行语句完成对应变量、对象或业务状态处理。
    tcpServer = new QTcpServer(this);
    // 建立 Qt 信号与槽或 lambda 回调连接。
    connect(tcpServer, &QTcpServer::newConnection, this, &Widget::onNewTcpConnection);
    // 根据条件判断是否执行该分支。
    if (!tcpServer->listen(QHostAddress::Any, 8887)) {
        // 输出调试日志。
        qDebug() << "TCP server failed to listen on port 8887:" << tcpServer->errorString();
    // 结束当前代码块作用域。
    } else {
        // 输出调试日志。
        qDebug() << "TCP server listening on port 8887";
        qDebug() << "[网络配置] 服务端地址:" << smartserverSelfIp()
                 << "T113地址:" << smartserverDeviceIp();
    // 结束当前代码块作用域。
    }


    // 访问或更新 Qt 界面控件。
    ui->widget_light->setVisible(false);
    // 连接btn_home点击信号到槽函数

    // 执行本行语句完成对应变量、对象或业务状态处理。
    serialPort = new QSerialPort(this);
    // 设置串口名称
    // 继续当前代码块的参数、表达式或结构定义。
    serialPort->setPortName("COM24");  // Linux串口设备
    // 设置波特率
    // 执行本行语句完成对应变量、对象或业务状态处理。
    serialPort->setBaudRate(QSerialPort::Baud9600);
    // 设置数据位
    // 执行本行语句完成对应变量、对象或业务状态处理。
    serialPort->setDataBits(QSerialPort::Data8);
    // 设置奇偶校验
    // 执行本行语句完成对应变量、对象或业务状态处理。
    serialPort->setParity(QSerialPort::NoParity);
    // 设置停止位
    // 执行本行语句完成对应变量、对象或业务状态处理。
    serialPort->setStopBits(QSerialPort::OneStop);
    // 设置流控制
    // 执行本行语句完成对应变量、对象或业务状态处理。
    serialPort->setFlowControl(QSerialPort::NoFlowControl);
    // 打开串口
    // 根据条件判断是否执行该分支。
    if (serialPort->open(QIODevice::ReadWrite)) {
        // 输出调试日志。
        qDebug() << "串口打开成功";
    // 结束当前代码块作用域。
    } else {
        // 输出调试日志。
        qDebug() << "串口打开失败:" << serialPort->errorString();
    // 结束当前代码块作用域。
    }

// 结束当前代码块作用域。
}

// 定义类 Widget 的成员函数 ~Widget。
Widget::~Widget()
// 进入新的代码块作用域。
{
    // 释放动态创建的对象资源。
    delete ui;
// 结束当前代码块作用域。
}

// 定义或声明函数 Widget::on_btn_power_clicked。
void Widget::on_btn_power_clicked()
// 进入新的代码块作用域。
{
    // 根据条件判断是否执行该分支。
    if(!offmark){
        // 访问或更新 Qt 界面控件。
        ui->widget_main->setStyleSheet(
                // 继续当前代码块的参数、表达式或结构定义。
                "#widget_main {"
                // 继续当前代码块的参数、表达式或结构定义。
                "background-color: black;"
                // 继续当前代码块的参数、表达式或结构定义。
                "border-image: none;"
                // 继续当前代码块的参数、表达式或结构定义。
                "}"
            // 执行本行语句完成对应变量、对象或业务状态处理。
            );
    // 结束当前代码块作用域。
    }else{
        // 访问或更新 Qt 界面控件。
        ui->widget_main->setStyleSheet(
            // 继续当前代码块的参数、表达式或结构定义。
            "#widget_main {"
            // 继续当前代码块的参数、表达式或结构定义。
            "background-color: rgb(255, 255, 255);"
            // 继续当前代码块的参数、表达式或结构定义。
            "border-image: url(:/pic/smartbg.png);"
            // 继续当前代码块的参数、表达式或结构定义。
            "}"
        // 执行本行语句完成对应变量、对象或业务状态处理。
        );
    // 结束当前代码块作用域。
    }
    // 执行本行语句完成对应变量、对象或业务状态处理。
    offmark = !offmark;
// 结束当前代码块作用域。
}

// 定义或声明函数 Widget::on_btn_offline_clicked。
void Widget::on_btn_offline_clicked()
// 进入新的代码块作用域。
{
    // 使用自动类型推导保存表达式结果。
    auto *effect = qobject_cast<QGraphicsOpacityEffect *>(ui->label_off->graphicsEffect());
    // 根据条件判断是否执行该分支。
    if (!effect) return;

    // 执行本行语句完成对应变量、对象或业务状态处理。
    QPropertyAnimation *animation = new QPropertyAnimation(effect, "opacity", this);
    // 继续当前代码块的参数、表达式或结构定义。
    animation->setDuration(500); // 500ms 动画

    // 根据条件判断是否执行该分支。
    if (!ui->label_off->isVisible()) {
        // 访问或更新 Qt 界面控件。
        ui->label_off->setVisible(true);
        // 执行本行语句完成对应变量、对象或业务状态处理。
        animation->setStartValue(0.0);
        // 执行本行语句完成对应变量、对象或业务状态处理。
        animation->setEndValue(1.0);
    // 结束当前代码块作用域。
    } else {
        // 执行本行语句完成对应变量、对象或业务状态处理。
        animation->setStartValue(1.0);
        // 执行本行语句完成对应变量、对象或业务状态处理。
        animation->setEndValue(0.0);
        // 建立 Qt 信号与槽或 lambda 回调连接。
        connect(animation, &QPropertyAnimation::finished, [this]() {
            // 访问或更新 Qt 界面控件。
            ui->label_off->setVisible(false);
        // 结束当前代码块作用域。
        });
    // 结束当前代码块作用域。
    }
    // 执行本行语句完成对应变量、对象或业务状态处理。
    animation->start(QAbstractAnimation::DeleteWhenStopped);
// 结束当前代码块作用域。
}

// 定义或声明函数 Widget::requestWeather。
void Widget::requestWeather()
// 进入新的代码块作用域。
{
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QNetworkAccessManager *manager = new QNetworkAccessManager(this);
    // 继续当前代码块的参数、表达式或结构定义。
    QUrl url("http://t.weather.itboy.net/api/weather/city/101230101"); // 替换为你需要的城市代码
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QNetworkRequest req(url);
    // 执行本行语句完成对应变量、对象或业务状态处理。
    reply = manager->get(req);
    // 建立 Qt 信号与槽或 lambda 回调连接。
    connect(reply, &QNetworkReply::finished, this, &Widget::readHttpRply);
// 结束当前代码块作用域。
}

// 定义或声明函数 Widget::readHttpRply。
void Widget::readHttpRply()
// 进入新的代码块作用域。
{
    // 执行本行语句完成对应变量、对象或业务状态处理。
    int resCode = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
    // 根据条件判断是否执行该分支。
    if (reply->error() == QNetworkReply::NoError && resCode == 200) {
        // 创建或使用字节数组保存协议或音视频数据。
        QByteArray data = reply->readAll();
        // 执行本行语句完成对应变量、对象或业务状态处理。
        QJsonDocument jsonResponse = QJsonDocument::fromJson(data);
        // 执行本行语句完成对应变量、对象或业务状态处理。
        QJsonObject jsonObject = jsonResponse.object();

        // 执行本行语句完成对应变量、对象或业务状态处理。
        QString city = jsonObject["cityInfo"].toObject()["city"].toString();
        // 执行本行语句完成对应变量、对象或业务状态处理。
        QJsonObject today = jsonObject["data"].toObject()["forecast"].toArray()[0].toObject();
        // 执行本行语句完成对应变量、对象或业务状态处理。
        QString weatherType = today["type"].toString();
        // 执行本行语句完成对应变量、对象或业务状态处理。
        QString high = today["high"].toString().replace("高温 ", "");
        // 执行本行语句完成对应变量、对象或业务状态处理。
        QString low = today["low"].toString().replace("低温 ", "");
        // 执行本行语句完成对应变量、对象或业务状态处理。
        QString wind = today["fx"].toString();
        // 执行本行语句完成对应变量、对象或业务状态处理。
        QString notice = today["notice"].toString();

        // 继续当前代码块的参数、表达式或结构定义。
        QString weatherText = QString("%1，今日天气%2，\n高温%3，低温%4，\n%5\n每日提醒：%6")
            // 继续当前代码块的参数、表达式或结构定义。
            .arg(city)
            // 继续当前代码块的参数、表达式或结构定义。
            .arg(weatherType)
            // 继续当前代码块的参数、表达式或结构定义。
            .arg(high)
            // 继续当前代码块的参数、表达式或结构定义。
            .arg(low)
            // 继续当前代码块的参数、表达式或结构定义。
            .arg(wind)
            // 执行本行语句完成对应变量、对象或业务状态处理。
            .arg(notice);

        // 根据条件判断是否执行该分支。
        if (this->ui->label_weather)
            // 执行本行语句完成对应变量、对象或业务状态处理。
            this->ui->label_weather->setText(weatherText);
    // 结束当前代码块作用域。
    }
// 结束当前代码块作用域。
}

// 定义或声明函数 Widget::time_reflash。
void Widget::time_reflash()
// 进入新的代码块作用域。
{
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QDateTime currentTime = QDateTime::currentDateTime();
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QDate date = currentTime.date();
    // 执行本行语句完成对应变量、对象或业务状态处理。
    int year = date.year();
    // 执行本行语句完成对应变量、对象或业务状态处理。
    int month = date.month();
    // 执行本行语句完成对应变量、对象或业务状态处理。
    int day = date.day();
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QTime time = currentTime.time();
    // 执行本行语句完成对应变量、对象或业务状态处理。
    int hour = time.hour();
    // 执行本行语句完成对应变量、对象或业务状态处理。
    int minute = time.minute();
    // 执行本行语句完成对应变量、对象或业务状态处理。
    int second = time.second();
    // 执行本行语句完成对应变量、对象或业务状态处理。
    myDate = QString("%1-%2-%3").arg(year, 4, 10, QChar('0')).arg(month, 2, 10, QChar('0')).arg(day, 2, 10, QChar('0'));
    // 执行本行语句完成对应变量、对象或业务状态处理。
    myTime = QString("%1:%2:%3").arg(hour, 2, 10, QChar('0')).arg(minute, 2, 10, QChar('0')).arg(second, 2, 10, QChar('0'));
    // 根据条件判断是否执行该分支。
    if (ui->labelDate)
        // 访问或更新 Qt 界面控件。
        ui->labelDate->setText(myDate);
    // 根据条件判断是否执行该分支。
    if (ui->labelTime_2)
        // 访问或更新 Qt 界面控件。
        ui->labelTime_2->setText(myTime);
// 结束当前代码块作用域。
}

// 定义或声明函数 Widget::onUdpDataReceived。
void Widget::onUdpDataReceived()
// 进入新的代码块作用域。
{
    // 开始循环处理满足条件的数据或状态。
    while (udpSocket && udpSocket->hasPendingDatagrams()) {
        // 创建或使用字节数组保存协议或音视频数据。
        QByteArray datagram;
        // 执行本行语句完成对应变量、对象或业务状态处理。
        datagram.resize(int(udpSocket->pendingDatagramSize()));
        // 创建或设置网络主机地址。
        QHostAddress sender;
        // 执行本行语句完成对应变量、对象或业务状态处理。
        quint16 senderPort;
        // 执行本行语句完成对应变量、对象或业务状态处理。
        udpSocket->readDatagram(datagram.data(), datagram.size(), &sender, &senderPort);
        // 创建或处理用于界面显示的位图。
        QPixmap pix;
        // 执行本行语句完成对应变量、对象或业务状态处理。
        pix.loadFromData(datagram, "JPG");
        // 根据条件判断是否执行该分支。
        if (!pix.isNull() && camActive) {
            // 根据条件判断是否执行该分支。
            if (firstShow || !ui->labelcam->isVisible()) {
                // 执行本行语句完成对应变量、对象或业务状态处理。
                QRect endRect = ui->labelcam->geometry();
                // 执行本行语句完成对应变量、对象或业务状态处理。
                QRect startRect = endRect;
                // 执行本行语句完成对应变量、对象或业务状态处理。
                startRect.setWidth(endRect.width() * 0.2);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                startRect.setHeight(endRect.height() * 0.2);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                startRect.moveCenter(endRect.center());
                // 访问或更新 Qt 界面控件。
                ui->labelcam->setGeometry(startRect);
                // 访问或更新 Qt 界面控件。
                ui->labelcam->setVisible(true);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                QGraphicsOpacityEffect *effect = new QGraphicsOpacityEffect(ui->labelcam);
                // 访问或更新 Qt 界面控件。
                ui->labelcam->setGraphicsEffect(effect);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                effect->setOpacity(0.0);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                QPropertyAnimation *opacityAnim = new QPropertyAnimation(effect, "opacity");
                // 执行本行语句完成对应变量、对象或业务状态处理。
                opacityAnim->setDuration(1000);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                opacityAnim->setStartValue(0.0);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                opacityAnim->setEndValue(1.0);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                QPropertyAnimation *scaleAnim = new QPropertyAnimation(ui->labelcam, "geometry");
                // 执行本行语句完成对应变量、对象或业务状态处理。
                scaleAnim->setDuration(1000);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                scaleAnim->setStartValue(startRect);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                scaleAnim->setEndValue(endRect);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                scaleAnim->setEasingCurve(QEasingCurve::OutElastic);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                QParallelAnimationGroup *group = new QParallelAnimationGroup(this);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                group->addAnimation(opacityAnim);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                group->addAnimation(scaleAnim);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                group->start(QAbstractAnimation::DeleteWhenStopped);
                // 执行本行语句完成对应变量、对象或业务状态处理。
                firstShow = false;
            // 结束当前代码块作用域。
            }
            // 访问或更新 Qt 界面控件。
            ui->labelcam->setPixmap(pix.scaled(ui->labelcam->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));
        // 结束当前代码块作用域。
        }
    // 结束当前代码块作用域。
    }
// 结束当前代码块作用域。
}

// 新增btn_doorcam点击槽函数实现
// 定义或声明函数 Widget::on_btngetframe_clicked。
void Widget::on_btngetframe_clicked()
// 进入新的代码块作用域。
{
    // 根据条件判断是否执行该分支。
    if (!udpSocket) {
        // 执行本行语句完成对应变量、对象或业务状态处理。
        udpSocket = new QUdpSocket(this);
        // 继续当前代码块的参数、表达式或结构定义。
        quint16 localPort = 50000; // 本地端口，和服务端推送端口一致
        // 根据条件判断是否执行该分支。
        if (!udpSocket->bind(QHostAddress::Any, localPort, QUdpSocket::ShareAddress | QUdpSocket::ReuseAddressHint)) {
            // 输出调试日志。
            qDebug() << "UDP bind failed:" << udpSocket->errorString();
            // 释放动态创建的对象资源。
            delete udpSocket;
            // 执行本行语句完成对应变量、对象或业务状态处理。
            udpSocket = nullptr;
            // 返回当前函数的执行结果或结束函数。
            return;
        // 结束当前代码块作用域。
        }
        // 建立 Qt 信号与槽或 lambda 回调连接。
        connect(udpSocket, &QUdpSocket::readyRead, this, &Widget::onUdpDataReceived);
        // 输出调试日志。
        qDebug() << "UDP socket started on port" << localPort;
    // 结束当前代码块作用域。
    }

    // 创建或设置网络主机地址。
    QHostAddress cameraAddr(smartserverDeviceIp());
    // 执行本行语句完成对应变量、对象或业务状态处理。
    quint16 cameraPort = 50000;

    // 根据条件判断是否执行该分支。
    if (!camActive) {
        // 开始接收：服务端先发 getframe，终端侧 CameraUdpServer 才开始按定时器推送 JPEG 帧。
        // 创建或使用字节数组保存协议或音视频数据。
        QByteArray requestData = "getframe";
        // 执行本行语句完成对应变量、对象或业务状态处理。
        udpSocket->writeDatagram(requestData, cameraAddr, cameraPort);
        // 输出调试日志。
        qDebug() << "Sent UDP 'getframe' to camera";
        // 继续当前代码块的参数、表达式或结构定义。
        firstShow = true; // 开启时重置动画标志
        // 执行本行语句完成对应变量、对象或业务状态处理。
        camActive = true;
    // 结束当前代码块作用域。
    } else {
        // 停止接收：通知终端停止发帧，同时隐藏本地画面，避免无效占用带宽。
        // 创建或使用字节数组保存协议或音视频数据。
        QByteArray requestData = "stop";
        // 执行本行语句完成对应变量、对象或业务状态处理。
        udpSocket->writeDatagram(requestData, cameraAddr, cameraPort);
        // 输出调试日志。
        qDebug() << "Sent UDP 'stop' to camera";
        // 访问或更新 Qt 界面控件。
        ui->labelcam->setVisible(false); // 直接隐藏
        // 执行本行语句完成对应变量、对象或业务状态处理。
        camActive = false;
        // 继续当前代码块的参数、表达式或结构定义。
        firstShow = true; // 下次再开时重新动画
    // 结束当前代码块作用域。
    }
// 结束当前代码块作用域。
}

// 定义或声明函数 Widget::onNewTcpConnection。
void Widget::onNewTcpConnection()
// 进入新的代码块作用域。
{
    // 开始循环处理满足条件的数据或状态。
    while (tcpServer->hasPendingConnections()) {
        // 执行本行语句完成对应变量、对象或业务状态处理。
        QTcpSocket *client = tcpServer->nextPendingConnection();
        // 执行本行语句完成对应变量、对象或业务状态处理。
        tcpClients.insert(client);
        // 建立 Qt 信号与槽或 lambda 回调连接。
        connect(client, &QTcpSocket::readyRead, this, [this, client]() { onTcpDataReceived(client); });
        // 建立 Qt 信号与槽或 lambda 回调连接。
        connect(client, &QTcpSocket::disconnected, this, [this, client]() {
            // 执行本行语句完成对应变量、对象或业务状态处理。
            tcpClients.remove(client);
            // 执行本行语句完成对应变量、对象或业务状态处理。
            client->deleteLater();
            // 输出调试日志。
            qDebug() << "TCP client disconnected:" << client;
        // 结束当前代码块作用域。
        });
        // 输出调试日志。
        qDebug() << "New TCP client connected from" << client->peerAddress().toString();
    // 结束当前代码块作用域。
    }
// 结束当前代码块作用域。
}

// 定义或声明函数 Widget::onTcpDataReceived。
void Widget::onTcpDataReceived(QTcpSocket *client)
// 进入新的代码块作用域。
{
    // 创建或使用字节数组保存协议或音视频数据。
    QByteArray data = client->readAll();
    // 输出调试日志。
    qDebug() << "Received TCP data from" << client << ":" << data;
    // 根据条件判断是否执行该分支。
    if (data.trimmed() == "call") {
        // TCP 只承担通话信令：call/accept/recstop/unlock；真正的音视频仍然走 UDP。
        // 执行本行语句完成对应变量、对象或业务状态处理。
        bool playRing = !ui->label_off->isVisible();
        // 根据条件判断是否执行该分支。
        if (!callForm) {
            // 继续当前代码块的参数、表达式或结构定义。
            callForm = new Form_phonecall(nullptr, playRing); // 不设parent，顶层窗口
            // 建立 Qt 信号与槽或 lambda 回调连接。
            connect(callForm, &Form_phonecall::accepted, this, [this, client](){
                // 根据条件判断是否执行该分支。
                if (client) {
                    // 执行本行语句完成对应变量、对象或业务状态处理。
                    client->write("accept\n");
                    // 执行本行语句完成对应变量、对象或业务状态处理。
                    client->flush();
                    // 输出调试日志。
                    qDebug() << "Sent TCP: accept";
                // 结束当前代码块作用域。
                }
            // 结束当前代码块作用域。
            });
            // 建立 Qt 信号与槽或 lambda 回调连接。
            connect(callForm, &Form_phonecall::hangupClicked, this, [this, client](){
                // 根据条件判断是否执行该分支。
                if (client) {
                    // 执行本行语句完成对应变量、对象或业务状态处理。
                    client->write("recstop");
                    // 输出调试日志。
                    qDebug() << "send recstop";
                    // 执行本行语句完成对应变量、对象或业务状态处理。
                    client->flush();
                // 结束当前代码块作用域。
                }
            // 结束当前代码块作用域。
            });
            // 建立 Qt 信号与槽或 lambda 回调连接。
            connect(callForm, &QObject::destroyed, this, [this]() { callForm = nullptr; });
            // 执行本行语句完成对应变量、对象或业务状态处理。
            callForm->setAttribute(Qt::WA_DeleteOnClose);
            // 执行本行语句完成对应变量、对象或业务状态处理。
            callForm->show();
            // 居中显示在widget_main范围内
            // 执行本行语句完成对应变量、对象或业务状态处理。
            QRect mainRect = ui->widget_main->geometry();
            // 执行本行语句完成对应变量、对象或业务状态处理。
            QPoint globalTopLeft = ui->widget_main->mapToGlobal(mainRect.topLeft());
            // 执行本行语句完成对应变量、对象或业务状态处理。
            QRect globalRect(globalTopLeft, mainRect.size());
            // 执行本行语句完成对应变量、对象或业务状态处理。
            QSize callSize = callForm->size();
            // 执行本行语句完成对应变量、对象或业务状态处理。
            QPoint center = globalRect.center();
            // 执行本行语句完成对应变量、对象或业务状态处理。
            QPoint topLeft(center.x() - callSize.width()/2, center.y() - callSize.height()/2);
            // 执行本行语句完成对应变量、对象或业务状态处理。
            callForm->move(topLeft);
        // 结束当前代码块作用域。
        }
    // 结束当前代码块作用域。
    } else if (data.trimmed() == "stopsend") {
        // 根据条件判断是否执行该分支。
        if (callForm) {
            // 执行本行语句完成对应变量、对象或业务状态处理。
            callForm->close();
            // 执行本行语句完成对应变量、对象或业务状态处理。
            callForm = nullptr;
        // 结束当前代码块作用域。
        }
    // 结束当前代码块作用域。
    } else if (data.trimmed() == "unlock") {
        // 这里可以处理unlock指令
    // 结束当前代码块作用域。
    }
// 结束当前代码块作用域。
}

// 定义或声明函数 Widget::on_btn_lock_clicked。
void Widget::on_btn_lock_clicked()
// 进入新的代码块作用域。
{
    // 群发unlock到所有客户端
    // 开始循环处理满足条件的数据或状态。
    for (QTcpSocket *client : tcpClients) {
        // 根据条件判断是否执行该分支。
        if (client && client->state() == QAbstractSocket::ConnectedState) {
            // 执行本行语句完成对应变量、对象或业务状态处理。
            client->write("unlock\n");
            // 执行本行语句完成对应变量、对象或业务状态处理。
            client->flush();
            // 输出调试日志。
            qDebug() << "Sent TCP: unlock to client" << client;
        // 结束当前代码块作用域。
        }
    // 结束当前代码块作用域。
    }
// 结束当前代码块作用域。
}

// 定义或声明函数 Widget::on_btn_home_clicked。
void Widget::on_btn_home_clicked()
// 进入新的代码块作用域。
{
    // 根据条件判断是否执行该分支。
    if(ui->widget_light->isVisible()){
        // 输出调试日志。
        qDebug()<<"novisabel";
        // 访问或更新 Qt 界面控件。
        ui->widget_light->setVisible(false);
    // 结束当前代码块作用域。
    }else{
        // 访问或更新 Qt 界面控件。
        ui->widget_light->setVisible(true);
        // 输出调试日志。
        qDebug()<<"sabel";
    // 结束当前代码块作用域。
    }
// 结束当前代码块作用域。
}


// 定义或声明函数 Widget::on_btn_tea_clicked。
void Widget::on_btn_tea_clicked()
// 进入新的代码块作用域。
{
    // 茶桌圆灯
    // 根据条件判断是否执行该分支。
    if (serialPort && serialPort->isOpen()) {
        // 执行本行语句完成对应变量、对象或业务状态处理。
        serialPort->write((char*)hexArrayDeskRound, sizeof(hexArrayDeskRound));
        // 输出调试日志。
        qDebug() << "发送茶桌圆灯控制命令";
    // 结束当前代码块作用域。
    } else {
        // 输出调试日志。
        qDebug() << "串口未打开，无法发送命令";
    // 结束当前代码块作用域。
    }
// 结束当前代码块作用域。
}

// 定义或声明函数 Widget::on_btn_teab_clicked。
void Widget::on_btn_teab_clicked()
// 进入新的代码块作用域。
{
    // 工位圆灯
    // 根据条件判断是否执行该分支。
    if (serialPort && serialPort->isOpen()) {
        // 执行本行语句完成对应变量、对象或业务状态处理。
        serialPort->write((char*)hexArrayWorkRound, sizeof(hexArrayWorkRound));
        // 输出调试日志。
        qDebug() << "发送工位圆灯控制命令";
    // 结束当前代码块作用域。
    } else {
        // 输出调试日志。
        qDebug() << "串口未打开，无法发送命令";
    // 结束当前代码块作用域。
    }
// 结束当前代码块作用域。
}

// 定义或声明函数 Widget::on_btn_white_clicked。
void Widget::on_btn_white_clicked()
// 进入新的代码块作用域。
{
    // 茶桌灯
    // 根据条件判断是否执行该分支。
    if (serialPort && serialPort->isOpen()) {
        // 执行本行语句完成对应变量、对象或业务状态处理。
        serialPort->write((char*)hexArrayDesk, sizeof(hexArrayDesk));
        // 输出调试日志。
        qDebug() << "发送茶桌灯控制命令";
    // 结束当前代码块作用域。
    } else {
        // 输出调试日志。
        qDebug() << "串口未打开，无法发送命令";
    // 结束当前代码块作用域。
    }
// 结束当前代码块作用域。
}
