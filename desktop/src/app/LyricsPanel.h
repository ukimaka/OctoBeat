#pragma once

#include <QVector>
#include <QWidget>

#include "LyricsService.h"

class QPushButton;
class QTextBrowser;

class LyricsPanel : public QWidget {
    Q_OBJECT

public:
    explicit LyricsPanel(QWidget *parent = nullptr);

    void setContent(const QString &mode,
                    const QVector<LyricsLine> &lines,
                    const QString &plain);
    void setHighlight(int lineIndex, int wordIndex);
    void scrollToCurrent();
    void applyTheme();

signals:
    void offsetRequested(int deltaMs);
    void karaokeRequested();
    void fullscreenRequested();

private:
    void render();
    QString lineHtml(int index, const LyricsLine &line) const;

    QTextBrowser *m_view = nullptr;
    QPushButton *m_fullscreen = nullptr;
    QPushButton *m_karaoke = nullptr;
    QVector<LyricsLine> m_lines;
    QString m_plain;
    QString m_mode = QStringLiteral("empty");
    int m_lineIndex = -1;
    int m_wordIndex = -1;
};
