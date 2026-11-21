#pragma once

#include <QObject>
#include <QString>
#include <QStringList>

class QProcess;
class QTemporaryDir;
class QTimer;

// External SomeDL CLI wrapper. SomeDL downloads YouTube audio, resolves
// MusicBrainz/Genius/Deezer metadata and embeds a cover. The application
// keeps only the audio file; reports and sidecar images stay in the temporary
// staging folder and are removed with it.
class SomeDlService : public QObject {
    Q_OBJECT

public:
    explicit SomeDlService(const QString &dataDir,
                           QObject *parent = nullptr);
    ~SomeDlService() override;

    static bool isAvailable();
    static QString executablePath();

    void download(const QString &query,
                  const QString &outputDir,
                  const QString &cookiesPath = {});
    void cancel();

    bool isBusy() const;
    QString lastError() const { return m_lastError; }

signals:
    void downloadProgress(int percent);
    void downloadFinished(const QString &filePath);
    void failed(const QString &message);
    void canceled();

private:
    void start(const QStringList &args);
    void stopProcess();
    void handleOutput();
    void handleFinished(int exitCode);
    void handleError();
    void fail(const QString &message);
    void cleanup();

    QString m_dataDir;
    QString m_query;
    QString m_outputDir;
    QString m_cookies;
    QProcess *m_process = nullptr;
    QTemporaryDir *m_staging = nullptr;
    QTimer *m_timeout = nullptr;
    QTimer *m_stall = nullptr;
    QString m_output;
    QString m_lastError;
    bool m_canceled = false;
};
