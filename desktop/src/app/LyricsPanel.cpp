#include "LyricsPanel.h"

#include "IconUtils.h"
#include "Theme.h"

#include <QFont>
#include <QFrame>
#include <QHBoxLayout>
#include <QPalette>
#include <QPushButton>
#include <QSizePolicy>
#include <QStringList>
#include <QTextBrowser>
#include <QVBoxLayout>

namespace {
const QColor Accent(0x51, 0x51, 0xab);
const QColor Muted(0x8a, 0x8a, 0x8a);
} // namespace

LyricsPanel::LyricsPanel(QWidget *parent) : QWidget(parent) {
    setObjectName(QStringLiteral("lyricsPanel"));
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);

    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);

    m_view = new QTextBrowser(this);
    m_view->setObjectName(QStringLiteral("lyricsView"));
    m_view->setOpenExternalLinks(false);
    m_view->setFrameShape(QFrame::NoFrame);
    m_view->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_view->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_view->setMinimumHeight(96);
    m_view->setMaximumHeight(180);
    m_view->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);

    auto *offsetDown = new QPushButton(QStringLiteral("-0.5s"), this);
    offsetDown->setFlat(true);
    offsetDown->setFixedWidth(46);
    offsetDown->setCursor(Qt::PointingHandCursor);
    offsetDown->setToolTip(tr("Sync lyrics: -0.5s"));
    auto *offsetUp = new QPushButton(QStringLiteral("+0.5s"), this);
    offsetUp->setFlat(true);
    offsetUp->setFixedWidth(46);
    offsetUp->setCursor(Qt::PointingHandCursor);
    offsetUp->setToolTip(tr("Sync lyrics: +0.5s"));

    m_karaoke = new QPushButton(this);
    m_karaoke->setFlat(true);
    m_karaoke->setIconSize(QSize(18, 18));
    m_karaoke->setCursor(Qt::PointingHandCursor);
    m_karaoke->setToolTip(tr("Karaoke"));

    m_fullscreen = new QPushButton(this);
    m_fullscreen->setFlat(true);
    m_fullscreen->setIconSize(QSize(16, 16));
    m_fullscreen->setCursor(Qt::PointingHandCursor);
    m_fullscreen->setToolTip(tr("Fullscreen"));

    auto *header = new QHBoxLayout();
    header->setContentsMargins(0, 0, 8, 0);
    header->setSpacing(4);
    header->addStretch(1);
    header->addWidget(offsetDown);
    header->addWidget(offsetUp);
    header->addWidget(m_karaoke);
    header->addWidget(m_fullscreen);
    layout->addLayout(header);
    layout->addWidget(m_view);

    connect(offsetDown, &QPushButton::clicked, this,
            [this] { emit offsetRequested(-500); });
    connect(offsetUp, &QPushButton::clicked, this,
            [this] { emit offsetRequested(500); });
    connect(m_karaoke, &QPushButton::clicked, this,
            &LyricsPanel::karaokeRequested);
    connect(m_fullscreen, &QPushButton::clicked, this,
            &LyricsPanel::fullscreenRequested);

    applyTheme();
    render();
    hide();
}

void LyricsPanel::setContent(const QString &mode,
                             const QVector<LyricsLine> &lines,
                             const QString &plain) {
    m_mode = mode;
    m_lines = lines;
    m_plain = plain;
    m_lineIndex = -1;
    m_wordIndex = -1;
    render();
    scrollToCurrent();
}

void LyricsPanel::setHighlight(int lineIndex, int wordIndex) {
    if (m_lineIndex == lineIndex && m_wordIndex == wordIndex) {
        return;
    }
    m_lineIndex = lineIndex;
    m_wordIndex = wordIndex;
    if (isVisible()) {
        render();
        scrollToCurrent();
    }
}

void LyricsPanel::scrollToCurrent() {
    if (m_lineIndex >= 0 && m_lineIndex < m_lines.size()) {
        m_view->scrollToAnchor(QStringLiteral("lrc%1").arg(m_lineIndex));
    }
}

void LyricsPanel::applyTheme() {
    m_fullscreen->setIcon(IconUtils::tinted(QStringLiteral("expand.svg"),
                                            Theme::iconColor(), 16));
    m_karaoke->setIcon(IconUtils::tinted(QStringLiteral("karaoke.svg"),
                                         Theme::iconColor(), 18));
    render();
}

QString LyricsPanel::lineHtml(int index, const LyricsLine &line) const {
    const bool current = index == m_lineIndex;
    const QString anchor = QStringLiteral("<a name=\"lrc%1\"></a>").arg(index);
    const QColor textColor = palette().color(QPalette::Text);

    if (current && !line.words.isEmpty()) {
        QStringList spans;
        for (int i = 0; i < line.words.size(); ++i) {
            const bool active = i == m_wordIndex;
            const QString color =
                active ? Accent.name() : textColor.name();
            spans.push_back(QStringLiteral(
                                "<span style=\"color:%1; font-weight:%2;\">%3</span>")
                                .arg(color,
                                     active ? QStringLiteral("bold")
                                            : QStringLiteral("normal"),
                                     line.words[i].text.toHtmlEscaped()));
        }
        return QStringLiteral("<div style=\"font-weight:bold;\">%1%2</div>")
            .arg(anchor, spans.join(QLatin1Char(' ')));
    }

    const QString color = current ? Accent.name() : Muted.name();
    const QString weight = current ? QStringLiteral("bold")
                                   : QStringLiteral("normal");
    const QString body = line.text.isEmpty()
                             ? QStringLiteral("&nbsp;")
                             : line.text.toHtmlEscaped();
    return QStringLiteral(
               "<div style=\"color:%1; font-weight:%2;\">%3%4</div>")
        .arg(color, weight, anchor, body);
}

void LyricsPanel::render() {
    const QColor textColor = palette().color(QPalette::Text);
    if (m_mode == QStringLiteral("loading")) {
        m_view->setHtml(QStringLiteral(
                            "<div style=\"color:%1; line-height:1.6;\">%2</div>")
                            .arg(Muted.name(), tr("Loading lyrics...")));
        return;
    }
    if (m_mode == QStringLiteral("synced") && !m_lines.isEmpty()) {
        QStringList parts;
        for (int i = 0; i < m_lines.size(); ++i) {
            parts.push_back(lineHtml(i, m_lines[i]));
        }
        m_view->setHtml(QStringLiteral(
                            "<div style=\"line-height:1.6;\">%1</div>")
                            .arg(parts.join(QString())));
        return;
    }
    if (m_mode == QStringLiteral("plain") && !m_plain.isEmpty()) {
        m_view->setHtml(QStringLiteral(
                            "<div style=\"color:%1; line-height:1.6;\">%2</div>")
                            .arg(textColor.name(),
                                 m_plain.toHtmlEscaped().replace(
                                     QLatin1Char('\n'),
                                     QStringLiteral("<br>"))));
        return;
    }
    m_view->setHtml(QStringLiteral(
                        "<div style=\"color:%1; line-height:1.6;\">%2</div>")
                        .arg(Muted.name(), tr("No lyrics found")));
}
