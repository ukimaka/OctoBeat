#pragma once

#include <QLabel>

class ElidedLabel : public QLabel {
    Q_OBJECT

public:
    explicit ElidedLabel(const QString &text = {}, QWidget *parent = nullptr);

    void setText(const QString &text);

    QSize minimumSizeHint() const override;

protected:
    void paintEvent(QPaintEvent *event) override;

private:
    QString m_fullText;
};
