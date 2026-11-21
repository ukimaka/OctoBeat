#include "TrackDelegate.h"

#include "CoverCache.h"
#include "IconUtils.h"
#include "Theme.h"

#include <cstdio>

#include <QAbstractItemView>
#include <QElapsedTimer>
#include <QFontMetrics>
#include <QPainter>
#include <QPainterPath>
#include <QPolygonF>
#include <QStyle>
#include <QStyleOptionViewItem>

namespace {
constexpr int RowHeight = 60;
constexpr int CoverSize = 50;
constexpr int CoverRadius = 6;
constexpr int CoverX = 32;
constexpr int TextX = 94;

QString durationText(qint64 seconds) {
    const qint64 total = qMax<qint64>(0, seconds);
    const qint64 hours = total / 3600;
    const qint64 minutes = (total % 3600) / 60;
    const qint64 secs = total % 60;
    if (hours > 0) {
        return QStringLiteral("%1:%2:%3")
            .arg(hours)
            .arg(minutes, 2, 10, QLatin1Char('0'))
            .arg(secs, 2, 10, QLatin1Char('0'));
    }
    return QStringLiteral("%1:%2")
        .arg(minutes)
        .arg(secs, 2, 10, QLatin1Char('0'));
}
} // namespace

TrackDelegate::TrackDelegate(QObject *parent)
    : QStyledItemDelegate(parent), m_accent(Theme::accent()) {}

QSize TrackDelegate::sizeHint(const QStyleOptionViewItem &option,
                              const QModelIndex &index) const {
    Q_UNUSED(index);
    return QSize(option.rect.width(), RowHeight);
}

void TrackDelegate::ensureFonts(const QFont &baseFont) const {
    if (baseFont.key() == m_fontKey) {
        return;
    }
    m_fontKey = baseFont.key();
    m_titleFont = baseFont;
    m_titleFont.setPixelSize(13);
    m_titleFont.setBold(true);
    m_artistFont = baseFont;
    m_artistFont.setPixelSize(11);
    m_numberFont = baseFont;
    m_numberFont.setPixelSize(11);
    m_folderFont = baseFont;
    m_folderFont.setPixelSize(14);
    m_folderFont.setBold(true);
    m_titleMetrics.emplace(m_titleFont);
    m_artistMetrics.emplace(m_artistFont);
    m_numberMetrics.emplace(m_numberFont);
    m_folderMetrics.emplace(m_folderFont);
}

const QPixmap &TrackDelegate::playMarker(const QColor &color) const {
    if (!m_playPixmap || m_playColor != color) {
        m_playPixmap = IconUtils::tinted(QStringLiteral("play-mini.svg"),
                                         color, 14)
                           .pixmap(14, 14);
        m_playColor = color;
    }
    return *m_playPixmap;
}

const QPixmap &TrackDelegate::trashIcon() const {
    if (!m_trashPixmap) {
        m_trashPixmap = IconUtils::tinted(
                            QStringLiteral("trash.svg"),
                            QColor(QStringLiteral("#e05a4a")), 16)
                            .pixmap(16, 16);
    }
    return *m_trashPixmap;
}

QRect TrackDelegate::trashRect(const QRect &rowRect,
                               qint64 durationSeconds) const {
    const QFontMetrics metrics = m_numberMetrics
                                     ? *m_numberMetrics
                                     : QFontMetrics(m_numberFont);
    const int durationWidth =
        metrics.horizontalAdvance(durationText(durationSeconds)) + 24;
    const int textRight = rowRect.right() - durationWidth - 6;
    return QRect(textRight - 16 - 12,
                 rowRect.y() + (rowRect.height() - 16) / 2, 16, 16);
}

const QPixmap &TrackDelegate::folderIcon(const QColor &color) const {
    if (!m_folderPixmap || m_folderColor != color) {
        m_folderPixmap = IconUtils::tinted(
                             QStringLiteral("show-folder-with-music.svg"),
                             color, 22)
                             .pixmap(22, 22);
        m_folderColor = color;
    }
    return *m_folderPixmap;
}

