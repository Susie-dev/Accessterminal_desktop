/**
 * @file fake_serial_port.h
 * @brief 影子 QSerialPort 的访问入口声明。
 *
 * 测试文件**不能**直接 `#include <QSerialPort>` 来拿 FakeSerialPortRecord ——
 * 在别的目标里那样只会拿到真的 Qt 头，从而出现"类型不匹配"的诡异错误。
 * 本头文件不依赖 Qt 的 QSerialPort 头，只声明记录结构与两个自由函数，
 * 因此测试可以安全包含它。
 */
#ifndef ACCESSTERMINAL_TESTS_FAKE_SERIAL_PORT_H
#define ACCESSTERMINAL_TESTS_FAKE_SERIAL_PORT_H

#include <QByteArray>
#include <QList>
#include <QString>

/// 替身串口记录下来的全部可观测量，由测试读取/复位。
struct FakeSerialPortRecord
{
    // ---- 参数配置：`open()` 是否按 8N1/无流控 设置 ----
    QString portName;
    int baudRate = -1;
    int dataBits = -1;
    int parity = -1;
    int stopBits = -1;
    int flowControl = -1;
    int setPortNameCalls = 0;
    int setBaudRateCalls = 0;
    int dataBitsCalls = 0;
    int parityCalls = 0;
    int stopBitsCalls = 0;
    int flowControlCalls = 0;

    // ---- 生命周期 ----
    int openCalls = 0;
    int closeCalls = 0;
    bool openModeReadWrite = false;
    int lastOpenMode = 0;

    // ---- 数据 ----
    QList<QByteArray> writes;
    int flushCalls = 0;

    // ---- 可控行为（测试用来注入失败）----
    bool failOpen = false;
    QString errorString = QStringLiteral("(未设置)");
    /// `write()` 的返回值覆盖值；-1 表示"返回真实长度"。
    qint64 writeReturnOverride = -1;
};

/// 取得全局替身记录。
FakeSerialPortRecord& fakeSerialPort();

/// 复位替身记录。
void resetFakeSerialPort();

#endif // ACCESSTERMINAL_TESTS_FAKE_SERIAL_PORT_H
