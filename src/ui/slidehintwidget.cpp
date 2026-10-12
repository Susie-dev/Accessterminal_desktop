#include "ui/slidehintwidget.h"
#include <QPainter>
#include <QLinearGradient>

SlideHintWidget::SlideHintWidget(QWidget *parent)
    : QWidget(parent), pos(0)
{
    timer = new QTimer(this);
    connect(timer, &QTimer::timeout, this, [this]() {
        pos += 5; // 速度加快
        int lightWidth = 100;
        if (pos > width()-100) pos = -lightWidth+80; // 流光从左侧外部开始
        update();
    });
    timer->start(10);
    setAttribute(Qt::WA_TransparentForMouseEvents, true); // 不拦截鼠标事件
}

void SlideHintWidget::paintEvent(QPaintEvent *)
{
    QPainter p(this);
    // --- 胶囊背景 ---
    int bgRadius = height() / 2 + 10; // 胶囊背景大圆角
    p.setRenderHint(QPainter::Antialiasing, true);
    QLinearGradient bg(100, 0, width(), 0); // 黑到白渐变
    bg.setColorAt(0, QColor(0,0,0,180));
    bg.setColorAt(1, QColor(255,255,255,180));
    p.setPen(Qt::NoPen);
    p.setBrush(bg);
    p.drawRoundedRect(rect(), bgRadius, bgRadius);

    // --- 流光 ---
    int lightWidth = 100;
    int lightRadius = qMin(lightWidth, height()) / 2; // 流光圆角不能大于自身宽/高一半
    QLinearGradient light(pos, 0, pos+lightWidth, 0);
    light.setColorAt(0, QColor(0,0,0,0));
    light.setColorAt(0.5, QColor(255,255,255,220));
    light.setColorAt(1, QColor(0,0,0,0));
    p.setBrush(light);
    QRect lightRect(pos, 0, lightWidth, height());
    p.drawRoundedRect(lightRect, lightRadius, lightRadius);
} 
