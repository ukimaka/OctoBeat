#pragma once

#include <QColor>
#include <QTimer>
#include <QWidget>

class SpinnerWidget : public QWidget {
    Q_OBJECT

public:
    explicit SpinnerWidget(QWidget *parent = nullptr);

    void setColor(const QColor &color);
    void start();
    void stop();
    void setProgress(int progress);
    bool isRunning() const { return m_running; }
    QSize sizeHint() const override;

protected:
    void paintEvent(QPaintEvent *event) override;

private:
    QTimer m_timer;
    QColor m_color = QColor(0x51, 0x51, 0xab);
    int m_angle = 0;
    int m_progress = -1;
    bool m_running = false;
};
