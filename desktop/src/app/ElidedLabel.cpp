#include "ElidedLabel.h"

#include <QFontMetrics>
#include <QPainter>
#include <QPaintEvent>

ElidedLabel::ElidedLabel(const QString &text, QWidget *parent)
    : QLabel(text, parent), m_fullText(text) {
    setToolTip(text);
}

void ElidedLabel::setText(const QString &text) {
    m_fullText = text;
    setToolTip(text);
    QLabel::setText(text);
    update();
}

QSize ElidedLabel::minimumSizeHint() const {
    const QSize hint = QLabel::minimumSizeHint();
    return QSize(0, hint.height());
}

void ElidedLabel::paintEvent(QPaintEvent *event) {
    Q_UNUSED(event);
    QPainter painter(this);
    const QFontMetrics metrics(font());
    const QString elided =
        metrics.elidedText(m_fullText, Qt::ElideRight, width());
    painter.setPen(palette().color(QPalette::WindowText));
    painter.drawText(rect(), alignment(), elided);
}
