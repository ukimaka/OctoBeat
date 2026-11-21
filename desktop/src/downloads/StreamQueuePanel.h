#pragma once

#include <QFrame>
#include <QVector>

#include "SearchResult.h"

class QLabel;
class QScrollArea;
class QVBoxLayout;
class QWidget;

class StreamQueuePanel : public QFrame {
    Q_OBJECT

public:
    explicit StreamQueuePanel(QWidget *parent = nullptr);

    void setQueue(const QVector<SearchResult> &queue);
    void openAt(QWidget *anchor);

signals:
    void playRequested(const SearchResult &result);
    void removeRequested(const SearchResult &result);
    void clearRequested();

private:
    void rebuild();

    QVector<SearchResult> m_queue;
    QLabel *m_title = nullptr;
    QWidget *m_clear = nullptr;
    QScrollArea *m_scroll = nullptr;
    QWidget *m_rows = nullptr;
    QVBoxLayout *m_rowsLayout = nullptr;
    QLabel *m_empty = nullptr;
};
