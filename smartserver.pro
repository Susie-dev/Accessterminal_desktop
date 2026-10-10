# ============================================================================
# Accessterminal_desktop — 室内机（对讲主机 / 控制面板）
#
# 说明：本文件为兼容 Qt Creator / qmake 工作流的构建脚本。
#       推荐入口为 CMakeLists.txt，两者源文件集合保持一致。
# ============================================================================

QT += core gui network multimedia serialport
greaterThan(QT_MAJOR_VERSION, 4): QT += widgets

CONFIG += c++11 warn_on

TARGET = smartserver
TEMPLATE = app

# 使源码内 #include "core/net/protocol.h" 等以 src/ 为根
INCLUDEPATH += $$PWD/src

SOURCES += \
    src/main.cpp \
    src/config/app_config.cpp \
    src/core/net/signaling_server.cpp \
    src/core/net/monitor_client.cpp \
    src/core/media/call_session.cpp \
    src/core/weather/weather_service.cpp \
    src/hal/serial_light.cpp \
    src/ui/widget.cpp \
    src/ui/form_phonecall.cpp \
    src/ui/slidehintwidget.cpp

HEADERS += \
    src/config/app_config.h \
    src/core/net/protocol.h \
    src/core/net/signaling_server.h \
    src/core/net/monitor_client.h \
    src/core/media/call_session.h \
    src/core/weather/weather_service.h \
    src/hal/serial_light.h \
    src/ui/widget.h \
    src/ui/form_phonecall.h \
    src/ui/slidehintwidget.h

FORMS += \
    src/ui/widget.ui \
    src/ui/form_phonecall.ui

RESOURCES += \
    src/resources/res.qrc

# Default rules for deployment.
qnx: target.path = /tmp/$${TARGET}/bin
else: unix:!android: target.path = /opt/$${TARGET}/bin
!isEmpty(target.path): INSTALLS += target
