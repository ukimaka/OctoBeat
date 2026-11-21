#pragma once

#include <QString>

// Full-track audio cache for streaming playback. The fast FIFO gives an
// instant start; this cache is downloaded in the background and makes seeks
// instant because the native engine can jump inside a normal local file.
namespace StreamCache {

QString directory();
QString keyFor(const QString &id, const QString &url);
// Returns an existing complete audio file for key, or an empty string.
QString pathFor(const QString &key);
void clear();

} // namespace StreamCache
