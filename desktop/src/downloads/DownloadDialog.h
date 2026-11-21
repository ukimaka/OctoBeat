#pragma once

#include <QDialog>

class DownloadsPage;
class QFrame;

class DownloadDialog : public QDialog {
    Q_OBJECT

public:
    DownloadDialog(const QString &musicDir,
                   const QString &dataDir,
                   QWidget *parent = nullptr);

    void searchFor(const QString &query);

signals:
    void libraryChanged();

private:
    DownloadsPage *m_page = nullptr;
};
