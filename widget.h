// 开始头文件防重复包含保护 WIDGET_H。
#ifndef WIDGET_H
// 定义预处理宏或常量 WIDGET_H。
#define WIDGET_H

// 引入系统或第三方头文件 <QWidget>。
#include <QWidget>
// 引入系统或第三方头文件 <QNetworkReply>。
#include <QNetworkReply>
// 引入系统或第三方头文件 <QTimer>。
#include <QTimer>
// 引入系统或第三方头文件 <QUdpSocket>。
#include <QUdpSocket>
// 引入系统或第三方头文件 <QGraphicsOpacityEffect>。
#include <QGraphicsOpacityEffect>
// 引入系统或第三方头文件 <QPropertyAnimation>。
#include <QPropertyAnimation>
// 引入系统或第三方头文件 <QTcpServer>。
#include <QTcpServer>
// 引入系统或第三方头文件 <QTcpSocket>。
#include <QTcpSocket>
// 引入系统或第三方头文件 <QSerialPort>。
#include <QSerialPort>
// 引入系统或第三方头文件 <QSet>。
#include <QSet>

// 引入项目内部头文件 "form_phonecall.h"。
#include "form_phonecall.h"
// 进入 Qt 命名空间声明区域。
QT_BEGIN_NAMESPACE
// 声明或进入命名空间 Ui。
namespace Ui { class Widget; }
// 结束 Qt 命名空间声明区域。
QT_END_NAMESPACE

// 声明类 Widget。
class Widget : public QWidget
// 进入新的代码块作用域。
{
    // 继续当前代码块的参数、表达式或结构定义。
    Q_OBJECT

// 声明类成员的 public 访问权限区域。
public:
    // 执行本行语句完成对应变量、对象或业务状态处理。
    Widget(QWidget *parent = nullptr);
    // 声明或定义析构函数 Widget。
    ~Widget();

// 声明 Qt 信号槽成员区域。
private slots:
    // 定义或声明函数 on_btn_power_clicked。
    void on_btn_power_clicked();
    // 定义或声明函数 on_btn_offline_clicked。
    void on_btn_offline_clicked();
    // 定义或声明函数 readHttpRply。
    void readHttpRply();
    // 定义或声明函数 requestWeather。
    void requestWeather();
    // 定义或声明函数 time_reflash。
    void time_reflash();
    // 定义或声明函数 onUdpDataReceived。
    void onUdpDataReceived();
    // 定义或声明函数 onNewTcpConnection。
    void onNewTcpConnection();
    // 定义或声明函数 onTcpDataReceived。
    void onTcpDataReceived(QTcpSocket *client);


    // 定义或声明函数 on_btngetframe_clicked。
    void on_btngetframe_clicked();
    // 定义或声明函数 on_btn_lock_clicked。
    void on_btn_lock_clicked();
    // 定义或声明函数 on_btn_home_clicked。
    void on_btn_home_clicked();

    // 定义或声明函数 on_btn_tea_clicked。
    void on_btn_tea_clicked();

    // 定义或声明函数 on_btn_teab_clicked。
    void on_btn_teab_clicked();

    // 定义或声明函数 on_btn_white_clicked。
    void on_btn_white_clicked();

// 声明类成员的 private 访问权限区域。
private:
    // 执行本行语句完成对应变量、对象或业务状态处理。
    Ui::Widget *ui;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    bool offmark;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QNetworkReply *reply = nullptr;
    // 创建或使用 Qt 定时器对象。
    QTimer *sysTimeTimer = nullptr;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QString myDate;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QString myTime;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QUdpSocket *udpSocket = nullptr;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    bool camActive = false;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    bool firstShow = true;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QTcpServer *tcpServer = nullptr;
    // QTcpSocket *tcpClientSocket = nullptr;
    // 支持多个 T113 客户端接入，开锁信令会广播给当前在线的所有终端。
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QSet<QTcpSocket*> tcpClients;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    Form_phonecall *callForm = nullptr;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QSerialPort *serialPort;
    // 茶桌灯
    // 执行本行语句完成对应变量、对象或业务状态处理。
    unsigned char hexArrayDesk[7] = {0xFD, 0x03, 0x4C, 0x12, 0x04, 0x5D, 0xDF};
    // 工位灯
    // 执行本行语句完成对应变量、对象或业务状态处理。
    unsigned char hexArrayWork[7] = {0xFD, 0x03, 0x4C, 0x12, 0x02, 0x5D, 0xDF};
    // 工位圆灯
    // 执行本行语句完成对应变量、对象或业务状态处理。
    unsigned char hexArrayWorkRound[7] = {0xFD, 0x03, 0x97, 0x36, 0xF4, 0x4F, 0xDF};
    // 茶桌圆灯
    // 执行本行语句完成对应变量、对象或业务状态处理。
    unsigned char hexArrayDeskRound[7] = {0xFD, 0x03, 0x97, 0x36, 0xF2, 0x50, 0xDF};
    // 墙面射灯
    // 执行本行语句完成对应变量、对象或业务状态处理。
    unsigned char hexArrayWall[7] = {0xFD, 0x03, 0x97, 0x36, 0xF1, 0x50, 0xDF};
// 结束当前代码块作用域。
};
// 结束当前预处理条件块。
#endif // WIDGET_H
