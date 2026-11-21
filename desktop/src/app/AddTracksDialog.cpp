#include "AddTracksDialog.h"

#include "CoverCache.h"
#include "SmoothListWidget.h"
#include "IconUtils.h"
#include "Theme.h"
#include "TrackDelegate.h"

#include <QAbstractItemView>
#include <QColor>
#include <QFontMetrics>
#include <QEvent>
#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QMouseEvent>
#include <QPainter>
#include <QPainterPath>
#include <QPushButton>
#include <QStyledItemDelegate>
#include <QStyle>
#include <QVBoxLayout>

namespace {

constexpr int RowHeight = 58;
constexpr int CoverSize = 40;
constexpr int CheckSize = 18;

QString titleOf(const Track &track) {
    return track.title.isEmpty() ? QObject::tr("Unknown title") : track.title;
}

QString artistOf(const Track &track) {
    return track.artist.isEmpty() ? QObject::tr("Unknown artist") : track.artist;
}

class CheckableTrackDelegate : public QStyledItemDelegate {
public:
    explicit CheckableTrackDelegate(QObject *parent = nullptr)
        : QStyledItemDelegate(parent) {}

    QSize sizeHint(const QStyleOptionViewItem &option,
                   const QModelIndex &index) const override {
        Q_UNUSED(index);
        return QSize(option.rect.width(), RowHeight);
    }

    void paint(QPainter *painter,
               const QStyleOptionViewItem &option,
               const QModelIndex &index) const override {
        painter->save();
        painter->setRenderHint(QPainter::Antialiasing, true);
        painter->setRenderHint(QPainter::SmoothPixmapTransform, true);

        const QRect rect = option.rect;
        const bool checked =
            index.data(Qt::CheckStateRole).toInt() == Qt::Checked;
        const QColor accent = Theme::accent();
        const QPalette &palette = option.palette;

        if (checked) {
            QColor fill = accent;
            fill.setAlpha(28);
            painter->fillRect(rect, fill);
        } else if (option.state & QStyle::State_MouseOver) {
            QColor fill = palette.color(QPalette::WindowText);
            fill.setAlpha(15);
            painter->fillRect(rect, fill);
        }

        const QRect checkRect(rect.x() + 12,
                              rect.y() + (rect.height() - CheckSize) / 2,
                              CheckSize, CheckSize);
        if (checked) {
            painter->setPen(Qt::NoPen);
            painter->setBrush(accent);
            painter->drawRoundedRect(checkRect, 4, 4);
            const QPixmap mark =
                IconUtils::tinted(QStringLiteral("confirm.svg"),
                                  QColor(Qt::white), 12)
                    .pixmap(12, 12);
            painter->drawPixmap(checkRect.center().x() - 6,
                                checkRect.center().y() - 6, mark);
        } else {
            QColor border = palette.color(QPalette::WindowText);
            border.setAlpha(90);
            painter->setPen(QPen(border, 1.2));
            painter->setBrush(Qt::NoBrush);
            painter->drawRoundedRect(checkRect, 4, 4);
        }

        const QRect coverRect(rect.x() + 42,
                              rect.y() + (rect.height() - CoverSize) / 2,
                              CoverSize, CoverSize);
        const QPixmap cover =
            CoverCache::cover(index.data(TrackCoverRole).toString(), CoverSize);
        QPainterPath clip;
        clip.addRoundedRect(coverRect, 5, 5);
        painter->save();
        painter->setClipPath(clip);
        if (!cover.isNull()) {
            painter->drawPixmap(coverRect, cover);
        } else {
            painter->fillRect(coverRect, palette.color(QPalette::Base));
        }
        painter->restore();

        const int textLeft = coverRect.right() + 12;
        const int textWidth = qMax(20, rect.right() - textLeft - 12);
        QFont titleFont = option.font;
        titleFont.setPixelSize(13);
        titleFont.setBold(true);
        painter->setFont(titleFont);
        painter->setPen(palette.color(QPalette::Text));
        const QFontMetrics titleMetrics(titleFont);
        painter->drawText(
            QRect(textLeft, rect.y() + 8, textWidth, 19),
            Qt::AlignLeft | Qt::AlignVCenter,
            titleMetrics.elidedText(index.data(TrackTitleRole).toString(),
                                    Qt::ElideRight, textWidth));

        QFont artistFont = option.font;
        artistFont.setPixelSize(11);
        painter->setFont(artistFont);
        QColor muted = palette.color(QPalette::WindowText);
        muted.setAlpha(150);
        painter->setPen(muted);
        const QFontMetrics artistMetrics(artistFont);
        painter->drawText(
            QRect(textLeft, rect.y() + 28, textWidth, 18),
            Qt::AlignLeft | Qt::AlignVCenter,
            artistMetrics.elidedText(index.data(TrackArtistRole).toString(),
                                     Qt::ElideRight, textWidth));
        painter->restore();
    }
};

class DimOverlay : public QWidget {
public:
    explicit DimOverlay(QWidget *parent) : QWidget(parent) {
        setAttribute(Qt::WA_TranslucentBackground, true);
        setAttribute(Qt::WA_TransparentForMouseEvents, true);
        setAttribute(Qt::WA_ShowWithoutActivating, true);
        setFocusPolicy(Qt::NoFocus);
    }

protected:
    void paintEvent(QPaintEvent *) override {
        QPainter painter(this);
        painter.fillRect(rect(), QColor(0, 0, 0, 102));
    }
};

class CheckableList : public SmoothListWidget {
public:
    explicit CheckableList(QWidget *parent = nullptr) : SmoothListWidget(parent) {}

protected:
    void mouseReleaseEvent(QMouseEvent *event) override {
        if (event->button() == Qt::LeftButton) {
            QListWidgetItem *item = itemAt(event->pos());
            if (item) {
                item->setCheckState(item->checkState() == Qt::Checked
                                        ? Qt::Unchecked
                                        : Qt::Checked);
                event->accept();
                return;
            }
        }
        SmoothListWidget::mouseReleaseEvent(event);
    }
};

} // namespace

