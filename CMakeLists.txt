#
# Accessterminal_desktop — 室内机（对讲主机 / 控制面板）
#
# 构建：
#   cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo
#   cmake --build build -j
#   ./build/bin/smartserver
#
# 单元测试：
#   cmake -S . -B build -DACCESSTERMINAL_BUILD_TESTS=ON
#   cmake --build build && ctest --test-dir build --output-on-failure
#
cmake_minimum_required(VERSION 3.16)

project(Accessterminal_desktop
    VERSION 1.0.0
    DESCRIPTION "别墅门禁可视化对讲系统 — 室内机"
    LANGUAGES CXX)

# ---------------------------------------------------------------------------
# 全局编译设置
# ---------------------------------------------------------------------------
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# 使源码内 #include "core/net/protocol.h" 等以 src/ 为根。
set(CMAKE_INCLUDE_CURRENT_DIR ON)

# ---------------------------------------------------------------------------
# 警告设置
#
# 默认开启 -Wall -Wextra，让“定义了却没用到的函数”“有符号/无符号比较”
# 这类问题在编译期就暴露，而不是等运行时。
# 不启用 -Werror：不同 GCC/Qt 版本的告警集合会变，卡死构建反而无益。
# ---------------------------------------------------------------------------
option(ACCESSTERMINAL_WARNINGS "开启编译警告 (-Wall -Wextra)" ON)

if(ACCESSTERMINAL_WARNINGS AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(-Wall -Wextra)
    # 未使用的参数在 Qt 的虚函数重写与信号槽里很常见，噪声大于价值。
    add_compile_options(-Wno-unused-parameter)
endif()

set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "构建类型" FORCE)
endif()

# ---------------------------------------------------------------------------
# 依赖
# ---------------------------------------------------------------------------
find_package(Qt5 5.12 REQUIRED COMPONENTS
    Core Gui Widgets Network Multimedia SerialPort)

# ---------------------------------------------------------------------------
# 源文件
#
# AUTOUIC 会为每个 .ui 在其所在目录生成 ui_*.h，因此 .ui 需与对应
# .cpp 处于同一目录（现均为 src/ui/）。
# ---------------------------------------------------------------------------
set(APP_SOURCES
    src/main.cpp

    src/config/app_config.cpp

    src/core/net/signaling_server.cpp
    src/core/net/monitor_client.cpp
    src/core/media/call_session.cpp
    src/core/weather/weather_service.cpp

    src/hal/serial_light.cpp

    src/ui/widget.cpp
    src/ui/form_phonecall.cpp
    src/ui/slidehintwidget.cpp
)

set(APP_HEADERS
    src/config/app_config.h

    src/core/net/protocol.h
    src/core/net/signaling_server.h
    src/core/net/monitor_client.h
    src/core/media/call_session.h
    src/core/weather/weather_service.h

    src/hal/serial_light.h

    src/ui/widget.h
    src/ui/form_phonecall.h
    src/ui/slidehintwidget.h
)

set(APP_FORMS
    src/ui/widget.ui
    src/ui/form_phonecall.ui
)

set(APP_RESOURCES
    src/resources/res.qrc
)

source_group("Sources"   FILES ${APP_SOURCES})
source_group("Headers"   FILES ${APP_HEADERS})
source_group("Forms"     FILES ${APP_FORMS})
source_group("Resources" FILES ${APP_RESOURCES})

# ---------------------------------------------------------------------------
# 目标
# ---------------------------------------------------------------------------
add_executable(smartserver
    ${APP_SOURCES}
    ${APP_HEADERS}
    ${APP_FORMS}
    ${APP_RESOURCES}
)

target_include_directories(smartserver PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_link_libraries(smartserver PRIVATE
    Qt5::Core Qt5::Gui Qt5::Widgets Qt5::Network Qt5::Multimedia Qt5::SerialPort
)

set_target_properties(smartserver PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin
)

# ---------------------------------------------------------------------------
# 安装
# ---------------------------------------------------------------------------
include(GNUInstallDirs)

install(TARGETS smartserver RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
install(FILES config/appconfig.json
        DESTINATION ${CMAKE_INSTALL_SYSCONFDIR}/accessterminal)

# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------
option(ACCESSTERMINAL_BUILD_TESTS "构建单元测试" OFF)
if(ACCESSTERMINAL_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()
