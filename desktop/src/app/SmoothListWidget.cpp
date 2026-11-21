#include "SmoothListWidget.h"

#include <QPropertyAnimation>
#include <QScrollBar>
#include <QWheelEvent>

#include <algorithm>

SmoothListWidget::SmoothListWidget(QWidget *parent) : QListWidget(parent) {
    setVerticalScrollMode(QAbstractItemView::ScrollPerPixel);
    m_scrollAnimation = new QPropertyAnimation(verticalScrollBar(), "value", this);
    m_scrollAnimation->setDuration(220);
    m_scrollAnimation->setEasingCurve(QEasingCurve::OutCubic);
}

void SmoothListWidget::wheelEvent(QWheelEvent *event) {
    QScrollBar *bar = verticalScrollBar();
    int delta = event->angleDelta().y();
    if (delta == 0) {
        delta = event->pixelDelta().y();
    }
    if (delta == 0 || !bar) {
        QListWidget::wheelEvent(event);
        return;
    }

    const int target = std::clamp(bar->value() - delta, bar->minimum(), bar->maximum());
    if (m_scrollAnimation) {
        m_scrollAnimation->stop();
        m_scrollAnimation->setStartValue(bar->value());
        m_scrollAnimation->setEndValue(target);
        m_scrollAnimation->start();
    } else {
        bar->setValue(target);
    }
    event->accept();
}
