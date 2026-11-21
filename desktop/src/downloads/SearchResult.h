#pragma once

#include <QString>

struct SearchResult {
    enum class Kind { Track, Artist, Playlist };

    Kind kind = Kind::Track;
    QString id;
    QString title;
    QString uploader;
    QString url;
    QString thumbnail;
    QString channelId;
    QString playlistId;
    qint64 duration = 0;
    int itemCount = 0;
    qint64 popularity = 0;
    bool hasPopularity = false;
    bool squareThumbnail = false;
};
