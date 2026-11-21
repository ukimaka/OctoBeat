#include "SmoothTreeWidget.h"

#include "TrackDelegate.h"

#include <QEasingCurve>
#include <QPropertyAnimation>
#include <QDropEvent>
#include <QScrollBar>
#include <QWheelEvent>

#include <algorithm>

SmoothTreeWidget::SmoothTreeWidget(QWidget *parent) : QTreeWidget(parent) {
    setVerticalScrollMode(QAbstractItemView::ScrollPerPixel);
    m_scrollAnimation = new QPropertyAnimation(verticalScrollBar(), "value", this);
    m_scrollAnimation->setDuration(220);
    m_scrollAnimation->setEasingCurve(QEasingCurve::OutCubic);
}

void SmoothTreeWidget::dropEvent(QDropEvent *event) {
    QTreeWidgetItem *source = currentItem();
    if (!source || source->data(0, IsFolderRole).toBool()) {
        event->ignore();
        return;
    }

    QTreeWidgetItem *target = itemAt(event->position().toPoint());
    QTreeWidgetItem *targetFolder = nullptr;
    if (target) {
        targetFolder = target->data(0, IsFolderRole).toBool()
                           ? target
                           : target->parent();
    }
    if (target == source ||
        (source->parent() == targetFolder &&
         source->parent() == nullptr && target == nullptr)) {
        event->ignore();
        return;
    }

    QTreeWidgetItem *copy = source->clone();
    if (source->parent()) {
        source->parent()->removeChild(source);
    } else {
        const int row = indexOfTopLevelItem(source);
        if (row >= 0) {
            takeTopLevelItem(row);
        }
    }
    delete source;

    if (targetFolder) {
        targetFolder->addChild(copy);
        targetFolder->setExpanded(true);
    } else {
        addTopLevelItem(copy);
    }
    setCurrentItem(copy);
    event->acceptProposedAction();
    emit itemsMoved();
}

void SmoothTreeWidget::wheelEvent(QWheelEvent *event) {
    QScrollBar *bar = verticalScrollBar();
    int delta = event->angleDelta().y();
    if (delta == 0) {
        delta = event->pixelDelta().y();
    }
    if (delta == 0 || !bar) {
        QTreeWidget::wheelEvent(event);
        return;
    }

    const int target =
        std::clamp(bar->value() - delta, bar->minimum(), bar->maximum());
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
