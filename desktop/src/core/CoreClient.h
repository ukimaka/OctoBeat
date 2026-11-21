#pragma once

#include <QString>
#include <QVector>

#include <functional>

#include "octobeat_core.h"

struct Track {
    qint64 id = 0;
    QString filePath;
    QString title;
    QString artist;
    QString album;
    qint64 duration = 0;
    QString coverPath;
    qint64 folderId = 0;
    QString addedAt;
};

struct Folder {
    qint64 id = 0;
    QString name;
};

struct LyricsData {
    QString synced;
    QString plain;
    bool checked = false;
    bool manual = false;
    qint64 offsetMs = 0;
};

struct Playlist {
    qint64 id = 0;
    QString name;
    QString coverPath;
    QString description;
    int isPinned = 0;
    int position = 0;
};

struct ProfileData {
    QString nickname;
    QString avatarPath;
    QString bannerPath;
    QString description;
    qint64 listeningSeconds = 0;
    qint64 tracks = 0;
    qint64 playlistsCount = 0;
    qint64 appAgeDays = 0;
    Track favorite;
    bool hasFavorite = false;
    QVector<Track> topTracks;
    QVector<Playlist> playlists;
};

class CoreClient {
public:
    CoreClient() = default;
    ~CoreClient();

    CoreClient(const CoreClient &) = delete;
    CoreClient &operator=(const CoreClient &) = delete;

    bool open(const QString &dataDir,
              const QString &dbPath,
              const QString &musicDir,
              const QString &cacheDir);

    bool isOpen() const { return m_core != nullptr; }
    QString lastError() const { return m_lastError; }

    QVector<Track> tracks();
    QVector<Playlist> playlists();
    QVector<Folder> folders();
    qint64 createFolder(const QString &name);
    bool moveTrackToFolder(qint64 trackId, qint64 folderId);
    LyricsData trackLyrics(qint64 trackId);
    bool updateTrackLyrics(qint64 trackId,
                           const QString &synced,
                           const QString &plain,
                           bool manual = false);
    bool setLyricsOffset(qint64 trackId, qint64 offsetMs);
    bool deleteTrack(qint64 trackId);
    bool updateTrackMetadata(qint64 trackId,
                             const QString &title,
                             const QString &artist);
    bool setTrackCover(qint64 trackId, const QString &sourcePath);
    ProfileData profile();
    bool logPlay(qint64 trackId);
    bool addListeningTime(qint64 seconds);
    bool setProfileField(const QString &field, const QString &value);
    bool setMusicDir(const QString &path);
    QVector<Track> playlistTracks(qint64 playlistId);
    QString trackPath(qint64 trackId);

    qint64 createPlaylist(const QString &name);
    bool updatePlaylistDescription(qint64 playlistId, const QString &description);
    bool updatePlaylistCover(qint64 playlistId, const QString &coverPath);
    bool deletePlaylist(qint64 playlistId);
    bool clearCovers();
    bool clearAllCache();
    bool addTrackToPlaylist(qint64 playlistId, qint64 trackId);
    bool removeTrackFromPlaylist(qint64 playlistId, qint64 trackId);

    bool scan(const std::function<void(int, int)> &progress = {});

private:
    OctoCore *m_core = nullptr;
    QString m_lastError;
};
