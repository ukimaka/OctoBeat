#pragma once

#include <QWidget>

#include "SearchResult.h"

class ElidedLabel;
class QLabel;
class QToolButton;
class RemoteImageCache;
class QEnterEvent;
class QVBoxLayout;

class StreamCard : public QWidget {
    Q_OBJECT

public:
    explicit StreamCard(const SearchResult &result,
                        RemoteImageCache *images,
                        QWidget *parent = nullptr);

    const SearchResult &result() const { return m_result; }
    void setPlaying(bool playing);
    void setCompact(bool compact);
    void updatePlayPosition();

signals:
    void activated(const SearchResult &result);
    void playRequested(const SearchResult &result);
    void downloadRequested(const SearchResult &result);
    void queueRequested(const SearchResult &result);
    void removeRequested(const SearchResult &result);

protected:
    void paintEvent(QPaintEvent *event) override;
    void mousePressEvent(QMouseEvent *event) override;
    void contextMenuEvent(QContextMenuEvent *event) override;
    void mouseDoubleClickEvent(QMouseEvent *event) override;
    void keyPressEvent(QKeyEvent *event) override;
    void resizeEvent(QResizeEvent *event) override;
    void enterEvent(QEnterEvent *event) override;
    void leaveEvent(QEvent *event) override;
    bool eventFilter(QObject *watched, QEvent *event) override;

private:
    SearchResult m_result;
    QLabel *m_cover = nullptr;
    ElidedLabel *m_title = nullptr;
    ElidedLabel *m_subtitle = nullptr;
    QToolButton *m_play = nullptr;
    QVBoxLayout *m_layout = nullptr;
    bool m_hovered = false;
    bool m_playing = false;
};
