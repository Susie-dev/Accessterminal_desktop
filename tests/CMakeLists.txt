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

find_package(Qt5 5.12 REQUIRED COMPONENTS Core Test)

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
add_executable(test_protocol test_protocol.cpp)

target_include_directories(test_protocol PRIVATE
    ${ACCESSTERMINAL_SRC_ROOT}
)

target_link_libraries(test_protocol PRIVATE
    Qt5::Core
    Qt5::Test
)

add_test(NAME protocol COMMAND test_protocol)
