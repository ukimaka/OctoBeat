#include "SpinnerWidget.h"

#include <QFontMetrics>
#include <QPainter>

SpinnerWidget::SpinnerWidget(QWidget *parent) : QWidget(parent) {
    setAttribute(Qt::WA_TransparentForMouseEvents, true);
    setAttribute(Qt::WA_TranslucentBackground, true);
    setAutoFillBackground(false);
    setFixedSize(22, 22);
    m_timer.setInterval(50);
    connect(&m_timer, &QTimer::timeout, this, [this] {
        m_angle = (m_angle + 24) % 360;
        update();
    });
}

void SpinnerWidget::setColor(const QColor &color) {
    m_color = color;
    update();
}

void SpinnerWidget::start() {
    m_running = true;
    m_timer.start();
    show();
    update();
}

void SpinnerWidget::stop() {
    m_running = false;
    m_timer.stop();
    hide();
}

void SpinnerWidget::setProgress(int progress) {
    m_progress = qBound(-1, progress, 100);
    if (m_progress >= 0) {
        m_progress = qMin(100, m_progress);
    }
    start();
}

QSize SpinnerWidget::sizeHint() const {
    return QSize(22, 22);
}

void SpinnerWidget::paintEvent(QPaintEvent *) {
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing, true);

    const qreal side = qMin(width(), height()) - 4.0;
    const QRectF circle((width() - side) / 2.0, (height() - side) / 2.0,
                        side, side);
    QPen track(m_color);
    track.setWidthF(2.2);
    track.setCapStyle(Qt::RoundCap);
    QColor trackColor = m_color;
    trackColor.setAlpha(45);
    track.setColor(trackColor);
    painter.setPen(track);
    painter.drawEllipse(circle);

    QPen arc(m_color);
    arc.setWidthF(2.4);
    arc.setCapStyle(Qt::RoundCap);
    painter.setPen(arc);
    if (m_progress > 0) {
        const int span = qBound(0, m_progress * 36, 3600);
        painter.drawArc(circle, 90 * 16, -span);
        if (side >= 26) {
            painter.setPen(m_color);
            QFont font = painter.font();
            font.setPixelSize(qMax(8, static_cast<int>(side * 0.28)));
            font.setBold(true);
            painter.setFont(font);
            painter.drawText(rect(), Qt::AlignCenter,
                             QStringLiteral("%1").arg(m_progress));
        }
    } else {
        painter.drawArc(circle, (90 - m_angle) * 16, -100 * 16);
    }
}
