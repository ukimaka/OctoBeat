#pragma once

#include <QObject>
#include <QProcess>
#include <QString>
#include <QVector>

#include "SearchResult.h"

class QTimer;

class YtDlpService : public QObject {
    Q_OBJECT

public:
    explicit YtDlpService(QObject *parent = nullptr);
    ~YtDlpService() override;

    void search(const QString &query, const QString &cookiesPath = {});
    void download(const QString &url,
                  const QString &outputDir,
                  const QString &cookiesPath = {});
    void resolveStream(const QString &url, const QString &cookiesPath = {});
    void resolveAudioHls(const QString &url, const QString &cookiesPath = {});
    void downloadForStream(const QString &url,
                           const QString &outputDir,
                           const QString &cookiesPath = {});
    // Downloads a complete audio file to a stable cache path. Unlike
    // downloadForStream, the output name is controlled by the caller so it
    // can be found again on the next play/seek.
    void cacheStream(const QString &url,
                     const QString &cacheDir,
                     const QString &key,
                     const QString &cookiesPath = {});
    void cancel();

    bool isBusy() const;
    QString lastError() const { return m_lastError; }

signals:
    void searchFinished(const QVector<SearchResult> &results);
    void downloadProgress(int percent);
    void downloadFinished(const QString &filePath);
    void streamResolved(const QString &url,
                        const QString &title,
                        const QString &uploader,
                        int durationSeconds);
    void failed(const QString &message);
    void canceled();

private:
    enum class Mode { None, Search, Download, Stream };
    enum class StreamAttempt { None, AudioHls, EmbeddedHls };

    void start(Mode mode, const QStringList &args);
    void stopProcess();
    void armTimeout(int milliseconds);
    void handleFinished(int exitCode, QProcess::ExitStatus exitStatus);
    void handleError();
    void handleOutput();
    QString executable() const;
    QStringList commonArgs(const QString &cookiesPath,
                           bool jsRuntime = true) const;
    void startDownloadAttempt(bool embed);
    static QString cleanOutput(const QString &text);

    QProcess *m_process = nullptr;
    Mode m_mode = Mode::None;
    QString m_output;
    QString m_lastError;
    QString m_downloadUrl;
    QString m_downloadDir;
    QString m_downloadCookies;
    bool m_downloadEmbedded = true;
    QString m_streamUrl;
    StreamAttempt m_streamAttempt = StreamAttempt::None;
    QTimer *m_timeout = nullptr;
    QTimer *m_stallTimer = nullptr;
};
