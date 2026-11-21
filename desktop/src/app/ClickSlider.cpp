#include "ClickSlider.h"

#include <QMouseEvent>
#include <QStyle>

ClickSlider::ClickSlider(Qt::Orientation orientation, QWidget *parent)
    : QSlider(orientation, parent) {
    setTracking(true);
}

int ClickSlider::valueAt(int x) const {
    return QStyle::sliderValueFromPosition(minimum(), maximum(), x, width(),
                                           false);
}

void ClickSlider::mousePressEvent(QMouseEvent *event) {
    if (event->button() == Qt::LeftButton && maximum() > minimum()) {
        m_dragging = true;
        setSliderDown(true);
        const int value = valueAt(static_cast<int>(event->position().x()));
        setValue(value);
        emit sliderPressed();
        emit clickedValue(value);
        event->accept();
        return;
    }
    QSlider::mousePressEvent(event);
}

void ClickSlider::mouseMoveEvent(QMouseEvent *event) {
    if (m_dragging && (event->buttons() & Qt::LeftButton)) {
        const int value = valueAt(static_cast<int>(event->position().x()));
        setValue(value);
        emit sliderMoved(value);
        event->accept();
        return;
    }
    QSlider::mouseMoveEvent(event);
}

void ClickSlider::mouseReleaseEvent(QMouseEvent *event) {
    if (m_dragging && event->button() == Qt::LeftButton) {
        m_dragging = false;
        setSliderDown(false);
        emit sliderReleased();
        event->accept();
        return;
    }
    QSlider::mouseReleaseEvent(event);
}
