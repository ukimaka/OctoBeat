#include "DownloadsPage.h"

#include "app/IconUtils.h"
#include "YouTubeSearchService.h"

#include "app/SmoothListWidget.h"

#include <QDir>
#include <QFileInfo>
#include <QFont>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMessageBox>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QPixmap>
#include <QProgressBar>
#include <QPushButton>
#include <QUrl>
#include <QVBoxLayout>

DownloadsPage::DownloadsPage(const QString &musicDir,
                             const QString &dataDir,
                             QWidget *parent)
    : QWidget(parent), m_musicDir(musicDir), m_dataDir(dataDir) {
    m_searchService = new YouTubeSearchService(this);
    m_service = new YtDlpService(this);
    m_network = new QNetworkAccessManager(this);

    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(18, 14, 18, 10);
    root->setSpacing(8);

    m_title = new QLabel(tr("Download music"), this);
    m_title->setObjectName(QStringLiteral("pageTitle"));
    QFont titleFont = m_title->font();
    titleFont.setBold(true);
    titleFont.setPointSize(titleFont.pointSize() + 4);
    m_title->setFont(titleFont);
    root->addWidget(m_title);

    auto *searchRow = new QHBoxLayout();
    m_search = new QLineEdit(this);
    m_search->setPlaceholderText(tr("Search YouTube..."));
    m_search->setClearButtonEnabled(true);
    m_searchButton = new QPushButton(tr("Search"), this);
    m_searchButton->setIcon(IconUtils::tinted(QStringLiteral("search.svg"),
                                             QColor(205, 205, 215), 18));
    m_searchButton->setIconSize(QSize(16, 16));
    m_searchButton->setCursor(Qt::PointingHandCursor);
    searchRow->addWidget(m_search, 1);
    searchRow->addWidget(m_searchButton);
    root->addLayout(searchRow);

    m_status = new QLabel(this);
    m_status->setObjectName(QStringLiteral("downloadStatus"));
    root->addWidget(m_status);

    m_results = new SmoothListWidget(this);
    m_results->setObjectName(QStringLiteral("downloadResults"));
    m_results->setIconSize(QSize(64, 36));
    m_results->setUniformItemSizes(true);
    m_results->setSelectionMode(QAbstractItemView::SingleSelection);
    root->addWidget(m_results, 1);

    auto *bottom = new QHBoxLayout();
    m_progress = new QProgressBar(this);
    m_progress->setRange(0, 100);
    m_progress->setValue(0);
    m_progress->setTextVisible(true);
    m_downloadButton = new QPushButton(tr("Download selected"), this);
    m_downloadButton->setIcon(IconUtils::tinted(QStringLiteral("download.svg"),
                                                QColor(205, 205, 215), 18));
    m_downloadButton->setIconSize(QSize(16, 16));
    m_downloadButton->setCursor(Qt::PointingHandCursor);
    m_downloadButton->setEnabled(false);
    m_cancelButton = new QPushButton(tr("Cancel"), this);
    m_cancelButton->setEnabled(false);
    bottom->addWidget(m_progress, 1);
    bottom->addWidget(m_cancelButton);
    bottom->addWidget(m_downloadButton);
    root->addLayout(bottom);

    connect(m_searchButton, &QPushButton::clicked, this, &DownloadsPage::startSearch);
    connect(m_search, &QLineEdit::returnPressed, this, &DownloadsPage::startSearch);
    connect(m_results, &QListWidget::itemSelectionChanged, this, [this] {
        m_downloadButton->setEnabled(m_results->currentItem() != nullptr &&
                                     !m_service->isBusy());
    });
    connect(m_downloadButton, &QPushButton::clicked, this, &DownloadsPage::startDownload);
    connect(m_cancelButton, &QPushButton::clicked, this,
            &DownloadsPage::cancelSearch);
    connect(m_network, &QNetworkAccessManager::finished, this,
            [this](QNetworkReply *reply) {
                const QByteArray data = reply->readAll();
                QPixmap cover;
                if (!data.isEmpty() && cover.loadFromData(data)) {
                    const QString url = reply->url().toString();
                    const QIcon icon(cover.scaled(64, 36, Qt::KeepAspectRatioByExpanding,
                                                   Qt::SmoothTransformation));
                    for (int row = 0; row < m_results->count(); ++row) {
                        QListWidgetItem *item = m_results->item(row);
                        if (item && item->data(Qt::UserRole + 1).toString() == url) {
                            item->setIcon(icon);
                        }
                    }
                }
                reply->deleteLater();
            });

    connect(m_searchService, &YouTubeSearchService::finished, this,
            [this](const QVector<SearchResult> &results) {
                m_fallbackSearch = false;
                showResults(results);
            });
    connect(m_searchService, &YouTubeSearchService::failed, this,
            [this](const QString &message) {
                if (m_suppressCancel) {
                    return;
                }
                const QString query = m_search->text().trimmed();
                if (!m_fallbackSearch && !query.isEmpty()) {
                    m_fallbackSearch = true;
                    m_status->setText(tr("Trying alternate search…"));
                    m_service->search(query, cookiesPath());
                    return;
                }
                m_fallbackSearch = false;
                m_status->setText(message);
                setBusy(false);
            });
    connect(m_searchService, &YouTubeSearchService::canceled, this, [this] {
        if (m_suppressCancel) {
            return;
        }
        m_fallbackSearch = false;
        m_status->setText(tr("Search canceled."));
        setBusy(false);
    });
    connect(m_service, &YtDlpService::searchFinished, this,
            [this](const QVector<SearchResult> &results) {
                m_fallbackSearch = false;
                showResults(results);
            });
    connect(m_service, &YtDlpService::downloadProgress, this, [this](int percent) {
        m_progress->setValue(percent);
        m_status->setText(tr("Downloading… %1%").arg(percent));
    });
    connect(m_service, &YtDlpService::downloadFinished, this, [this](const QString &path) {
        m_progress->setValue(100);
        m_status->setText(tr("Downloaded: %1").arg(QFileInfo(path).fileName()));
        setBusy(false);
        emit libraryChanged();
    });
    connect(m_service, &YtDlpService::failed, this, [this](const QString &message) {
        if (m_suppressCancel) {
            return;
        }
        if (m_fallbackSearch) {
            m_fallbackSearch = false;
            m_status->setText(message);
            setBusy(false);
            return;
        }
        m_status->setText(message);
        setBusy(false);
        QMessageBox::warning(this, tr("Download error"), message);
    });
    connect(m_service, &YtDlpService::canceled, this, [this] {
        if (m_suppressCancel) {
            return;
        }
        m_status->setText(tr("Canceled."));
        setBusy(false);
    });
    connect(m_service, &YtDlpService::streamResolved, this,
            [](const QString &, const QString &, const QString &) {});

    setBusy(false);
}

