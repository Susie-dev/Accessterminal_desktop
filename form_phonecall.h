// 开始头文件防重复包含保护 FORM_PHONECALL_H。
#ifndef FORM_PHONECALL_H
// 定义预处理宏或常量 FORM_PHONECALL_H。
#define FORM_PHONECALL_H

// 引入系统或第三方头文件 <QWidget>。
#include <QWidget>
// 引入系统或第三方头文件 <QMouseEvent>。
#include <QMouseEvent>
// 引入系统或第三方头文件 <QUdpSocket>。
#include <QUdpSocket>
// 引入系统或第三方头文件 <QAudioInput>。
#include <QAudioInput>
// 引入系统或第三方头文件 <QAudioOutput>。
#include <QAudioOutput>
// 引入系统或第三方头文件 <QAudioFormat>。
#include <QAudioFormat>
// 引入系统或第三方头文件 <QIODevice>。
#include <QIODevice>
// 引入系统或第三方头文件 <QHostAddress>。
#include <QHostAddress>
// 引入系统或第三方头文件 <QPushButton>。
#include <QPushButton>
// 引入项目内部头文件 "slidehintwidget.h"。
#include "slidehintwidget.h"
// 引入系统或第三方头文件 <QMediaPlayer>。
#include <QMediaPlayer>
// 引入系统或第三方头文件 <QAudioOutput>。
#include <QAudioOutput>


// 声明或进入命名空间 Ui。
namespace Ui {
// 声明类 Form_phonecall。
class Form_phonecall;
// 结束当前代码块作用域。
}

// 声明类 Form_phonecall。
class Form_phonecall : public QWidget
// 进入新的代码块作用域。
{
    // 继续当前代码块的参数、表达式或结构定义。
    Q_OBJECT

// 声明类成员的 public 访问权限区域。
public:
    // 声明显式构造函数 Form_phonecall。
    explicit Form_phonecall(QWidget *parent = nullptr, bool playRing = true);
    // 声明或定义析构函数 Form_phonecall。
    ~Form_phonecall();

// 声明类成员的 private 访问权限区域。
private:
    // 执行本行语句完成对应变量、对象或业务状态处理。
    Ui::Form_phonecall *ui;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    bool dragging = false;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    int dragOffset = 0;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QUdpSocket *audioSocket = nullptr;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QUdpSocket *videoSocket = nullptr;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QAudioOutput *audioOutput = nullptr;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QIODevice *audioDevice = nullptr;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QAudioInput *audioInput = nullptr;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QIODevice *inputDevice = nullptr;
    // 创建或使用字节数组保存协议或音视频数据。
    QByteArray audioBuffer;
    // 创建或使用字节数组保存协议或音视频数据。
    QByteArray inputBuffer;
    // 创建或设置网络主机地址。
    QHostAddress t113Address;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    quint16 t113Port = 0;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QPushButton *btn_hangup = nullptr;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    SlideHintWidget *hint = nullptr;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QMediaPlayer *ringPlayer = nullptr;
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QAudioOutput *ringAudio = nullptr;

    // 定义或声明函数 startAV。
    void startAV();
    // 定义或声明函数 stopAV。
    void stopAV();

// 声明 Qt 信号槽成员区域。
private slots:
    // 定义或声明函数 onAudioDataReady。
    void onAudioDataReady();
    // 定义或声明函数 onInputReady。
    void onInputReady();
    // 定义或声明函数 onVideoDataReady。
    void onVideoDataReady();
    // 定义或声明函数 writeAudioData。
    void writeAudioData();
    // 定义或声明函数 onRingStateChanged。
    void onRingStateChanged(QMediaPlayer::State state);

// 声明类成员的 protected 访问权限区域。
protected:
    // 定义或声明函数 eventFilter。
    bool eventFilter(QObject *watched, QEvent *event) override;
    // 定义或声明函数 closeEvent。
    void closeEvent(QCloseEvent *event) override;
//    void mousePressEvent(QMouseEvent *event) override;
//    void mouseMoveEvent(QMouseEvent *event) override;
//    void mouseReleaseEvent(QMouseEvent *event) override;

// 声明 Qt 信号槽成员区域。
signals:
    // 定义或声明函数 answered。
    void answered();
    // 定义或声明函数 accepted。
    void accepted();
    // 定义或声明函数 hangupClicked。
    void hangupClicked();
// 结束当前代码块作用域。
};

// 结束当前预处理条件块。
#endif // FORM_PHONECALL_H
