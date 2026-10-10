/**
 * @file fake_serial_port.cpp
 * @brief 影子 QSerialPort 的全局记录定义。
 *
 * 这里包含的是**影子** `<QSerialPort>`（靠 include 路径顺序命中），
 * 与 `serial_light.cpp` 编译时看到的必须是同一个头，否则两边对类型布局的
 * 理解会不一致（那是最难查的一类链接期/运行期错乱）。
 */
#include <QSerialPort>

#include "fake_serial_port.h"

namespace {

FakeSerialPortRecord g_record;

} // namespace

FakeSerialPortRecord& fakeSerialPort()
{
    return g_record;
}

void resetFakeSerialPort()
{
    g_record = FakeSerialPortRecord();
}
