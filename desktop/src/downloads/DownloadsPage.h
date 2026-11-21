#pragma once

#include <QVector>
#include <QWidget>

#include "YtDlpService.h"

class QLabel;
class QLineEdit;
class QListWidget;
class QNetworkAccessManager;
class QProgressBar;
class QPushButton;
class YouTubeSearchService;

class DownloadsPage : public QWidget {
    Q_OBJECT

public:
    DownloadsPage(const QString &musicDir,
                  const QString &dataDir,
                  QWidget *parent = nullptr);

    void searchFor(const QString &query);
    void setTitleVisible(bool visible);

signals:
    void libraryChanged();

private:
    QString cookiesPath() const;
    void startSearch();
    void cancelSearch();
    void showResults(const QVector<SearchResult> &results);
    void startDownload();
    void setBusy(bool busy, bool lockSearch = false);

    QString m_musicDir;
    QString m_dataDir;
    YouTubeSearchService *m_searchService = nullptr;
    YtDlpService *m_service = nullptr;
    QNetworkAccessManager *m_network = nullptr;
    QLabel *m_title = nullptr;
    QLineEdit *m_search = nullptr;
    QListWidget *m_results = nullptr;
    QLabel *m_status = nullptr;
    QProgressBar *m_progress = nullptr;
    QPushButton *m_searchButton = nullptr;
    QPushButton *m_cancelButton = nullptr;
    QPushButton *m_downloadButton = nullptr;
    QVector<SearchResult> m_items;
    bool m_fallbackSearch = false;
    bool m_suppressCancel = false;
};
