#pragma once

#include <QPushButton>

class LyricsButton : public QPushButton {
    Q_OBJECT

public:
    explicit LyricsButton(QWidget *parent = nullptr);

signals:
    void doubleClicked();

protected:
    void mouseDoubleClickEvent(QMouseEvent *event) override;
};