AddTracksDialog::AddTracksDialog(const QVector<Track> &tracks,
                                 const QSet<qint64> &existingIds,
                                 QWidget *parent)
    : QDialog(parent) {
    setWindowFlags(Qt::Dialog | Qt::FramelessWindowHint |
                   Qt::WindowStaysOnTopHint);
    setAttribute(Qt::WA_TranslucentBackground, true);
    setWindowModality(Qt::ApplicationModal);
    setMinimumSize(600, 540);
    resize(640, 620);

    QWidget *dimTarget = parent ? parent->window() : nullptr;
    DimOverlay *overlay = nullptr;
    if (dimTarget) {
        overlay = new DimOverlay(dimTarget);
        overlay->setGeometry(dimTarget->rect());
        overlay->show();
        overlay->raise();
        connect(this, &QDialog::finished, overlay, &QWidget::deleteLater);
    }

    const bool dark = Theme::isDark(Theme::current());
    const QString panelBg = dark ? QStringLiteral("rgba(20, 20, 24, 235)")
                                 : QStringLiteral("rgba(248, 249, 251, 240)");
    const QString border = dark ? QStringLiteral("rgba(255, 255, 255, 34)")
                                : QStringLiteral("rgba(0, 0, 0, 24)");
    const QString field = dark ? QStringLiteral("rgba(255, 255, 255, 14)")
                               : QStringLiteral("rgba(0, 0, 0, 10)");
    const QString text = dark ? QStringLiteral("#ffffff") : QStringLiteral("#1a1a1a");
    const QString muted = dark ? QStringLiteral("#a7a7b2") : QStringLiteral("#5e5e66");
    setStyleSheet(
        QStringLiteral(
            "QDialog { background: transparent; }"
            "#cdRoot { background-color: %1; border: 1px solid %2;"
            " border-radius: 14px; }"
            "#cdTitle { color: %3; font-size: 14px; font-weight: bold; }"
            "#cdClose { background: transparent; border: none; border-radius: 8px; }"
            "#cdClose:hover { background: %4; }"
            "#cdBulkList { background: %4; border: 1px solid %2;"
            " border-radius: 10px; outline: none; color: %3; }"
            "#cdConfirm { background: #5151ab; color: #ffffff; border: none;"
            " border-radius: 8px; padding: 8px 22px; font-weight: bold; }"
            "#cdConfirm:hover { background: #6262c4; }"
            "#cdConfirm:disabled { background: %4; color: %5; }"
            "#cdCancel { background: %4; color: %3; border: none;"
            " border-radius: 8px; padding: 8px 22px; }"
            "#cdCancel:hover { background: %6; }")
            .arg(panelBg, border, text, field, muted,
                 dark ? QStringLiteral("rgba(255, 255, 255, 28)")
                      : QStringLiteral("rgba(0, 0, 0, 18)")));

    auto *outer = new QVBoxLayout(this);
    outer->setContentsMargins(16, 16, 16, 16);

    auto *panel = new QFrame(this);
    panel->setObjectName(QStringLiteral("cdRoot"));
    panel->setAttribute(Qt::WA_StyledBackground, true);
    auto *panelLayout = new QVBoxLayout(panel);
    panelLayout->setContentsMargins(16, 12, 16, 12);
    panelLayout->setSpacing(10);

    auto *header = new QHBoxLayout();
    auto *title = new QLabel(tr("Add Tracks"), panel);
    title->setObjectName(QStringLiteral("cdTitle"));
    auto *close = new QPushButton(panel);
    close->setObjectName(QStringLiteral("cdClose"));
    close->setFixedSize(28, 28);
    close->setFlat(true);
    close->setCursor(Qt::PointingHandCursor);
    close->setIcon(IconUtils::tinted(QStringLiteral("cancel.svg"),
                                     Theme::iconColor(), 16));
    close->setIconSize(QSize(14, 14));
    header->addWidget(title);
    header->addStretch(1);
    header->addWidget(close);
    panelLayout->addLayout(header);

    m_list = new CheckableList(panel);
    m_list->setObjectName(QStringLiteral("cdBulkList"));
    m_list->setSelectionMode(QAbstractItemView::NoSelection);
    m_list->setUniformItemSizes(true);
    m_list->setVerticalScrollMode(QAbstractItemView::ScrollPerPixel);
    m_list->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_list->setMouseTracking(true);
    m_list->setItemDelegate(new CheckableTrackDelegate(m_list));
    for (const Track &track : tracks) {
        auto *item = new QListWidgetItem(m_list);
        item->setData(TrackIdRole, track.id);
        item->setData(TrackTitleRole, titleOf(track));
        item->setData(TrackArtistRole, artistOf(track));
        item->setData(TrackCoverRole, track.coverPath);
        item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsUserCheckable);
        item->setCheckState(existingIds.contains(track.id) ? Qt::Checked
                                                           : Qt::Unchecked);
        item->setSizeHint(QSize(0, RowHeight));
    }
    panelLayout->addWidget(m_list, 1);

    auto *footer = new QHBoxLayout();
    footer->addStretch(1);
    auto *cancel = new QPushButton(tr("Cancel"), panel);
    cancel->setObjectName(QStringLiteral("cdCancel"));
    cancel->setCursor(Qt::PointingHandCursor);
    m_confirm = new QPushButton(tr("OK"), panel);
    m_confirm->setObjectName(QStringLiteral("cdConfirm"));
    m_confirm->setCursor(Qt::PointingHandCursor);
    m_confirm->setEnabled(false);
    footer->addWidget(cancel);
    footer->addWidget(m_confirm);
    panelLayout->addLayout(footer);
    outer->addWidget(panel);

    connect(close, &QPushButton::clicked, this, &QDialog::reject);
    connect(cancel, &QPushButton::clicked, this, &QDialog::reject);
    connect(m_confirm, &QPushButton::clicked, this, &QDialog::accept);
    connect(m_list, &QListWidget::itemChanged, this,
            [this](QListWidgetItem *) { updateConfirmState(); });
    updateConfirmState();

    if (parent) {
        move(parent->mapToGlobal(QPoint((parent->width() - width()) / 2,
                                        (parent->height() - height()) / 2)));
    }
}

QVector<qint64> AddTracksDialog::selectedTrackIds() const {
    QVector<qint64> ids;
    if (!m_list) {
        return ids;
    }
    for (int i = 0; i < m_list->count(); ++i) {
        QListWidgetItem *item = m_list->item(i);
        if (item && item->checkState() == Qt::Checked) {
            const qint64 id = item->data(TrackIdRole).toLongLong();
            if (id > 0) {
                ids.push_back(id);
            }
        }
    }
    return ids;
}

void AddTracksDialog::updateConfirmState() {
    if (m_confirm) {
        m_confirm->setEnabled(!selectedTrackIds().isEmpty());
    }
}
