#include "PlaylistCoverDelegate.h"

#include "CoverCache.h"
#include "IconUtils.h"
#include "TrackDelegate.h"
#include "app/Theme.h"

#include <QAbstractItemView>
#include <QFontMetrics>
#include <QPainter>
#include <QPainterPath>
#include <QStyle>

namespace {
constexpr int CoverSize = 160;
constexpr int CoverRadius = 8;
constexpr int PlaySize = 44;
constexpr int PlayMargin = 8;
} // namespace

PlaylistCoverDelegate::PlaylistCoverDelegate(QObject *parent)
    : QStyledItemDelegate(parent) {}

QSize PlaylistCoverDelegate::sizeHint(const QStyleOptionViewItem &,
                                      const QModelIndex &) const {
    return QSize(180, 210);
}

QRect PlaylistCoverDelegate::coverRect(const QRect &itemRect) {
    return QRect(itemRect.x() + (itemRect.width() - CoverSize) / 2,
                 itemRect.y() + 8, CoverSize, CoverSize);
}

QRect PlaylistCoverDelegate::playRect(const QRect &itemRect) {
    const QRect cover = coverRect(itemRect);
    return QRect(cover.right() - PlaySize - PlayMargin,
                 cover.bottom() - PlaySize - PlayMargin, PlaySize, PlaySize);
}

void PlaylistCoverDelegate::setHoveredPlayRow(int row) {
    if (m_hoveredPlayRow == row) {
        return;
    }
    m_hoveredPlayRow = row;
    if (auto *view = qobject_cast<QAbstractItemView *>(parent())) {
        view->viewport()->update();
    }
}

void PlaylistCoverDelegate::paint(QPainter *painter,
                                  const QStyleOptionViewItem &option,
                                  const QModelIndex &index) const {
    if (!painter) {
        return;
    }
    painter->save();
    painter->setRenderHint(QPainter::Antialiasing, true);
    painter->setRenderHint(QPainter::SmoothPixmapTransform, true);

    const QRect itemRect = option.rect;
    const QRect cover = coverRect(itemRect);
    const bool hover = option.state & QStyle::State_MouseOver;
    const QColor textColor = option.palette.color(QPalette::Text);

    QPainterPath clip;
    if (index.data(TrackCoverIsAvatarRole).toBool()) {
        clip.addEllipse(cover);
    } else {
        clip.addRoundedRect(cover, CoverRadius, CoverRadius);
    }
    painter->save();
    painter->setClipPath(clip);
    const QPixmap pixmap = CoverCache::cover(
        index.data(TrackCoverRole).toString(), CoverSize);
    if (!pixmap.isNull()) {
        painter->drawPixmap(cover, pixmap);
    } else {
        painter->fillRect(cover, option.palette.color(QPalette::Base));
        const QPixmap note =
            IconUtils::tinted(QStringLiteral("music-note.svg"), textColor, 48)
                .pixmap(48, 48);
        painter->drawPixmap(cover.center().x() - 24,
                            cover.center().y() - 24, note);
    }
    if (hover) {
        painter->fillRect(cover, QColor(0, 0, 0, 120));
    }
    painter->restore();

    if (hover) {
        QRect button = playRect(itemRect);
        const bool buttonHovered = index.row() == m_hoveredPlayRow;
        if (buttonHovered) {
            button.adjust(-2, -2, 2, 2);
        }
        painter->setPen(Qt::NoPen);
        const QColor accent = Theme::accent();
        painter->setBrush(buttonHovered ? accent.lighter(120) : accent);
        painter->drawEllipse(button);
        if (m_playIcon.isNull()) {
            m_playIcon = IconUtils::tinted(QStringLiteral("play.svg"),
                                           QColor(Qt::white), 20)
                             .pixmap(20, 20);
        }
        painter->drawPixmap(button.center().x() - 10,
                            button.center().y() - 10, m_playIcon);
    }

    QFont titleFont = option.font;
    titleFont.setPixelSize(13);
    titleFont.setBold(true);
    painter->setFont(titleFont);
    painter->setPen(textColor);
    const QRect titleRect(itemRect.x() + 8, cover.bottom() + 10,
                          itemRect.width() - 16, 20);
    const QString title = QFontMetrics(titleFont).elidedText(
        index.data(TrackTitleRole).toString(), Qt::ElideRight,
        titleRect.width());
    painter->drawText(titleRect, Qt::AlignHCenter | Qt::AlignVCenter, title);
    painter->restore();
}