void TrackDelegate::setCurrentPlaying(qint64 trackId) {
    if (m_currentPlaying == trackId) {
        return;
    }
    m_currentPlaying = trackId;
    if (auto *view = qobject_cast<QAbstractItemView *>(parent())) {
        view->viewport()->update();
    }
}

void TrackDelegate::setHoveredTrashTrackId(qint64 trackId) {
    if (m_hoveredTrashTrackId == trackId) {
        return;
    }
    m_hoveredTrashTrackId = trackId;
    if (auto *view = qobject_cast<QAbstractItemView *>(parent())) {
        view->viewport()->update();
    }
}

void TrackDelegate::setAccentColor(const QColor &color) {
    m_accent = color;
    resetIcons();
}

void TrackDelegate::resetIcons() {
    m_playPixmap.reset();
    m_folderPixmap.reset();
    m_trashPixmap.reset();
    m_playColor = QColor();
    m_folderColor = QColor();
    if (auto *view = qobject_cast<QAbstractItemView *>(parent())) {
        view->viewport()->update();
    }
}

void TrackDelegate::paint(QPainter *painter,
                          const QStyleOptionViewItem &option,
                          const QModelIndex &index) const {
    if (!painter) {
        return;
    }
    static const bool paintDebug =
        qEnvironmentVariableIsSet("OCTOBEAT_PAINT_DEBUG");
    QElapsedTimer paintTimer;
    if (paintDebug) {
        paintTimer.start();
    }
    ensureFonts(option.font);

    const bool isFolder = index.data(IsFolderRole).toBool();
    const QRect rect = option.rect;
    const QPalette &palette = option.palette;
    const QColor textColor = palette.color(QPalette::Text);
    const QColor windowText = palette.color(QPalette::WindowText);
    QColor muted = windowText;
    muted.setAlpha(150);

    int fullWidth = rect.width();
    if (const auto *view = qobject_cast<const QAbstractItemView *>(option.widget)) {
        fullWidth = view->viewport()->width();
    }
    const QRect rowRect(0, rect.y(), fullWidth, rect.height());

    painter->save();
    painter->setRenderHint(QPainter::Antialiasing, true);
    painter->setRenderHint(QPainter::SmoothPixmapTransform, true);

    const qint64 trackId = index.data(TrackIdRole).toLongLong();
    const bool playing = !isFolder && trackId > 0 && trackId == m_currentPlaying;

    if (playing) {
        QColor fill = m_accent;
        fill.setAlpha(40);
        painter->fillRect(rowRect, fill);
    } else if (option.state & QStyle::State_Selected) {
        QColor fill = m_accent;
        fill.setAlpha(30);
        painter->fillRect(rowRect, fill);
    } else if (option.state & QStyle::State_MouseOver) {
        QColor fill = windowText;
        fill.setAlpha(15);
        painter->fillRect(rowRect, fill);
    }

    if (isFolder) {
        const QColor folderColor = Theme::iconColor();
        const bool expanded = option.state & QStyle::State_Open;
        const int chevronX = rect.x() + 9;
        const int chevronY = rect.y() + rect.height() / 2;
        painter->setPen(QPen(folderColor, 1.6, Qt::SolidLine,
                             Qt::RoundCap, Qt::RoundJoin));
        QPolygonF chevron;
        if (expanded) {
            chevron << QPointF(chevronX - 3, chevronY - 2)
                    << QPointF(chevronX, chevronY + 2)
                    << QPointF(chevronX + 3, chevronY - 2);
        } else {
            chevron << QPointF(chevronX - 2, chevronY - 3)
                    << QPointF(chevronX + 2, chevronY)
                    << QPointF(chevronX - 2, chevronY + 3);
        }
        painter->drawPolyline(chevron);
        painter->drawPixmap(rect.x() + 22,
                            rect.y() + (rect.height() - 22) / 2,
                            folderIcon(folderColor));
        painter->setFont(m_folderFont);
        painter->setPen(textColor);
        const int textLeft = rect.x() + 50;
        const int textWidth = qMax(0, rect.right() - textLeft - 12);
        const QString name = m_folderMetrics->elidedText(
            index.data(FolderNameRole).toString(), Qt::ElideRight, textWidth);
        painter->drawText(QRect(textLeft, rect.y(), textWidth, rect.height()),
                          Qt::AlignLeft | Qt::AlignVCenter, name);
        painter->restore();
        return;
    }

    // Leading marker: track number, or the play glyph on hover.
    const QRect markerRect(rect.x() + 2, rect.y(), 28, rect.height());
    if (option.state & QStyle::State_MouseOver) {
        const QPixmap &icon = playMarker(textColor);
        const QPoint center = markerRect.center();
        painter->drawPixmap(center.x() - 7, center.y() - 7, icon);
    } else {
        painter->setFont(m_numberFont);
        painter->setPen(muted);
        const QVariant number = index.data(TrackIndexRole);
        if (number.isValid()) {
            painter->drawText(markerRect, Qt::AlignCenter,
                              number.toString());
        }
    }

    const QRect coverRect(rect.x() + CoverX,
                          rect.y() + (rect.height() - CoverSize) / 2,
                          CoverSize, CoverSize);
    const QString coverPath = index.data(TrackCoverRole).toString();
    const QPixmap cover = CoverCache::cover(coverPath, CoverSize);
    QPainterPath clip;
    clip.addRoundedRect(coverRect, CoverRadius, CoverRadius);
    painter->save();
    painter->setClipPath(clip);
    if (!cover.isNull()) {
        painter->drawPixmap(coverRect, cover);
    } else {
        painter->fillRect(coverRect, palette.color(QPalette::Base));
        const QPixmap note = IconUtils::tinted(
                                 QStringLiteral("music-note.svg"), muted, 20)
                                 .pixmap(20, 20);
        painter->drawPixmap(coverRect.center().x() - 10,
                            coverRect.center().y() - 10, note);
    }
    painter->restore();

    const qint64 duration = index.data(TrackDurationRole).toLongLong();
    const QString durationLabel = durationText(duration);
    const int durationWidth =
        m_numberMetrics->horizontalAdvance(durationLabel) + 24;
    const int textLeft = rect.x() + TextX;
    const int textRight = rect.right() - durationWidth - 6;
    const int textWidth = qMax(0, textRight - textLeft);

    const bool exists = index.data(TrackExistsRole).toBool();
    QColor titleColor = textColor;
    if (!exists) {
        titleColor.setAlpha(110);
    }

    painter->setFont(m_titleFont);
    painter->setPen(titleColor);
    const QString title = m_titleMetrics->elidedText(
        index.data(TrackTitleRole).toString(), Qt::ElideRight, textWidth);
    painter->drawText(QRect(textLeft, rect.y() + 11, textWidth, 16),
                      Qt::AlignLeft | Qt::AlignVCenter, title);

    painter->setFont(m_artistFont);
    painter->setPen(muted);
    const QString artist = m_artistMetrics->elidedText(
        index.data(TrackArtistRole).toString(), Qt::ElideRight, textWidth);
    painter->drawText(QRect(textLeft, rect.y() + 30, textWidth, 15),
                      Qt::AlignLeft | Qt::AlignVCenter, artist);

    if (option.state & QStyle::State_MouseOver) {
        const QRect trash = trashRect(rect, duration);
        if (trackId > 0 && trackId == m_hoveredTrashTrackId) {
            painter->setPen(Qt::NoPen);
            painter->setBrush(QColor(224, 90, 74, 45));
            painter->drawEllipse(trash.adjusted(-5, -5, 5, 5));
        }
        painter->drawPixmap(trash, trashIcon());
    }

    painter->setFont(m_numberFont);
    painter->setPen(muted);
    painter->drawText(QRect(textRight, rect.y(), durationWidth - 14,
                            rect.height()),
                      Qt::AlignRight | Qt::AlignVCenter, durationLabel);

    painter->restore();
    if (paintDebug && paintTimer.elapsed() > 2) {
        std::fprintf(stderr, "[paint] %.2fms row=%s\n",
                     paintTimer.nsecsElapsed() / 1000000.0,
                     index.data(TrackTitleRole).toString().toUtf8().constData());
    }
}
