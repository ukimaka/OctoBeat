#pragma once

#include <QWidget>

class QLabel;

class TitleBar : public QWidget {
    Q_OBJECT

public:
    explicit TitleBar(QWidget *parent = nullptr);

signals:
    void miniPlayerRequested();

protected:
    void mousePressEvent(QMouseEvent *event) override;
    void mouseDoubleClickEvent(QMouseEvent *event) override;

private:
    QLabel *m_title = nullptr;
};
