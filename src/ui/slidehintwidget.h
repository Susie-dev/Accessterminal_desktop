#ifndef SLIDEHINTWIDGET_H
#define SLIDEHINTWIDGET_H

#include <QWidget>
#include <QTimer>

class SlideHintWidget : public QWidget {
    Q_OBJECT
public:
    explicit SlideHintWidget(QWidget *parent = nullptr);
protected:
    void paintEvent(QPaintEvent *event) override;
private:
    QTimer *timer;
    int pos = 100;
};

#endif // SLIDEHINTWIDGET_H 
