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
