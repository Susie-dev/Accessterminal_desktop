#
# 单元测试。两种用法：
#
#   A. 独立构建（不依赖主工程，桌面机/Linux 均可）：
#        cmake -S tests -B /tmp/desktop-tests -G Ninja
#        cmake --build /tmp/desktop-tests
#        ctest --test-dir /tmp/desktop-tests --output-on-failure
#
#   B. 作为主工程的子目录（随 -DACCESSTERMINAL_BUILD_TESTS=ON 启用）：
#        cmake -S . -B build -DACCESSTERMINAL_BUILD_TESTS=ON
#
# 为什么必须有 cmake_minimum_required / project() / enable_testing()：
# 用法 B 时这三者都由主 CMakeLists.txt 提供，本文件作为片段（fragment）
# 无所谓；但用法 A 下会分别报
#   "No cmake_minimum_required command is present"（配置阶段直接失败）
#   "No tests were found!!!"（构建成功却一个用例都跑不到）
# 即——独立构建这条路看起来能用、实际从来没有真的跑起来过。这与门口机
# 侧是同一个缺陷，两侧对称修复。三行在用法 B 下均幂等。
#
# 测试是纯逻辑（协议编解码），只依赖 Qt5::Core/Test。
#
cmake_minimum_required(VERSION 3.16)
project(accessterminal_desktop_tests LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# test_protocol.cpp 末尾有 `#include "test_protocol.moc"`，必须开 AUTOMOC。
set(CMAKE_AUTOMOC ON)

# 独立构建时必须自己启用测试注册，否则 add_test() 不生效。
enable_testing()

find_package(Qt5 5.12 REQUIRED COMPONENTS Core Test Network Gui)

# 作为子目录被主工程引入时 CMAKE_SOURCE_DIR 指向主工程根，src 在其下；
# 独立构建时 CMAKE_SOURCE_DIR 就是 tests/，src 在上一级。两种都要能工作。
if(EXISTS "${CMAKE_SOURCE_DIR}/src/core/net/protocol.h")
    set(ACCESSTERMINAL_SRC_ROOT "${CMAKE_SOURCE_DIR}/src")
else()
    get_filename_component(ACCESSTERMINAL_SRC_ROOT
                           "${CMAKE_CURRENT_LIST_DIR}/../src" ABSOLUTE)
endif()

# ---------------------------------------------------------------------------
# 协议契约测试
# ---------------------------------------------------------------------------
add_executable(desktop_test_protocol test_protocol.cpp)

target_include_directories(desktop_test_protocol PRIVATE
    ${ACCESSTERMINAL_SRC_ROOT}
)

target_link_libraries(desktop_test_protocol PRIVATE
    Qt5::Core
    Qt5::Test
)

add_test(NAME desktop_protocol COMMAND desktop_test_protocol)

# ---------------------------------------------------------------------------
# 配置解析测试（灯控指令十六进制解析）
#
# 这是本工程第二个单元测试目标，需要链接真实的 src/config/app_config.cpp。
# 不依赖硬件/网络，可在无串口的开发机上完整运行。
# ---------------------------------------------------------------------------
add_executable(desktop_test_app_config
    test_app_config.cpp
    ${ACCESSTERMINAL_SRC_ROOT}/config/app_config.cpp
)

target_include_directories(desktop_test_app_config PRIVATE
    ${ACCESSTERMINAL_SRC_ROOT}
)

target_link_libraries(desktop_test_app_config PRIVATE
    Qt5::Core
    Qt5::Test
)

add_test(NAME desktop_app_config COMMAND desktop_test_app_config)

# ---------------------------------------------------------------------------
# SignalingServer：室内机 TCP 8887 信令服务端
#
# TCP 8887 是本项目**第一条协议硬约束**，但室内机侧的 SignalingServer
# （接收门口机的 call/stopsend/unlock，回 accept/recstop/unlock）此前没有任何
# 单元测试 —— 只有协议编解码被 test_protocol.cpp 覆盖，服务端自己的行为
# （接入/断开、按连接分流的解码器、回执、广播、停止）全无覆盖。
#
# 本目标用**真实 QTcpSocket** 连到真实 QTcpServer 上，走完整事件循环：bind、
# newConnection、readyRead 派发、disconnected 清理一并被验证，而不是直接调
# 私有槽（那会绕开真正的线上路径）。不需要任何硬件。
#
# 不需要测试替身，因此直接链接真实的 signaling_server.cpp。
# ---------------------------------------------------------------------------
add_executable(desktop_test_signaling_server
    test_signaling_server.cpp
    ${ACCESSTERMINAL_SRC_ROOT}/core/net/signaling_server.cpp
)

target_include_directories(desktop_test_signaling_server PRIVATE
    ${ACCESSTERMINAL_SRC_ROOT}
)

target_link_libraries(desktop_test_signaling_server PRIVATE
    Qt5::Core
    Qt5::Test
    Qt5::Network
)

add_test(NAME desktop_signaling_server COMMAND desktop_test_signaling_server)

# ---------------------------------------------------------------------------
# MonitorClient：室内机 UDP 50000 远程监看客户端
#
# UDP 50000 是**协议硬约束**的一员，而且语义与另外三条都不同：
#   - 请求文本是**裸的、不带 '\n'**（与 TCP 8887 信令不同！）；
#   - 门口机**只有收到 getframe 之后**才开始按 50ms 定时器推帧；
#   - 收到 stop 就停推；每包一帧完整 JPEG，无重组、无重传。
#
# 门口机侧（CameraUdpServer）已有 t113_test_camera_preview 覆盖，
# 但室内机侧这一半从来没有测过 —— 两条半必须配对，否则一边改了字节，
# 另一边的测试还是绿的，而互操作已经断了。
#
# 用**真实 QUdpSocket** + 真实事件循环，不调私有槽：
# 假门口机绑在 127.0.0.2:50000，MonitorClient 绑 Any:50000 并把 deviceIp
# 设为 127.0.0.2。于是"发出的请求"与"收到的帧"归属都是确定的。
#
# 为什么必须显式链 Qt5::Gui：onReadyRead() 用的是 **QPixmap**
# （QPixmap::loadFromData），不是 QImage。QTEST_MAIN 在链了 Qt5::Gui 时
# 会生成 QGuiApplication，从而让 QPixmap 在无显示的开发机上也能工作
# （实测平台插件 = windows，loadFromData 成功）。
#
# 不需要测试替身，直接链接真实的 monitor_client.cpp。
# ---------------------------------------------------------------------------
add_executable(desktop_test_monitor_client
    test_monitor_client.cpp
    ${ACCESSTERMINAL_SRC_ROOT}/core/net/monitor_client.cpp
)

target_include_directories(desktop_test_monitor_client PRIVATE
    ${ACCESSTERMINAL_SRC_ROOT}
)

target_link_libraries(desktop_test_monitor_client PRIVATE
    Qt5::Core
    Qt5::Test
    Qt5::Network
    Qt5::Gui
)

add_test(NAME desktop_monitor_client COMMAND desktop_test_monitor_client)

# ---------------------------------------------------------------------------
# WeatherService：天气获取与文案格式化
#
# 这个文件此前**从未被任何测试目标链接**。它做三件都会伤到用户的事：
# 解析第三方 JSON、拼出用户直接看到的文案、出错时 emit errorOccurred。
#
# 起因是它代码里最长的那段注释（abandonReply() 上方）断言的是一条
# **从未被验证过的因果链**。第 32 轮用探针实测（%TEMP%\probe32\）：
#   - abort() **确实同步**投递 finished()（5/5 次，三种状态下都成立）
#     -> 注释的**前提**是对的；
#   - 但预测的"空指针解引用**崩溃**"**没有复现**（nullptr->deleteLater()
#     是 UB，而 QObject::deleteLater() 不解引用，侥幸活着）
#     -> 注释描述的**具体后果过强了**；
#   - 真正可观测的后果是**假错误**：
#       正确顺序（先断连接+先摘成员）：finished 处理 0 次，错误信号 0 个
#       错误顺序（直接 abort）        ：finished 处理 1 次，错误信号 1 个
#       消息 = "天气请求失败: Operation canceled (HTTP 200)"
#     -> 每次刷新取消在途请求，界面都会闪一条假错误。
# 测试守的是最后这条真实差异，文本已按实测改写。
#
# 用**真实 QTcpServer** 当天气接口 + 真实事件循环，不 mock 网络、不调私有槽。
# 通过 ACCESSTERMINAL_WEATHER_URL 把 AppConfig 指到该服务端。
#
# 链接真实的 weather_service.cpp 与 app_config.cpp（后者提供 URL 与解析）。
# ---------------------------------------------------------------------------
add_executable(desktop_test_weather_service
    test_weather_service.cpp
    ${ACCESSTERMINAL_SRC_ROOT}/core/weather/weather_service.cpp
    ${ACCESSTERMINAL_SRC_ROOT}/config/app_config.cpp
)

target_include_directories(desktop_test_weather_service PRIVATE
    ${ACCESSTERMINAL_SRC_ROOT}
)

target_link_libraries(desktop_test_weather_service PRIVATE
    Qt5::Core
    Qt5::Test
    Qt5::Network
)

add_test(NAME desktop_weather_service COMMAND desktop_test_weather_service)

# ---------------------------------------------------------------------------
# SerialLight：室内机串口灯控
#
# `src/hal/serial_light.cpp` 此前**从未被任何测试目标链接**。它只有 89 行，
# 却是"把灯控指令写到硬件"的唯一出口，且有两条**只靠日志区分**的失败分支
# （指令名未知 / 串口未打开）——现场排障完全依赖这两条日志分得清楚。
#
# 难点：SerialLight 把 QSerialPort 当**具体类型**用（new QSerialPort(this)、
# m_port->write(...)），既不是虚函数也不可注入；本机（Windows/MinGW）又没有
# 真实串口。两条路都试过：
#   - 用 Windows 命名管道冒充串口：实测会卡在 QSerialPort::open()，且依赖
#     `\\.\pipe\` 这个平台细节，脆弱且不可移植 -> 放弃；
#   - **影子头文件**：把替身命名为 `QSerialPort` 放在 tests/fake_serial_port/，
#     用 `target_include_directories(BEFORE ...)` 插到 Qt 的 include 路径之前，
#     于是 `#include <QSerialPort>` 命中替身。已用探针实测确认生效
#     （%TEMP%\probe33\shadow.cpp：影子生效时退出码 0）。
#
# 这样测的仍是**真实的 serial_light.cpp**、同一条代码路径，只把最底层的系统
# 调用换成可记录的替身；"打开失败要发信号"、"写入不完整要发信号"、"未打开
# 不许写"这些分支都能真的被执行到，而不是靠读代码推断。
#
# 安全阀：影子头会顶掉真正的 Qt 头，因此它要求显式定义 ACC_SERIAL_LIGHT_TEST，
# 否则直接 `#error`。只有本目标定义它，产线目标不可能误命中。
# 另：影子头不在任何目标的源列表里，AUTOMOC 不会处理它，所以它**不带
# Q_OBJECT**（SerialLight 也从不 connect 它的信号）。
# ---------------------------------------------------------------------------
add_executable(desktop_test_serial_light
    test_serial_light.cpp
    fake_serial_port.cpp
    ${ACCESSTERMINAL_SRC_ROOT}/hal/serial_light.cpp
    ${ACCESSTERMINAL_SRC_ROOT}/config/app_config.cpp
)

# BEFORE 是关键：必须排在 Qt5::SerialPort 带来的 include 目录**之前**，
# 影子头才会被命中。少了 BEFORE 就会悄悄用上真的 Qt 头，而测试表现是
# "链接期缺少 QSerialPort 的符号"，很容易误判成别的毛病。
target_include_directories(desktop_test_serial_light BEFORE PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/fake_serial_port
)

target_include_directories(desktop_test_serial_light PRIVATE
    ${ACCESSTERMINAL_SRC_ROOT}
    ${CMAKE_CURRENT_LIST_DIR}
)

target_compile_definitions(desktop_test_serial_light PRIVATE
    ACC_SERIAL_LIGHT_TEST
)

target_link_libraries(desktop_test_serial_light PRIVATE
    Qt5::Core
    Qt5::Test
)

add_test(NAME desktop_serial_light COMMAND desktop_test_serial_light)

# ---------------------------------------------------------------------------
# CallSession：室内机通话（UDP 12345 双向音频 + UDP 23456 单向视频）
#
# `src/core/media/call_session.cpp` 此前**从未被任何测试目标链接**，却是两条
# 协议硬约束的室内机一侧：
#   - UDP 12345 双向音频，裸 PCM（S16_LE/16000Hz/单声道），无包头，
#     每包 320 帧 / 640 字节；
#   - UDP 23456 单向视频，门口机→室内机，每包一帧**完整 JPEG**，不重组不重传。
# 门口机那侧有测试、室内机这侧没有 —— 于是门口机改了字节，这边仍然绿，
# 而互操作已经断了。
#
# **socket 一律用真的**：端口是协议常量，不能像 monitor_client 那样挪到别的
# 端口测。探针实测（%TEMP%\probe34\result17.txt）确认本机可以
# bind(AnyIPv4,12345,ShareAddress)，且收到的 sender=127.0.0.2:52803 与发送端
# 一致，因此在**真实协议端口**上收发，才真正证明"端口对了、报文语义对了"。
# 绑定失败也可靠造出（result18.txt：先独占绑占住端口，3/3 次稳定复现）。
#
# **只有声卡是替身**：本机虽有可用音频设备（result16.txt），但把单元测试绑在
# 开发机的真实声卡上会让结果取决于机器（有无声卡、是否被独占）——
# 那正是"在我这儿能跑"的坑。替身让音频路径完全确定。
#
# 影子头机制同 desktop_test_serial_light：把替身命名为 QAudioFormat /
# QAudioInput / QAudioOutput 放在 tests/fake_audio/，用 BEFORE 插到 Qt 的
# include 之前。因为三个音频类全被替换，本目标**不需要** Qt5::Multimedia。
# 安全阀：影子头要求显式定义 ACC_CALL_SESSION_TEST，否则 #error。
# ---------------------------------------------------------------------------
add_executable(desktop_test_call_session
    test_call_session.cpp
    fake_audio.cpp
    ${ACCESSTERMINAL_SRC_ROOT}/core/media/call_session.cpp
)

target_include_directories(desktop_test_call_session BEFORE PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/fake_audio
)

target_include_directories(desktop_test_call_session PRIVATE
    ${ACCESSTERMINAL_SRC_ROOT}
    ${CMAKE_CURRENT_LIST_DIR}
)

target_compile_definitions(desktop_test_call_session PRIVATE
    ACC_CALL_SESSION_TEST
)

target_link_libraries(desktop_test_call_session PRIVATE
    Qt5::Core
    Qt5::Test
    Qt5::Network
    Qt5::Gui
)

add_test(NAME desktop_call_session COMMAND desktop_test_call_session)
