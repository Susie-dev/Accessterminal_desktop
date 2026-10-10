/**
 * @file serial_light.h
 * @brief 串口灯控封装。
 *
 * 把 QSerialPort 的打开、参数配置与指令下发收敛到一处，
 * UI 层不再直接持有串口对象，也不再关心十六进制指令细节。
 */
#ifndef ACCESSTERMINAL_HAL_SERIAL_LIGHT_H
#define ACCESSTERMINAL_HAL_SERIAL_LIGHT_H

#include <QObject>
#include <QSerialPort>
#include <QString>

namespace accessterminal {

/**
 * @brief 通过串口向灯控模块发送固定指令。
 *
 * 串口打开失败不影响程序运行：后续发送会被安全忽略并记录警告，
 * 与重构前"串口未打开则打印日志"的行为一致。
 */
class SerialLight : public QObject
{
    Q_OBJECT

public:
    explicit SerialLight(QObject* parent = nullptr);
    ~SerialLight() override;

    /**
     * @brief 打开串口。
     * @param portName 设备名，如 /dev/ttyUSB0（原实现为 Windows 的 COM24）。
     * @param baudRate 波特率，默认 9600。
     * @return 成功返回 true。
     */
    bool open(const QString& portName, int baudRate = QSerialPort::Baud9600);

    /// 关闭串口。
    void close();

    /// 串口当前是否可用。
    bool isOpen() const;

    /**
     * @brief 按名称发送灯控指令。
     *
     * 名称对应配置文件 lights 段的键：
     * desk / work / work_round / desk_round / wall
     *
     * @return 成功写入返回 true；串口未打开或指令不存在返回 false。
     */
    bool sendCommand(const QString& name);

signals:
    /// 发生错误时发出，便于 UI 层提示。
    void errorOccurred(const QString& message);

private:
    QSerialPort* m_port = nullptr;
};

} // namespace accessterminal

#endif // ACCESSTERMINAL_HAL_SERIAL_LIGHT_H
