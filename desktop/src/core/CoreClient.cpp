#include "CoreClient.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

#include <utility>

namespace {

QString takeString(char *value) {
    if (!value) {
        return {};
    }
    QString out = QString::fromUtf8(value);
    octobeat_string_free(value);
    return out;
}

QString optionalString(const QJsonObject &object, const char *key) {
    const QJsonValue value = object.value(QLatin1String(key));
    return value.isString() ? value.toString() : QString();
}

Track trackFromJson(const QJsonObject &object) {
    Track track;
    track.id = static_cast<qint64>(object.value("id").toDouble());
    track.filePath = optionalString(object, "file_path");
    track.title = optionalString(object, "title");
    track.artist = optionalString(object, "artist");
    track.album = optionalString(object, "album");
    track.duration = static_cast<qint64>(object.value("duration").toDouble());
    track.coverPath = optionalString(object, "cover_path");
    track.folderId = static_cast<qint64>(object.value("folder_id").toDouble());
    track.addedAt = optionalString(object, "added_at");
    return track;
}

struct ScanContext {
    const std::function<void(int, int)> *progress = nullptr;
};

extern "C" void scanProgress(int done, int total, void *userData) {
    auto *context = static_cast<ScanContext *>(userData);
    if (context && context->progress && *context->progress) {
        (*context->progress)(done, total);
    }
}

} // namespace

CoreClient::~CoreClient() {
    if (m_core) {
        octobeat_core_free(m_core);
        m_core = nullptr;
    }
}

bool CoreClient::open(const QString &dataDir,
                      const QString &dbPath,
                      const QString &musicDir,
                      const QString &cacheDir) {
    m_lastError.clear();
    if (m_core) {
        octobeat_core_free(m_core);
        m_core = nullptr;
    }
    m_core = octobeat_core_new(dataDir.toUtf8().constData(),
                               dbPath.toUtf8().constData(),
                               musicDir.toUtf8().constData(),
                               cacheDir.toUtf8().constData());
    if (!m_core) {
        m_lastError = QStringLiteral("Rust core initialisation failed");
    }
    return m_core != nullptr;
}

QVector<Track> CoreClient::tracks() {
    QVector<Track> result;
    if (!m_core) {
        return result;
    }
    const QString json = takeString(octobeat_core_tracks_json(m_core));
    if (json.isEmpty()) {
        return result;
    }
    const QJsonDocument document = QJsonDocument::fromJson(json.toUtf8());
    if (!document.isArray()) {
        return result;
    }
    const QJsonArray array = document.array();
    result.reserve(array.size());
    for (const QJsonValue &value : array) {
        if (value.isObject()) {
            result.push_back(trackFromJson(value.toObject()));
        }
    }
    return result;
}

QVector<Playlist> CoreClient::playlists() {
    QVector<Playlist> result;
    if (!m_core) {
        return result;
    }
    const QString json = takeString(octobeat_core_playlists_json(m_core));
    if (json.isEmpty()) {
        return result;
    }
    const QJsonDocument document = QJsonDocument::fromJson(json.toUtf8());
    if (!document.isArray()) {
        return result;
    }
    const QJsonArray array = document.array();
    result.reserve(array.size());
    for (const QJsonValue &value : array) {
        if (!value.isObject()) {
            continue;
        }
        const QJsonObject object = value.toObject();
        Playlist playlist;
        playlist.id = static_cast<qint64>(object.value("id").toDouble());
        playlist.name = optionalString(object, "name");
        playlist.coverPath = optionalString(object, "cover_path");
        playlist.description = optionalString(object, "description");
        playlist.isPinned = object.value("is_pinned").toInt();
        playlist.position = object.value("position").toInt();
        result.push_back(playlist);
    }
    return result;
}

QVector<Folder> CoreClient::folders() {
    QVector<Folder> result;
    if (!m_core) {
        return result;
    }
    const QString json = takeString(octobeat_core_folders_json(m_core));
    if (json.isEmpty()) {
        return result;
    }
    const QJsonDocument document = QJsonDocument::fromJson(json.toUtf8());
    if (!document.isArray()) {
        return result;
    }
    for (const QJsonValue &value : document.array()) {
        if (!value.isObject()) {
            continue;
        }
        const QJsonObject object = value.toObject();
        Folder folder;
        folder.id = static_cast<qint64>(object.value("id").toDouble());
        folder.name = optionalString(object, "name");
        result.push_back(folder);
    }
    return result;
}

