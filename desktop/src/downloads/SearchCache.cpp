#include "SearchCache.h"

#include <QCryptographicHash>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QStandardPaths>

namespace {

constexpr int CacheVersion = 5;
constexpr qint64 TtlSeconds = 24 * 60 * 60;

QString g_directory;

QString ensureDirectory() {
    if (g_directory.isEmpty()) {
        const QString base =
            QStandardPaths::writableLocation(QStandardPaths::GenericCacheLocation);
        g_directory = QDir(base.isEmpty() ? QDir::homePath() + QStringLiteral("/.cache")
                                          : base)
                          .filePath(QStringLiteral("OctoBeat/stream-search"));
    }
    QDir().mkpath(g_directory);
    return g_directory;
}

QJsonObject toJson(const SearchResult &result) {
    QJsonObject object;
    object.insert(QStringLiteral("kind"), static_cast<int>(result.kind));
    object.insert(QStringLiteral("id"), result.id);
    object.insert(QStringLiteral("title"), result.title);
    object.insert(QStringLiteral("uploader"), result.uploader);
    object.insert(QStringLiteral("url"), result.url);
    object.insert(QStringLiteral("thumbnail"), result.thumbnail);
    object.insert(QStringLiteral("channelId"), result.channelId);
    object.insert(QStringLiteral("playlistId"), result.playlistId);
    object.insert(QStringLiteral("duration"), result.duration);
    object.insert(QStringLiteral("itemCount"), result.itemCount);
    object.insert(QStringLiteral("popularity"), result.popularity);
    object.insert(QStringLiteral("hasPopularity"), result.hasPopularity);
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
    result.popularity = static_cast<qint64>(
        object.value(QStringLiteral("popularity")).toDouble());
    result.hasPopularity =
        object.value(QStringLiteral("hasPopularity")).toBool();
    result.squareThumbnail =
        object.value(QStringLiteral("squareThumbnail")).toBool();
    return result;
}

} // namespace

namespace SearchCache {

QString directory() {
    return ensureDirectory();
}

void setDirectory(const QString &path) {
    g_directory = path;
    ensureDirectory();
}

QString keyFor(const QString &query, int filter, int limit) {
    const QString seed = QStringLiteral("v%1|%2|%3|%4")
                             .arg(CacheVersion)
                             .arg(query.trimmed().toLower())
                             .arg(filter)
                             .arg(limit);
    return QString::fromLatin1(
        QCryptographicHash::hash(seed.toUtf8(),
                                 QCryptographicHash::Sha1)
            .toHex());
}

bool load(const QString &key, QVector<SearchResult> &results) {
    const QString path = QDir(ensureDirectory())
                             .filePath(key + QStringLiteral(".json"));
    QFileInfo info(path);
    if (!info.isFile()) {
        return false;
    }
    if (info.lastModified().secsTo(QDateTime::currentDateTime()) >
        TtlSeconds) {
        QFile::remove(path);
        return false;
    }
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        return false;
    }
    const QJsonDocument document =
        QJsonDocument::fromJson(file.readAll());
    if (!document.isArray()) {
        return false;
    }
    QVector<SearchResult> loaded;
    for (const QJsonValue &value : document.array()) {
        if (value.isObject()) {
            const SearchResult result = fromJson(value.toObject());
            if (!result.id.isEmpty() && !result.title.isEmpty()) {
                loaded.push_back(result);
            }
        }
    }
    if (loaded.isEmpty()) {
        return false;
    }
    results = loaded;
    return true;
}

void save(const QString &key, const QVector<SearchResult> &results) {
    if (results.isEmpty()) {
        return;
    }
    QJsonArray array;
    for (const SearchResult &result : results) {
        array.push_back(toJson(result));
    }
    QFile file(QDir(ensureDirectory())
                   .filePath(key + QStringLiteral(".json")));
    if (file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        file.write(QJsonDocument(array).toJson(QJsonDocument::Compact));
    }
}

void clear() {
    QDir(ensureDirectory()).removeRecursively();
}

} // namespace SearchCache
