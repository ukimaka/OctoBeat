#pragma once

#include <QVector>
#include <QWidget>

#include "LyricsService.h"

class QPushButton;
class QTextBrowser;
class QKeyEvent;
class QLabel;
class QPaintEvent;

class FullscreenLyrics : public QWidget {
    Q_OBJECT

public:
    enum class Mode { Lyrics, Karaoke };

    explicit FullscreenLyrics(Mode mode, QWidget *parent = nullptr);

    void setContent(const QVector<LyricsLine> &lines, const QString &plain);
    void setHighlight(int lineIndex, int wordIndex);
    void setOffset(int offsetMs);

signals:
    void offsetRequested(int deltaMs);

protected:
    void keyPressEvent(QKeyEvent *event) override;
    void paintEvent(QPaintEvent *event) override;

private:
    void render();
    QString lineHtml(int index, const LyricsLine &line) const;

    Mode m_mode;
    QTextBrowser *m_view = nullptr;
    QPushButton *m_close = nullptr;
    QLabel *m_offsetLabel = nullptr;
    QVector<LyricsLine> m_lines;
    QString m_plain;
    int m_lineIndex = -1;
    int m_wordIndex = -1;
    int m_offsetMs = 0;
};
