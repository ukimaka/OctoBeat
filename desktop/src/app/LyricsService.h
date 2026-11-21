#pragma once

#include <QJsonObject>
#include <QObject>
#include <QSet>
#include <QString>
#include <QVector>

#include "core/CoreClient.h"

class QNetworkAccessManager;

struct LyricsWord {
    qint64 timeMs = -1;
    QString text;
};

struct LyricsLine {
    qint64 timeMs = 0;
    QString text;
    QVector<LyricsWord> words;
};

class LyricsService : public QObject {
    Q_OBJECT

public:
    explicit LyricsService(CoreClient *core, QObject *parent = nullptr);

    void setTrack(const Track &track);
    void clear();
    void setPosition(qint64 milliseconds);
    void adjustOffset(int deltaMs);
    void reloadCurrent();
    void refreshHighlight();

    const QVector<LyricsLine> &lines() const { return m_lines; }
    const QString &plain() const { return m_plain; }
    QString mode() const { return m_mode; }
    int offsetMs() const { return m_offsetMs; }
    qint64 trackId() const { return m_trackId; }
    int lineIndex() const { return m_lineIndex; }
    int wordIndex() const { return m_wordIndex; }

signals:
    void contentChanged(const QString &mode,
                        const QVector<LyricsLine> &lines,
                        const QString &plain);
    void highlightChanged(int lineIndex, int wordIndex);
    void offsetChanged(int offsetMs);

private:
    void loadForTrack();
    void applyPayload(const QString &synced,
                      const QString &plain,
                      bool loading,
                      const QString &lyricsFile = {});
    void fetchFromLrclib();
    void handleSearchReply(class QNetworkReply *reply, qint64 trackId, int token);
    void handleGetReply(class QNetworkReply *reply, qint64 trackId, int token);
    void pickRecord(const QJsonObject &record);
    void computeHighlight(bool force);
    void emitContent();
    int lineIndexFor(qint64 position) const;
    int wordIndexFor(int lineIndex, qint64 position) const;

    CoreClient *m_core = nullptr;
    QNetworkAccessManager *m_network = nullptr;
    Track m_track;
    qint64 m_trackId = 0;
    QVector<LyricsLine> m_lines;
    QString m_plain;
    QString m_mode = QStringLiteral("empty");
    qint64 m_position = 0;
    int m_offsetMs = 0;
    int m_lineIndex = -1;
    int m_wordIndex = -1;
    QSet<qint64> m_attempted;
    bool m_loading = false;
    int m_fetchToken = 0;
};
