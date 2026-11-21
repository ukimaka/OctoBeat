#pragma once

#include <QColor>
#include <QWidget>

#include "core/CoreClient.h"

class ClickSlider;
class QLabel;
class QPushButton;
class QNetworkAccessManager;

class MiniPlayer : public QWidget {
    Q_OBJECT

public:
    explicit MiniPlayer(QWidget *parent = nullptr);

    void setTrack(const Track &track);
    void setPlaying(bool playing);
    void setDuration(qint64 milliseconds);
    void setPosition(qint64 milliseconds);
    void applyTheme();
    void setSeekEnabled(bool enabled);
    void setCoverUrl(const QString &url);

signals:
    void playPauseRequested();
    void nextRequested();
    void previousRequested();
    void seekRequested(qint64 milliseconds);
    void expandRequested();
    void closeRequested();

protected:
    void paintEvent(QPaintEvent *event) override;
    void mousePressEvent(QMouseEvent *event) override;
    void mouseDoubleClickEvent(QMouseEvent *event) override;

private:
    static QString formatTime(qint64 milliseconds);
    void setCoverPixmap(const QPixmap &pixmap);
    void updateTint(const QPixmap &pixmap);

    QLabel *m_cover = nullptr;
    QLabel *m_title = nullptr;
    QLabel *m_artist = nullptr;
    QPushButton *m_previous = nullptr;
    QPushButton *m_play = nullptr;
    QPushButton *m_next = nullptr;
    QPushButton *m_expand = nullptr;
    QPushButton *m_close = nullptr;
    ClickSlider *m_seek = nullptr;
    QLabel *m_time = nullptr;
    qint64 m_duration = 0;
    bool m_draggingSeek = false;
    bool m_playing = false;
    QNetworkAccessManager *m_network = nullptr;
    QString m_coverUrl;
    QColor m_tint;
};
