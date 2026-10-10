// 引入项目内部头文件 "widget.h"。
#include "widget.h"

// 引入系统或第三方头文件 <QApplication>。
#include <QApplication>
// 引入系统或第三方头文件 <form_phonecall.h>。
#include <form_phonecall.h>

// 定义或声明函数 main。
int main(int argc, char *argv[])
// 进入新的代码块作用域。
{
    // 执行本行语句完成对应变量、对象或业务状态处理。
    QApplication a(argc, argv);
    // 执行本行语句完成对应变量、对象或业务状态处理。
    Widget w;
//    Form_phonecall f;
//    f.show();
    // 执行本行语句完成对应变量、对象或业务状态处理。
    w.show();
    // 返回当前函数的执行结果或结束函数。
    return a.exec();
// 结束当前代码块作用域。
}
