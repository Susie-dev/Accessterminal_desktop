#pragma once

#include <QByteArray>
#include <QString>

inline QString smartserverSelfIp()
{
    const QByteArray value = qgetenv("SMARTSERVER_SELF_IP");
    return value.isEmpty() ? QStringLiteral("192.168.1.4") : QString::fromLocal8Bit(value);
}

inline QString smartserverDeviceIp()
{
    const QByteArray value = qgetenv("SMARTSERVER_DEVICE_IP");
    return value.isEmpty() ? QStringLiteral("192.168.1.8") : QString::fromLocal8Bit(value);
}
