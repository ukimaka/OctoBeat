#pragma once

#include <QSlider>

class ClickSlider : public QSlider {
    Q_OBJECT

public:
    explicit ClickSlider(Qt::Orientation orientation, QWidget *parent = nullptr);

signals:
    void clickedValue(int value);

protected:
    void mousePressEvent(QMouseEvent *event) override;
    void mouseMoveEvent(QMouseEvent *event) override;
    void mouseReleaseEvent(QMouseEvent *event) override;

private:
    int valueAt(int x) const;
    bool m_dragging = false;
};
