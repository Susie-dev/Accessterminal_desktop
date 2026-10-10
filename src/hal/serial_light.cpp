/**
 * @file serial_light.cpp
 * @brief SerialLight 实现。
 */
#include "hal/serial_light.h"

#include "config/app_config.h"

#include <QDebug>

namespace accessterminal {

SerialLight::SerialLight(QObject* parent)
    : QObject(parent)
{
}

SerialLight::~SerialLight()
{
    close();
}

bool SerialLight::open(const QString& portName, int baudRate)
{
    if (!m_port) {
        m_port = new QSerialPort(this);
    }
    if (m_port->isOpen()) {
        m_port->close();
    }

    // 参数与重构前完全一致：8 数据位、无校验、1 停止位、无流控。
    m_port->setPortName(portName);
    m_port->setBaudRate(baudRate);
    m_port->setDataBits(QSerialPort::Data8);
    m_port->setParity(QSerialPort::NoParity);
    m_port->setStopBits(QSerialPort::OneStop);
    m_port->setFlowControl(QSerialPort::NoFlowControl);

    if (!m_port->open(QIODevice::ReadWrite)) {
        const QString msg = QStringLiteral("串口打开失败: %1 (%2)")
                                .arg(portName, m_port->errorString());
        qWarning() << "[灯控]" << msg;
        emit errorOccurred(msg);
        return false;
    }

    qInfo() << "[灯控] 串口打开成功:" << portName << "波特率:" << baudRate;
    return true;
}

void SerialLight::close()
{
    if (m_port && m_port->isOpen()) {
        m_port->close();
    }
}

bool SerialLight::isOpen() const
{
    return m_port && m_port->isOpen();
}

bool SerialLight::sendCommand(const QString& name)
{
    const QByteArray command = AppConfig::instance().lightCommand(name);
    if (command.isEmpty()) {
        qWarning() << "[灯控] 未知的指令名称:" << name;
        return false;
    }
    if (!isOpen()) {
        // 与重构前一致：不打弹窗，仅记录日志，避免现场无串口时阻塞操作。
        qWarning() << "[灯控] 串口未打开，无法发送指令:" << name;
        return false;
    }
    const qint64 written = m_port->write(command);
    m_port->flush();
    if (written != command.size()) {
        const QString msg = QStringLiteral("灯控指令写入不完整: %1").arg(name);
        qWarning() << "[灯控]" << msg;
        emit errorOccurred(msg);
        return false;
    }
    qDebug() << "[灯控] 已发送指令:" << name << command.toHex(' ');
    return true;
}

} // namespace accessterminal
