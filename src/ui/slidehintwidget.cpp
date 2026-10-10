// 引入项目内部头文件 "slidehintwidget.h"。
#include "ui/slidehintwidget.h"
// 引入系统或第三方头文件 <QPainter>。
#include <QPainter>
// 引入系统或第三方头文件 <QLinearGradient>。
#include <QLinearGradient>

// 定义类 SlideHintWidget 的成员函数 SlideHintWidget。
SlideHintWidget::SlideHintWidget(QWidget *parent)
    // 继续当前代码块的参数、表达式或结构定义。
    : QWidget(parent), pos(0)
// 进入新的代码块作用域。
{
    // 执行本行语句完成对应变量、对象或业务状态处理。
    timer = new QTimer(this);
    // 建立 Qt 信号与槽或 lambda 回调连接。
    connect(timer, &QTimer::timeout, this, [this]() {
        // 继续当前代码块的参数、表达式或结构定义。
        pos += 5; // 速度加快
        // 执行本行语句完成对应变量、对象或业务状态处理。
        int lightWidth = 100;
        // 根据条件判断是否执行该分支。
        if (pos > width()-100) pos = -lightWidth+80; // 流光从左侧外部开始
        // 执行本行语句完成对应变量、对象或业务状态处理。
        update();
    // 结束当前代码块作用域。
    });
    // 执行本行语句完成对应变量、对象或业务状态处理。
    timer->start(10);
    // 继续当前代码块的参数、表达式或结构定义。
    setAttribute(Qt::WA_TransparentForMouseEvents, true); // 不拦截鼠标事件
// 结束当前代码块作用域。
}

// 定义或声明函数 SlideHintWidget::paintEvent。
void SlideHintWidget::paintEvent(QPaintEvent *)
// 进入新的代码块作用域。
{
    // 创建绘图对象用于在图像或控件上绘制内容。
    QPainter p(this);
    // --- 胶囊背景 ---
    // 继续当前代码块的参数、表达式或结构定义。
    int bgRadius = height() / 2 + 10; // 胶囊背景大圆角
    // 执行本行语句完成对应变量、对象或业务状态处理。
    p.setRenderHint(QPainter::Antialiasing, true);
    // 继续当前代码块的参数、表达式或结构定义。
    QLinearGradient bg(100, 0, width(), 0); // 黑到白渐变
    // 执行本行语句完成对应变量、对象或业务状态处理。
    bg.setColorAt(0, QColor(0,0,0,180));
    // 执行本行语句完成对应变量、对象或业务状态处理。
    bg.setColorAt(1, QColor(255,255,255,180));
    // 执行本行语句完成对应变量、对象或业务状态处理。
    p.setPen(Qt::NoPen);
    // 执行本行语句完成对应变量、对象或业务状态处理。
    p.setBrush(bg);
    // 执行本行语句完成对应变量、对象或业务状态处理。
    p.drawRoundedRect(rect(), bgRadius, bgRadius);

    // --- 流光 ---
    // 执行本行语句完成对应变量、对象或业务状态处理。
    int lightWidth = 100;
    // 继续当前代码块的参数、表达式或结构定义。
    int lightRadius = qMin(lightWidth, height()) / 2; // 流光圆角不能大于自身宽/高一半
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QLinearGradient light(pos, 0, pos+lightWidth, 0);
    // 执行本行语句完成对应变量、对象或业务状态处理。
    light.setColorAt(0, QColor(0,0,0,0));
    // 执行本行语句完成对应变量、对象或业务状态处理。
    light.setColorAt(0.5, QColor(255,255,255,220));
    // 执行本行语句完成对应变量、对象或业务状态处理。
    light.setColorAt(1, QColor(0,0,0,0));
    // 执行本行语句完成对应变量、对象或业务状态处理。
    p.setBrush(light);
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QRect lightRect(pos, 0, lightWidth, height());
    // 执行本行语句完成对应变量、对象或业务状态处理。
    p.drawRoundedRect(lightRect, lightRadius, lightRadius);
// 结束当前代码块作用域。
} 
