#pragma once

#include <QAction>
#include <QPoint>
#include <QPair>
#include <QSet>
#include <QVector>
#include <QWidget>

#include "core/CoreClient.h"

class QComboBox;
class QLabel;
class QLineEdit;
class QPushButton;
class QTreeWidgetItem;
class SmoothTreeWidget;
class TrackDelegate;

class LibraryPage : public QWidget {
    Q_OBJECT

public:
    explicit LibraryPage(CoreClient *core, QWidget *parent = nullptr);

    void setTracks(const QVector<Track> &tracks);
    void setStatus(const QString &status);
    void setNextTrack(const Track &track);
    void clearNextTrack();
    void setCurrentPlaying(qint64 trackId);
    QVector<qint64> orderedTrackIds() const;
    void focusSearch();
    void applyTheme();
    void toggleSelectAll();
    bool allTracksSelected() const;

signals:
    void playRequested(qint64 trackId);
    void scanRequested();
    void randomRequested();
    void importFilesRequested();
    void contextMenuRequested(const QPoint &globalPos,
                              qint64 trackId,
                              const QVector<qint64> &selectedIds);
    void removeTrackRequested(qint64 trackId);

protected:
    bool eventFilter(QObject *watched, QEvent *event) override;

private:
    void rebuild();
    void filter();
    void updateSortIndicator();
    void activateItem(QTreeWidgetItem *item);
    void createFolder();
    void syncFoldersToDatabase();
    QTreeWidgetItem *makeTrackItem(const Track &track, int index);
    QTreeWidgetItem *makeFolderItem(const Folder &folder);
    QVector<qint64> collapsedFolders() const;
    QVector<qint64> selectedTrackIds() const;

    CoreClient *m_core = nullptr;
    QLineEdit *m_search = nullptr;
    QAction *m_searchAction = nullptr;
    QLabel *m_filterIcon = nullptr;
    QVector<QPair<QPushButton *, QString>> m_iconButtons;
    QComboBox *m_sort = nullptr;
    QLabel *m_count = nullptr;
    QWidget *m_nextContainer = nullptr;
    QLabel *m_nextCover = nullptr;
    QLabel *m_nextTitle = nullptr;
    QLabel *m_nextArtist = nullptr;
    SmoothTreeWidget *m_tree = nullptr;
    TrackDelegate *m_delegate = nullptr;
    QVector<Track> m_tracks;
    QString m_sortKey = QStringLiteral("added");
    bool m_sortAscending = false;
    QSet<qint64> m_collapsed;
};
