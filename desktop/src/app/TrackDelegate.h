#pragma once

#include <QColor>
#include <QFont>
#include <QFontMetrics>
#include <QPixmap>
#include <QStyledItemDelegate>

#include <optional>

enum TrackRole {
    TrackIdRole = Qt::UserRole,
    TrackTitleRole,
    TrackArtistRole,
    TrackDurationRole,
    TrackCoverRole,
    TrackIndexRole,
    IsFolderRole,
    FolderNameRole,
    FolderIdRole,
    TrackExistsRole,
    TrackCoverIsAvatarRole,
};

class TrackDelegate : public QStyledItemDelegate {
public:
    explicit TrackDelegate(QObject *parent = nullptr);

    QSize sizeHint(const QStyleOptionViewItem &option,
                   const QModelIndex &index) const override;
    void paint(QPainter *painter,
               const QStyleOptionViewItem &option,
               const QModelIndex &index) const override;

    void setCurrentPlaying(qint64 trackId);
    void setHoveredTrashTrackId(qint64 trackId);
    qint64 currentPlaying() const { return m_currentPlaying; }
    void setAccentColor(const QColor &color);
    void resetIcons();
    QRect trashRect(const QRect &rowRect, qint64 durationSeconds) const;

private:
    void ensureFonts(const QFont &baseFont) const;
    const QPixmap &playMarker(const QColor &color) const;
    const QPixmap &folderIcon(const QColor &color) const;
    const QPixmap &trashIcon() const;

    mutable QString m_fontKey;
    mutable QFont m_titleFont;
    mutable QFont m_artistFont;
    mutable QFont m_numberFont;
    mutable QFont m_folderFont;
    mutable std::optional<QFontMetrics> m_titleMetrics;
    mutable std::optional<QFontMetrics> m_artistMetrics;
    mutable std::optional<QFontMetrics> m_numberMetrics;
    mutable std::optional<QFontMetrics> m_folderMetrics;

    mutable std::optional<QPixmap> m_playPixmap;
    mutable std::optional<QPixmap> m_folderPixmap;
    mutable std::optional<QPixmap> m_trashPixmap;
    mutable QColor m_playColor;
    mutable QColor m_folderColor;
    qint64 m_currentPlaying = 0;
    qint64 m_hoveredTrashTrackId = 0;
    QColor m_accent;
};