qint64 CoreClient::createFolder(const QString &name) {
    if (!m_core) {
        return 0;
    }
    return octobeat_core_create_folder(m_core, name.toUtf8().constData());
}

bool CoreClient::renameFolder(qint64 folderId, const QString &name) {
    return m_core &&
           octobeat_core_rename_folder(m_core, folderId,
                                       name.toUtf8().constData()) == 0;
}

bool CoreClient::deleteFolder(qint64 folderId) {
    return m_core && octobeat_core_delete_folder(m_core, folderId) == 0;
}

bool CoreClient::moveTrackToFolder(qint64 trackId, qint64 folderId) {
    return m_core &&
           octobeat_core_move_track_to_folder(m_core, trackId, folderId) == 0;
}

LyricsData CoreClient::trackLyrics(qint64 trackId) {
    LyricsData data;
    if (!m_core) {
        return data;
    }
    const QString json =
        takeString(octobeat_core_track_lyrics_json(m_core, trackId));
    if (json.isEmpty()) {
        return data;
    }
    const QJsonDocument document = QJsonDocument::fromJson(json.toUtf8());
    if (!document.isObject()) {
        return data;
    }
    const QJsonObject object = document.object();
    data.synced = optionalString(object, "synced");
    data.plain = optionalString(object, "plain");
    data.checked = object.value("checked").toBool();
    data.manual = object.value("manual").toBool();
    data.offsetMs = static_cast<qint64>(
        object.value("offset_ms").toDouble());
    return data;
}

bool CoreClient::updateTrackLyrics(qint64 trackId,
                                   const QString &synced,
                                   const QString &plain,
                                   bool manual) {
    return m_core &&
           octobeat_core_update_track_lyrics(m_core, trackId,
                                             synced.toUtf8().constData(),
                                             plain.toUtf8().constData(),
                                             manual ? 1 : 0) == 0;
}

bool CoreClient::setLyricsOffset(qint64 trackId, qint64 offsetMs) {
    return m_core &&
           octobeat_core_set_lyrics_offset(m_core, trackId, offsetMs) == 0;
}

bool CoreClient::deleteTrack(qint64 trackId) {
    return m_core && octobeat_core_delete_track(m_core, trackId) == 0;
}

bool CoreClient::updateTrackMetadata(qint64 trackId,
                                     const QString &title,
                                     const QString &artist) {
    return m_core &&
           octobeat_core_update_track_metadata(m_core, trackId,
                                               title.toUtf8().constData(),
                                               artist.toUtf8().constData()) == 0;
}

bool CoreClient::setTrackCover(qint64 trackId, const QString &sourcePath) {
    return m_core &&
           octobeat_core_set_track_cover(m_core, trackId,
                                         sourcePath.toUtf8().constData()) == 0;
}

ProfileData CoreClient::profile() {
    ProfileData data;
    if (!m_core) {
        return data;
    }
    const QString json = takeString(octobeat_core_profile_json(m_core));
    if (json.isEmpty()) {
        return data;
    }
    const QJsonDocument document = QJsonDocument::fromJson(json.toUtf8());
    if (!document.isObject()) {
        return data;
    }
    const QJsonObject root = document.object();
    const QJsonObject profileObject = root.value("profile").toObject();
    data.nickname = optionalString(profileObject, "nickname");
    data.avatarPath = optionalString(profileObject, "avatar_path");
    data.bannerPath = optionalString(profileObject, "banner_path");
    data.description = optionalString(profileObject, "description");
    data.listeningSeconds = static_cast<qint64>(
        profileObject.value("listening_seconds").toDouble());
    data.tracks = static_cast<qint64>(root.value("tracks").toDouble());
    data.playlistsCount = static_cast<qint64>(
        root.value("playlists_count").toDouble());
    data.appAgeDays = static_cast<qint64>(
        root.value("app_age_days").toDouble());
    if (root.value("favorite").isObject()) {
        data.favorite = trackFromJson(root.value("favorite").toObject());
        data.hasFavorite = true;
    }
    for (const QJsonValue &value : root.value("top_tracks").toArray()) {
        if (value.isObject()) {
            data.topTracks.push_back(trackFromJson(
                value.toObject().value("track").toObject()));
        }
    }
    for (const QJsonValue &value : root.value("playlists").toArray()) {
        if (!value.isObject()) {
            continue;
        }
        const QJsonObject object = value.toObject();
        Playlist playlist;
        playlist.id = static_cast<qint64>(object.value("id").toDouble());
        playlist.name = optionalString(object, "name");
        playlist.coverPath = optionalString(object, "cover_path");
        playlist.description = optionalString(object, "description");
        data.playlists.push_back(playlist);
    }
    return data;
}

