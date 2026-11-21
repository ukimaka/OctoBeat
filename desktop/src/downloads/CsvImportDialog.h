#pragma once

#include <QDialog>
#include <QString>
#include <QVector>

class QLabel;
class QPlainTextEdit;
class QProgressBar;
class QPushButton;
class SomeDlService;

class CsvImportDialog : public QDialog {
    Q_OBJECT

public:
    CsvImportDialog(const QString &csvPath,
                    const QString &musicDir,
                    const QString &dataDir,
                    QWidget *parent = nullptr);
    ~CsvImportDialog() override;

    void start();
    int trackCount() const { return m_rows.size(); }

signals:
    void libraryChanged();
    void finished(int added, int failed);

protected:
    void reject() override;

private:
    struct Row {
        QString artist;
        QString title;
    };

    void parseFile();
    void processNext();
    void failCurrent(const QString &reason);
    void finishImport();
    void cancelOrClose();
    void setStatus(const QString &text);
    QString cookiesPath() const;

    QString m_csvPath;
    QString m_musicDir;
    QString m_dataDir;
    QVector<Row> m_rows;
    QString m_parseError;
    int m_index = 0;
    int m_added = 0;
    int m_failed = 0;
    bool m_running = false;
    bool m_completed = false;

    QLabel *m_fileLabel = nullptr;
    QLabel *m_status = nullptr;
    QProgressBar *m_progress = nullptr;
    QPlainTextEdit *m_log = nullptr;
    QPushButton *m_action = nullptr;
    SomeDlService *m_downloader = nullptr;
};
