#pragma once

#include <QPixmap>
#include <QRect>
#include <QStyledItemDelegate>

class PlaylistCoverDelegate : public QStyledItemDelegate {
public:
    explicit PlaylistCoverDelegate(QObject *parent = nullptr);

    QSize sizeHint(const QStyleOptionViewItem &option,
                   const QModelIndex &index) const override;
    void paint(QPainter *painter,
               const QStyleOptionViewItem &option,
               const QModelIndex &index) const override;

    static QRect coverRect(const QRect &itemRect);
    static QRect playRect(const QRect &itemRect);
    void setHoveredPlayRow(int row);

private:
    mutable QPixmap m_playIcon;
    int m_hoveredPlayRow = -1;
};
