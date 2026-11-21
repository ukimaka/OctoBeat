#include "DownloadDialog.h"

#include "app/IconUtils.h"
#include "DownloadsPage.h"

#include <QColor>
#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QVBoxLayout>

DownloadDialog::DownloadDialog(const QString &musicDir,
                               const QString &dataDir,
                               QWidget *parent)
    : QDialog(parent) {
    setWindowFlags(Qt::Dialog | Qt::FramelessWindowHint);
    setAttribute(Qt::WA_TranslucentBackground, true);
    setWindowModality(Qt::ApplicationModal);
    resize(780, 640);

    auto *outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);

    auto *panel = new QFrame(this);
    panel->setObjectName(QStringLiteral("downloadDialogPanel"));
    panel->setAttribute(Qt::WA_StyledBackground, true);
    panel->setStyleSheet(QStringLiteral(
        "#downloadDialogPanel {"
        " background-color: rgba(20, 20, 24, 245);"
        " border: 1px solid rgba(255, 255, 255, 34);"
        " border-radius: 14px; }"));
    outer->addWidget(panel);

    auto *layout = new QVBoxLayout(panel);
    layout->setContentsMargins(16, 12, 16, 14);
    layout->setSpacing(8);

    auto *header = new QHBoxLayout();
    auto *title = new QLabel(tr("Download from YouTube"), panel);
    QFont titleFont = title->font();
    titleFont.setBold(true);
    titleFont.setPointSize(titleFont.pointSize() + 1);
    title->setFont(titleFont);
    auto *close = new QPushButton(panel);
    close->setFlat(true);
    close->setFixedSize(28, 28);
    close->setIcon(IconUtils::tinted(QStringLiteral("cancel.svg"),
                                     QColor(210, 210, 220), 16));
    close->setIconSize(QSize(14, 14));
    close->setToolTip(tr("Close"));
    header->addWidget(title);
    header->addStretch(1);
    header->addWidget(close);
    layout->addLayout(header);

    m_page = new DownloadsPage(musicDir, dataDir, panel);
    m_page->setTitleVisible(false);
    layout->addWidget(m_page, 1);

    connect(close, &QPushButton::clicked, this, &QDialog::reject);
    connect(m_page, &DownloadsPage::libraryChanged,
            this, &DownloadDialog::libraryChanged);

    if (parent) {
        move(parent->mapToGlobal(QPoint((parent->width() - width()) / 2,
                                        (parent->height() - height()) / 2)));
    }
}

void DownloadDialog::searchFor(const QString &query) {
    if (m_page) {
        m_page->searchFor(query);
    }
}
