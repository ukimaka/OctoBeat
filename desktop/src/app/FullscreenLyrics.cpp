#include "FullscreenLyrics.h"

#include "IconUtils.h"
#include "Theme.h"

#include <QFrame>
#include <QHBoxLayout>
#include <QKeyEvent>
#include <QLabel>
#include <QPainter>
#include <QPalette>
#include <QPushButton>
#include <QStringList>
#include <QTextBrowser>
#include <QVBoxLayout>

namespace {
const QColor Accent(0x51, 0x51, 0xab);
const QColor Muted(0x8a, 0x8a, 0x8a);
} // namespace

FullscreenLyrics::FullscreenLyrics(Mode mode, QWidget *parent)
    : QWidget(parent), m_mode(mode) {
    setWindowFlags(Qt::Window | Qt::FramelessWindowHint);
    setAttribute(Qt::WA_TranslucentBackground, true);
    setWindowTitle(mode == Mode::Karaoke ? QStringLiteral("Karaoke")
                                         : QStringLiteral("Lyrics"));

    m_view = new QTextBrowser(this);
    m_view->setObjectName(QStringLiteral("karaokeView"));
    m_view->setOpenExternalLinks(false);
    m_view->setFrameShape(QFrame::NoFrame);
    m_view->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_view->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    QFont viewFont = m_view->font();
    viewFont.setPixelSize(36);
    viewFont.setBold(mode == Mode::Karaoke);
    m_view->setFont(viewFont);

    auto *offsetDown = new QPushButton(QStringLiteral("-0.5s"), this);
    offsetDown->setFlat(true);
    offsetDown->setCursor(Qt::PointingHandCursor);
    offsetDown->setToolTip(tr("Sync lyrics: -0.5s"));
    auto *offsetUp = new QPushButton(QStringLiteral("+0.5s"), this);
    offsetUp->setFlat(true);
    offsetUp->setCursor(Qt::PointingHandCursor);
    offsetUp->setToolTip(tr("Sync lyrics: +0.5s"));
    m_offsetLabel = new QLabel(this);
    m_offsetLabel->setStyleSheet(
        QStringLiteral("color: rgba(255, 255, 255, 0.55);"));

    m_close = new QPushButton(this);
    m_close->setFixedSize(44, 44);
    m_close->setFlat(true);
    m_close->setCursor(Qt::PointingHandCursor);
    m_close->setToolTip(tr("Close"));
    m_close->setIcon(IconUtils::tinted(QStringLiteral("cancel.svg"),
                                       QColor(235, 235, 240), 20));
    m_close->setIconSize(QSize(20, 20));
    m_close->setStyleSheet(QStringLiteral(
        "QPushButton { background: rgba(255, 255, 255, 0.12);"
        " border: none; border-radius: 22px; }"
        "QPushButton:hover { background: rgba(255, 255, 255, 0.25); }"));

    auto *header = new QHBoxLayout();
    header->setContentsMargins(24, 16, 20, 0);
    header->setSpacing(6);
    header->addWidget(offsetDown);
    header->addWidget(offsetUp);
    header->addWidget(m_offsetLabel);
    header->addStretch(1);
    header->addWidget(m_close);

    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    layout->addLayout(header);
    layout->addWidget(m_view, 1);

    connect(m_close, &QPushButton::clicked, this, &QWidget::close);
    connect(offsetDown, &QPushButton::clicked, this,
            [this] { emit offsetRequested(-500); });
    connect(offsetUp, &QPushButton::clicked, this,
            [this] { emit offsetRequested(500); });

    setStyleSheet(
        QStringLiteral(
            "QTextBrowser#karaokeView { background: transparent; border: none;"
            " padding: 30px 80px; font-size: 36px; font-weight: %1; color: #ffffff; }"
            "QPushButton { color: rgba(255, 255, 255, 0.8); background: transparent;"
            " border: none; padding: 4px 8px; border-radius: 6px; }"
            "QPushButton:hover { background: rgba(255, 255, 255, 0.12); }")
            .arg(mode == Mode::Karaoke ? QStringLiteral("bold")
                                       : QStringLiteral("normal")));

    setOffset(0);
    render();
}

