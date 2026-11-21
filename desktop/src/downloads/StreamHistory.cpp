#include "StreamHistory.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSettings>
#include <QSet>

namespace {
constexpr int MaxTracks = 50;
constexpr int MaxArtists = 20;
constexpr int MaxPlaylists = 20;
constexpr int MaxSearches = 150;

QString keyTracks() {
    return QStringLiteral("stream/history/tracks");
}
QString keyArtists() {
    return QStringLiteral("stream/history/artists");
}
QString keyPlaylists() {
    return QStringLiteral("stream/history/playlists");
}
QString keySearches() {
    return QStringLiteral("stream/history/searches");
}

QJsonObject toJson(const SearchResult &result) {
    QJsonObject object;
    object.insert(QStringLiteral("kind"),
                  static_cast<int>(result.kind));
    object.insert(QStringLiteral("id"), result.id);
    object.insert(QStringLiteral("title"), result.title);
    object.insert(QStringLiteral("uploader"), result.uploader);
    object.insert(QStringLiteral("url"), result.url);
    object.insert(QStringLiteral("thumbnail"), result.thumbnail);
    object.insert(QStringLiteral("channelId"), result.channelId);
    object.insert(QStringLiteral("playlistId"), result.playlistId);
    object.insert(QStringLiteral("duration"),
                  static_cast<double>(result.duration));
    object.insert(QStringLiteral("itemCount"), result.itemCount);
    object.insert(QStringLiteral("squareThumbnail"), result.squareThumbnail);
    return object;
}

SearchResult fromJson(const QJsonObject &object) {
    SearchResult result;
    result.kind = static_cast<SearchResult::Kind>(
        object.value(QStringLiteral("kind")).toInt());
    result.id = object.value(QStringLiteral("id")).toString();
    result.title = object.value(QStringLiteral("title")).toString();
    result.uploader = object.value(QStringLiteral("uploader")).toString();
    result.url = object.value(QStringLiteral("url")).toString();
    result.thumbnail = object.value(QStringLiteral("thumbnail")).toString();
    result.channelId = object.value(QStringLiteral("channelId")).toString();
    result.playlistId = object.value(QStringLiteral("playlistId")).toString();
    result.duration = static_cast<qint64>(
        object.value(QStringLiteral("duration")).toDouble());
    result.itemCount = object.value(QStringLiteral("itemCount")).toInt();
    result.squareThumbnail =
        object.value(QStringLiteral("squareThumbnail")).toBool();
    return result;
}

QString identity(const SearchResult &result) {
    switch (result.kind) {
    case SearchResult::Kind::Artist: {
        const QString id = result.channelId.isEmpty() ? result.id
                                                       : result.channelId;
        return QStringLiteral("artist:") + id;
    }
    case SearchResult::Kind::Playlist: {
        const QString id = result.playlistId.isEmpty() ? result.id
                                                        : result.playlistId;
        return QStringLiteral("playlist:") + id;
    }
    case SearchResult::Kind::Track:
        break;
    }
    return QStringLiteral("track:") + result.id;
}

} // namespace

QVector<SearchResult> StreamHistory::load(const QString &key, int limit) {
    QSettings settings(QStringLiteral("MusicPlayer"),
                       QStringLiteral("MusicPlayer"));
    const QByteArray raw =
        settings.value(key).toString().toUtf8();
    if (raw.isEmpty()) {
        return {};
    }
    const QJsonDocument document = QJsonDocument::fromJson(raw);
    if (!document.isArray()) {
        return {};
    }
    QVector<SearchResult> results;
    QSet<QString> seen;
    const QJsonArray array = document.array();
    for (const QJsonValue &value : array) {
        if (!value.isObject()) {
            continue;
        }
        const SearchResult item = fromJson(value.toObject());
        const QString key = identity(item);
        if (seen.contains(key)) {
            continue;
        }
        seen.insert(key);
        results.push_back(item);
        if (limit > 0 && results.size() >= limit) {
            break;
        }
    }
    return results;
}

void StreamHistory::save(const QString &key,
                         const QVector<SearchResult> &items,
                         int) {
    QJsonArray array;
    for (const SearchResult &item : items) {
        array.append(toJson(item));
    }
    QSettings settings(QStringLiteral("MusicPlayer"),
                       QStringLiteral("MusicPlayer"));
    settings.setValue(key,
                      QString::fromUtf8(
                          QJsonDocument(array).toJson(QJsonDocument::Compact)));
}

QVector<SearchResult> StreamHistory::tracks(int limit) {
    return load(keyTracks(), limit);
}

QVector<SearchResult> StreamHistory::artists(int limit) {
    return load(keyArtists(), limit);
}

QVector<SearchResult> StreamHistory::playlists(int limit) {
    return load(keyPlaylists(), limit);
}

QStringList StreamHistory::searches(int limit) {
    QSettings settings(QStringLiteral("MusicPlayer"),
                       QStringLiteral("MusicPlayer"));
    QStringList values = settings.value(keySearches()).toStringList();
    if (limit > 0 && values.size() > limit) {
        values = values.mid(0, limit);
    }
    return values;
}

void StreamHistory::addItem(const QString &key,
                            const SearchResult &result,
                            int maxItems) {
    if (result.id.isEmpty() && result.channelId.isEmpty() &&
        result.playlistId.isEmpty()) {
        return;
    }
    QVector<SearchResult> items = load(key, maxItems);
    const QString id = identity(result);
    for (int i = items.size() - 1; i >= 0; --i) {
        if (identity(items[i]) == id) {
            items.removeAt(i);
        }
    }
    items.prepend(result);
    while (items.size() > maxItems) {
        items.removeLast();
    }
    save(key, items, maxItems);
}

void StreamHistory::addTrack(const SearchResult &result) {
    addItem(keyTracks(), result, MaxTracks);
}

void StreamHistory::addArtist(const SearchResult &result) {
    addItem(keyArtists(), result, MaxArtists);
}

void StreamHistory::addPlaylist(const SearchResult &result) {
    addItem(keyPlaylists(), result, MaxPlaylists);
}

void StreamHistory::removeItem(const QString &key,
                               const SearchResult &result,
                               int maxItems) {
    QVector<SearchResult> items = load(key, maxItems);
    const QString id = identity(result);
    for (int i = items.size() - 1; i >= 0; --i) {
        if (identity(items[i]) == id) {
            items.removeAt(i);
        }
    }
    save(key, items, maxItems);
}

void StreamHistory::removeTrack(const SearchResult &result) {
    removeItem(keyTracks(), result, MaxTracks);
}

void StreamHistory::removeArtist(const SearchResult &result) {
    removeItem(keyArtists(), result, MaxArtists);
}

void StreamHistory::removePlaylist(const SearchResult &result) {
    removeItem(keyPlaylists(), result, MaxPlaylists);
}

void StreamHistory::addSearch(const QString &query) {
    const QString trimmed = query.trimmed();
    if (trimmed.isEmpty()) {
        return;
    }
    QSettings settings(QStringLiteral("MusicPlayer"),
                       QStringLiteral("MusicPlayer"));
    QStringList values = settings.value(keySearches()).toStringList();
    values.removeAll(trimmed);
    values.prepend(trimmed);
    while (values.size() > MaxSearches) {
        values.removeLast();
    }
    settings.setValue(keySearches(), values);
}

void StreamHistory::clear() {
    QSettings settings(QStringLiteral("MusicPlayer"),
                       QStringLiteral("MusicPlayer"));
    settings.remove(QStringLiteral("stream/history"));
}
