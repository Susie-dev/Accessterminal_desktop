/**
 * @file main.cpp
 * @brief 室内机程序入口。
 */
#include "config/app_config.h"
#include "core/net/protocol.h"
#include "ui/widget.h"

#include <QApplication>
#include <QDebug>

int main(int argc, char* argv[])
{
    QApplication app(argc, argv);

    // 配置须在窗口与各模块构造之前载入。
    // 支持命令行覆盖：./smartserver /path/to/appconfig.json
    const QString configPath = argc > 1 ? QString::fromLocal8Bit(argv[1]) : QString();
    const bool fromFile = accessterminal::AppConfig::instance().load(configPath);

    qInfo() << "[启动] Accessterminal 室内机，协议版本"
            << accessterminal::protocol::kProtocolVersion;
    qInfo() << "[启动] 配置来源:"
            << (fromFile ? accessterminal::AppConfig::instance().configPath()
                         : QStringLiteral("内置默认值"));

    Widget widget;
    widget.show();
    return app.exec();
}