void FullscreenLyrics::setContent(const QVector<LyricsLine> &lines,
                                  const QString &plain) {
    m_lines = lines;
    m_plain = plain;
    m_lineIndex = -1;
    m_wordIndex = -1;
    render();
    if (m_lineIndex >= 0) {
        m_view->scrollToAnchor(QStringLiteral("krk%1").arg(m_lineIndex));
    }
}

void FullscreenLyrics::setHighlight(int lineIndex, int wordIndex) {
    if (m_lineIndex == lineIndex && m_wordIndex == wordIndex) {
        return;
    }
    m_lineIndex = lineIndex;
    m_wordIndex = wordIndex;
    if (isVisible()) {
        render();
        if (m_lineIndex >= 0) {
            m_view->scrollToAnchor(
                QStringLiteral("krk%1").arg(m_lineIndex));
        }
    }
}

void FullscreenLyrics::setOffset(int offsetMs) {
    m_offsetMs = offsetMs;
    if (m_offsetLabel) {
        m_offsetLabel->setText(
            QStringLiteral("%1%2.%3s")
                .arg(offsetMs < 0 ? QStringLiteral("-") : QStringLiteral("+"))
                .arg(qAbs(offsetMs) / 1000)
                .arg((qAbs(offsetMs) % 1000) / 100));
    }
}

QString FullscreenLyrics::lineHtml(int index, const LyricsLine &line) const {
    const bool current = index == m_lineIndex;
    const QString anchor = QStringLiteral("<a name=\"krk%1\"></a>").arg(index);
    if (current && !line.words.isEmpty()) {
        QStringList spans;
        for (int i = 0; i < line.words.size(); ++i) {
            const bool active = i == m_wordIndex;
            spans.push_back(
                QStringLiteral("<span style=\"color:%1;\">%2</span>")
                    .arg(active ? Accent.name() : QStringLiteral("#ffffff"),
                         line.words[i].text.toHtmlEscaped()));
        }
        return QStringLiteral("<div style=\"font-weight:bold;\">%1%2</div>")
            .arg(anchor, spans.join(QLatin1Char(' ')));
    }
    const QString color = current ? Accent.name() : Muted.name();
    const QString weight =
        (current || m_mode == Mode::Karaoke) ? QStringLiteral("bold")
                                             : QStringLiteral("normal");
    const QString body = line.text.isEmpty()
                             ? QStringLiteral("&nbsp;")
                             : line.text.toHtmlEscaped();
    return QStringLiteral(
               "<div style=\"color:%1; font-weight:%2;\">%3%4</div>")
        .arg(color, weight, anchor, body);
}

void FullscreenLyrics::render() {
    if (!m_lines.isEmpty()) {
        QStringList parts;
        for (int i = 0; i < m_lines.size(); ++i) {
            parts.push_back(lineHtml(i, m_lines[i]));
        }
        m_view->setHtml(
            QStringLiteral(
                "<div style=\"text-align:center; line-height:1.5;\">%1</div>")
                .arg(parts.join(QString())));
        return;
    }
    if (!m_plain.isEmpty()) {
        m_view->setHtml(
            QStringLiteral(
                "<div style=\"color:#8a8a8a; text-align:center;\">%1</div>")
                .arg(m_plain.toHtmlEscaped().replace(QLatin1Char('\n'),
                                                     QStringLiteral("<br>"))));
        return;
    }
    m_view->setHtml(
        QStringLiteral("<div style=\"color:#8a8a8a; text-align:center;\">%1</div>")
            .arg(tr("No lyrics found")));
}

void FullscreenLyrics::keyPressEvent(QKeyEvent *event) {
    if (event->key() == Qt::Key_Escape) {
        close();
        return;
    }
    QWidget::keyPressEvent(event);
}

void FullscreenLyrics::paintEvent(QPaintEvent *) {
    QPainter painter(this);
    painter.fillRect(rect(), QColor(0, 0, 0, 230));
}
