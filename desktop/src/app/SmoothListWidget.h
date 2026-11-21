#pragma once

#include <QListWidget>

class QPropertyAnimation;

class SmoothListWidget : public QListWidget {
    Q_OBJECT

public:
    explicit SmoothListWidget(QWidget *parent = nullptr);

protected:
    void wheelEvent(QWheelEvent *event) override;

private:
    QPropertyAnimation *m_scrollAnimation = nullptr;
};