bool CoreClient::logPlay(qint64 trackId) {
    return m_core && octobeat_core_log_play(m_core, trackId) == 0;
}

bool CoreClient::addListeningTime(qint64 seconds) {
    return m_core && octobeat_core_add_listening_time(m_core, seconds) == 0;
}

bool CoreClient::setProfileField(const QString &field, const QString &value) {
    return m_core &&
           octobeat_core_set_profile_field(m_core,
                                           field.toUtf8().constData(),
                                           value.toUtf8().constData()) == 0;
}

bool CoreClient::setMusicDir(const QString &path) {
    return m_core &&
           octobeat_core_set_music_dir(m_core, path.toUtf8().constData()) == 0;
}

QVector<Track> CoreClient::playlistTracks(qint64 playlistId) {
    QVector<Track> result;
    if (!m_core) {
        return result;
    }
    const QString json = takeString(
        octobeat_core_playlist_tracks_json(m_core, playlistId));
    if (json.isEmpty()) {
        return result;
    }
    const QJsonDocument document = QJsonDocument::fromJson(json.toUtf8());
    if (!document.isArray()) {
        return result;
    }
    const QJsonArray array = document.array();
    result.reserve(array.size());
    for (const QJsonValue &value : array) {
        if (value.isObject()) {
            result.push_back(trackFromJson(value.toObject()));
        }
    }
    return result;
}

qint64 CoreClient::createPlaylist(const QString &name) {
    if (!m_core) {
        return 0;
    }
    return octobeat_core_create_playlist(m_core, name.toUtf8().constData());
}

bool CoreClient::updatePlaylistDescription(qint64 playlistId, const QString &description) {
    return m_core &&
           octobeat_core_update_playlist_description(
               m_core, playlistId, description.toUtf8().constData()) == 0;
}

bool CoreClient::updatePlaylistCover(qint64 playlistId, const QString &coverPath) {
    return m_core && octobeat_core_update_playlist_cover(
                         m_core, playlistId, coverPath.toUtf8().constData()) == 0;
}

bool CoreClient::deletePlaylist(qint64 playlistId) {
    return m_core && octobeat_core_delete_playlist(m_core, playlistId) == 0;
}

bool CoreClient::clearCovers() {
    return m_core && octobeat_core_clear_covers(m_core) == 0;
}

bool CoreClient::clearAllCache() {
    return m_core && octobeat_core_clear_all_cache(m_core) == 0;
}

bool CoreClient::addTrackToPlaylist(qint64 playlistId, qint64 trackId) {
    return m_core &&
           octobeat_core_add_track_to_playlist(m_core, playlistId, trackId) == 0;
}

bool CoreClient::removeTrackFromPlaylist(qint64 playlistId, qint64 trackId) {
    return m_core &&
           octobeat_core_remove_track_from_playlist(m_core, playlistId, trackId) == 0;
}

QString CoreClient::trackPath(qint64 trackId) {
    if (!m_core) {
        return {};
    }
    return takeString(octobeat_core_track_path(m_core, trackId));
}

bool CoreClient::scan(const std::function<void(int, int)> &progress) {
    if (!m_core) {
        return false;
    }
    ScanContext context;
    context.progress = &progress;
    const bool ok =
        octobeat_core_scan(m_core, scanProgress, &context) == 0;
    if (!ok) {
        m_lastError = takeString(octobeat_core_last_error(m_core));
    } else {
        m_lastError.clear();
    }
    return ok;
}

void CoreClient::cancelScan() {
    if (m_core) {
        octobeat_core_cancel_scan(m_core);
    }
}
