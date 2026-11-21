#pragma once

#include <QTreeWidget>

class QPropertyAnimation;

class SmoothTreeWidget : public QTreeWidget {
    Q_OBJECT

public:
    explicit SmoothTreeWidget(QWidget *parent = nullptr);

signals:
    void itemsMoved();

protected:
    void wheelEvent(QWheelEvent *event) override;
    void dropEvent(QDropEvent *event) override;

private:
    QPropertyAnimation *m_scrollAnimation = nullptr;
};