void DownloadsPage::setTitleVisible(bool visible) {
    if (m_title) {
        m_title->setVisible(visible);
    }
}

void DownloadsPage::searchFor(const QString &query) {
    if (!m_search || query.trimmed().isEmpty()) {
        return;
    }
    m_search->setText(query);
    startSearch();
}

QString DownloadsPage::cookiesPath() const {
    const QStringList candidates = {
        QDir(m_dataDir).filePath(QStringLiteral("cookies.txt")),
        QDir(m_musicDir).filePath(QStringLiteral("cookies.txt")),
    };
    for (const QString &candidate : candidates) {
        if (QFileInfo(candidate).isFile()) {
            return candidate;
        }
    }
    return {};
}

void DownloadsPage::startSearch() {
    const QString query = m_search->text().trimmed();
    if (query.isEmpty()) {
        m_status->setText(tr("Enter a search query."));
        return;
    }
    m_suppressCancel = true;
    m_searchService->cancel();
    m_service->cancel();
    m_suppressCancel = false;
    m_fallbackSearch = false;
    m_results->clear();
    m_items.clear();
    m_progress->setValue(0);
    m_progress->setRange(0, 0);
    setBusy(true);
    m_status->setText(tr("Searching YouTube…"));
    m_searchService->search(query);
}

void DownloadsPage::cancelSearch() {
    m_suppressCancel = true;
    m_searchService->cancel();
    m_service->cancel();
    m_suppressCancel = false;
    m_fallbackSearch = false;
    m_status->setText(tr("Canceled."));
    setBusy(false);
}

void DownloadsPage::showResults(const QVector<SearchResult> &results) {
    m_items = results;
    m_results->clear();
    for (const SearchResult &result : results) {
        const qint64 minutes = result.duration / 60;
        const qint64 seconds = result.duration % 60;
        const QString duration = QStringLiteral("%1:%2")
            .arg(minutes)
            .arg(seconds, 2, 10, QLatin1Char('0'));
        auto *item = new QListWidgetItem(
            QStringLiteral("%1\n%2 · %3")
                .arg(result.title,
                     result.uploader.isEmpty() ? tr("Unknown channel")
                                               : result.uploader,
                     duration),
            m_results);
        item->setSizeHint(QSize(0, 54));
        item->setData(Qt::UserRole + 1, result.thumbnail);
        if (!result.thumbnail.isEmpty()) {
            m_network->get(QNetworkRequest(QUrl(result.thumbnail)));
        }
    }
    m_status->setText(tr("%n result(s)", "", results.size()));
    if (!results.isEmpty()) {
        m_results->setCurrentRow(0);
    }
    setBusy(false);
}

void DownloadsPage::startDownload() {
    QListWidgetItem *item = m_results->currentItem();
    if (!item || item->listWidget() != m_results) {
        return;
    }
    const int index = m_results->row(item);
    if (index < 0 || index >= m_items.size()) {
        return;
    }
    if (!QDir().mkpath(m_musicDir)) {
        QMessageBox::warning(this, tr("Download error"),
                             tr("Could not create the download folder: %1").arg(m_musicDir));
        return;
    }
    setBusy(true, true);
    m_progress->setRange(0, 100);
    m_progress->setValue(0);
    m_status->setText(tr("Starting download…"));
    m_service->download(m_items[index].url, m_musicDir, cookiesPath());
}

void DownloadsPage::setBusy(bool busy, bool lockSearch) {
    m_searchButton->setEnabled(!busy || !lockSearch);
    m_search->setEnabled(!busy || !lockSearch);
    m_results->setEnabled(!busy || !lockSearch);
    m_downloadButton->setEnabled(!busy && m_results->currentItem() != nullptr);
    if (m_cancelButton) {
        m_cancelButton->setEnabled(busy);
    }
    if (!busy && m_progress->maximum() == 0) {
        m_progress->setRange(0, 100);
        m_progress->setValue(0);
    }
}
