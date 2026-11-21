#pragma once

#include <QWidget>

#include "SearchResult.h"

class ElidedLabel;
class QLabel;
class QStackedLayout;
class QToolButton;
class RemoteImageCache;
class SpinnerWidget;
class QEnterEvent;
class QContextMenuEvent;

class StreamItemRow : public QWidget {
    Q_OBJECT

public:
    explicit StreamItemRow(const SearchResult &result,
                           RemoteImageCache *images,
                           QWidget *parent = nullptr,
                           bool large = false,
                           int indent = 0);

    const SearchResult &result() const { return m_result; }

    void setBusy(bool busy);
    void setPlaying(bool playing);
    void setSelected(bool selected);
    void setDownloadBusy(bool busy, int progress = -1);
    void setDownloadProgress(int progress);

signals:
    void playRequested(const SearchResult &result);
    void downloadRequested(const SearchResult &result);
    void queueRequested(const SearchResult &result);
    void openRequested(const SearchResult &result);
    void activated();

protected:
    void paintEvent(QPaintEvent *event) override;
    void mousePressEvent(QMouseEvent *event) override;
    void contextMenuEvent(QContextMenuEvent *event) override;
    void enterEvent(QEnterEvent *event) override;
    void leaveEvent(QEvent *event) override;

private:
    void updatePlayIcon();
    void updateDownloadVisibility();

    SearchResult m_result;
    RemoteImageCache *m_images = nullptr;
    QLabel *m_cover = nullptr;
    ElidedLabel *m_title = nullptr;
    QLabel *m_subtitle = nullptr;
    QLabel *m_duration = nullptr;
    QWidget *m_playHost = nullptr;
    QToolButton *m_playButton = nullptr;
    SpinnerWidget *m_playSpinner = nullptr;
    QStackedLayout *m_playStack = nullptr;
    QToolButton *m_downloadButton = nullptr;
    SpinnerWidget *m_downloadSpinner = nullptr;
    QStackedLayout *m_downloadStack = nullptr;
    bool m_hovered = false;
    bool m_playing = false;
    bool m_busy = false;
    bool m_selected = false;
    bool m_large = false;
};
