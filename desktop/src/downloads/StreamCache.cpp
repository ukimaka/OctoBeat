#include "StreamCache.h"

#include <QCryptographicHash>
#include <QDir>
#include <QFileInfo>
#include <QStandardPaths>

#include <algorithm>

namespace {

constexpr qint64 MaxCacheBytes = 2LL * 1024 * 1024 * 1024;

const QStringList AudioExtensions = {
    QStringLiteral("opus"), QStringLiteral("ogg"), QStringLiteral("webm"),
    QStringLiteral("m4a"), QStringLiteral("mp3"), QStringLiteral("flac"),
    QStringLiteral("wav"), QStringLiteral("aac")};

} // namespace

namespace StreamCache {

QString directory() {
    const QString base =
        QStandardPaths::writableLocation(QStandardPaths::GenericCacheLocation);
    const QString path =
        QDir(base.isEmpty() ? QDir::homePath() + QStringLiteral("/.cache")
                            : base)
            .filePath(QStringLiteral("OctoBeat/stream-audio"));
    QDir().mkpath(path);
    static bool pruned = false;
    if (!pruned) {
        pruned = true;
        QDir dir(path);
        QFileInfoList files = dir.entryInfoList(QDir::Files, QDir::Time);
        qint64 total = 0;
        for (const QFileInfo &file : files) {
            total += file.size();
        }
        for (auto it = files.crbegin();
             it != files.crend() && total > MaxCacheBytes; ++it) {
            const qint64 size = it->size();
            if (QFile::remove(it->absoluteFilePath())) {
                total -= size;
            }
        }
    }
    return path;
}

QString keyFor(const QString &id, const QString &url) {
    QString key = id;
    if (key.isEmpty()) {
        key = QString::fromLatin1(
            QCryptographicHash::hash(url.toUtf8(), QCryptographicHash::Sha1)
                .toHex());
    }
    for (QChar &ch : key) {
        if (!ch.isLetterOrNumber() && ch != QLatin1Char('-') &&
            ch != QLatin1Char('_')) {
            ch = QLatin1Char('_');
        }
    }
    return key;
}

QString pathFor(const QString &key) {
    if (key.isEmpty()) {
        return {};
    }
    QDir dir(directory());
    const QStringList candidates =
        dir.entryList({key + QStringLiteral(".*")}, QDir::Files, QDir::Time);
    for (const QString &name : candidates) {
        const QString path = dir.filePath(name);
        if (name.endsWith(QStringLiteral(".part")) ||
            !AudioExtensions.contains(QFileInfo(path).suffix().toLower())) {
            continue;
        }
        if (QFileInfo(path).size() > 0) {
            return path;
        }
    }
    return {};
}

void clear() {
    QDir(directory()).removeRecursively();
}

} // namespace StreamCache
