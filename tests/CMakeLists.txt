#
# 单元测试。仅在本机构建时启用（交叉编译默认关闭）：
#   cmake -S . -B build -DACCESSTERMINAL_BUILD_TESTS=ON
#   cmake --build build
#   ctest --test-dir build --output-on-failure
#
find_package(Qt5 5.12 REQUIRED COMPONENTS Core Test)

# ---------------------------------------------------------------------------
# 协议契约测试
# ---------------------------------------------------------------------------
add_executable(test_protocol test_protocol.cpp)

target_include_directories(test_protocol PRIVATE
    ${CMAKE_SOURCE_DIR}/src
)

target_link_libraries(test_protocol PRIVATE
    Qt5::Core
    Qt5::Test
)

add_test(NAME protocol COMMAND test_protocol)
