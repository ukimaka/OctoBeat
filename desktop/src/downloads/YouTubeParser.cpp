#include "YouTubeParser.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QRegularExpression>
#include <QSet>

namespace {

qint64 parseCompactCount(const QString &text, bool *hasValue = nullptr) {
    static const QRegularExpression re(
        QStringLiteral("(\\d[\\d.,]*)\\s*([KMB])?"),
        QRegularExpression::CaseInsensitiveOption);
    const auto match = re.match(text);
    if (!match.hasMatch()) {
        if (hasValue) {
            *hasValue = false;
        }
        return 0;
    }
    QString number = match.captured(1);
    number.remove(QLatin1Char(','));
    double value = number.toDouble();
    const QString suffix = match.captured(2).toUpper();
    if (suffix == QStringLiteral("K")) {
        value *= 1000.0;
    } else if (suffix == QStringLiteral("M")) {
        value *= 1000000.0;
    } else if (suffix == QStringLiteral("B")) {
        value *= 1000000000.0;
    }
    if (hasValue) {
        *hasValue = true;
    }
    return static_cast<qint64>(value);
}

QString absoluteUrl(QString url) {
    if (url.startsWith(QStringLiteral("//"))) {
        return QStringLiteral("https:") + url;
    }
    if (url.startsWith(QLatin1Char('/'))) {
        return QStringLiteral("https://www.youtube.com") + url;
    }
    return url;
}

QString runsText(const QJsonObject &object) {
    if (object.contains(QStringLiteral("simpleText"))) {
        return object.value(QStringLiteral("simpleText")).toString();
    }
    QString text;
    const QJsonArray runs = object.value(QStringLiteral("runs")).toArray();
    for (const QJsonValue &run : runs) {
        text += run.toObject().value(QStringLiteral("text")).toString();
    }
    return text;
}

QString thumbnailUrl(const QJsonObject &object) {
    const QJsonArray thumbnails =
        object.value(QStringLiteral("thumbnails")).toArray();
    QString url;
    for (const QJsonValue &value : thumbnails) {
        const QString candidate =
            value.toObject().value(QStringLiteral("url")).toString();
        if (!candidate.isEmpty()) {
            url = candidate;
        }
    }
    return absoluteUrl(url);
}

qint64 parseDuration(const QString &text) {
    const QString trimmed = text.trimmed();
    if (trimmed.isEmpty() ||
        trimmed.compare(QStringLiteral("LIVE"), Qt::CaseInsensitive) == 0) {
        return 0;
    }
    const QStringList parts = trimmed.split(QLatin1Char(':'));
    if (parts.size() < 2 || parts.size() > 3) {
        return 0;
    }
    qint64 seconds = 0;
    for (const QString &part : parts) {
        bool ok = false;
        const qint64 value = part.toLongLong(&ok);
        if (!ok) {
            return 0;
        }
        seconds = seconds * 60 + value;
    }
    return seconds;
}

void findBrowseId(const QJsonValue &value, QString &id) {
    if (!id.isEmpty()) {
        return;
    }
    if (value.isObject()) {
        const QJsonObject object = value.toObject();
        const QJsonObject browse =
            object.value(QStringLiteral("browseEndpoint")).toObject();
        if (!browse.isEmpty()) {
            id = browse.value(QStringLiteral("browseId")).toString();
            if (!id.isEmpty()) {
                return;
            }
        }
        for (auto it = object.begin(); it != object.end(); ++it) {
            findBrowseId(it.value(), id);
        }
    } else if (value.isArray()) {
        for (const QJsonValue &entry : value.toArray()) {
            findBrowseId(entry, id);
        }
    }
}

SearchResult parseVideoRenderer(const QJsonObject &object) {
    SearchResult result;
    result.kind = SearchResult::Kind::Track;
    result.id = object.value(QStringLiteral("videoId")).toString();
    if (result.id.isEmpty()) {
        return result;
    }
    result.title = runsText(object.value(QStringLiteral("title")).toObject());
    const QJsonObject owner =
        object.value(QStringLiteral("ownerText")).toObject();
    result.uploader = runsText(owner);
    if (result.uploader.isEmpty()) {
        result.uploader = runsText(
            object.value(QStringLiteral("longBylineText")).toObject());
    }
    if (result.uploader.isEmpty()) {
        result.uploader = runsText(
            object.value(QStringLiteral("shortBylineText")).toObject());
    }
    findBrowseId(owner, result.channelId);
    if (result.channelId.isEmpty()) {
        findBrowseId(object.value(QStringLiteral("longBylineText")),
                     result.channelId);
    }
    result.duration = parseDuration(
        object.value(QStringLiteral("lengthText")).toObject().value(
            QStringLiteral("simpleText")).toString());
    result.thumbnail =
        thumbnailUrl(object.value(QStringLiteral("thumbnail")).toObject());
    if (result.thumbnail.isEmpty()) {
        result.thumbnail = QStringLiteral("https://i.ytimg.com/vi/") +
                           result.id + QStringLiteral("/mqdefault.jpg");
    }
    result.url = QStringLiteral("https://www.youtube.com/watch?v=") + result.id;
    const QString views =
        object.value(QStringLiteral("viewCountText"))
            .toObject()
            .value(QStringLiteral("simpleText"))
            .toString();
    if (views.contains(QStringLiteral("view"), Qt::CaseInsensitive)) {
        result.popularity = parseCompactCount(views, &result.hasPopularity);
    }
    return result;
}

SearchResult parseChannelRenderer(const QJsonObject &object) {
    SearchResult result;
    result.kind = SearchResult::Kind::Artist;
    result.id = object.value(QStringLiteral("channelId")).toString();
    result.channelId = result.id;
    if (result.id.isEmpty()) {
        return result;
    }
    result.title = runsText(object.value(QStringLiteral("title")).toObject());
    result.thumbnail =
        thumbnailUrl(object.value(QStringLiteral("thumbnail")).toObject());
    const QString subscribers =
        object.value(QStringLiteral("subscriberCountText"))
            .toObject()
            .value(QStringLiteral("simpleText"))
            .toString();
    result.uploader = subscribers;
    if (result.uploader.isEmpty()) {
        result.uploader =
            object.value(QStringLiteral("videoCountText"))
                .toObject()
                .value(QStringLiteral("simpleText"))
                .toString();
    }
    if (subscribers.contains(QStringLiteral("subscriber"),
                             Qt::CaseInsensitive)) {
        result.popularity =
            parseCompactCount(subscribers, &result.hasPopularity);
    }
    result.url = QStringLiteral("https://www.youtube.com/channel/") +
                 result.id + QStringLiteral("/videos");
    return result;
}

SearchResult parseLockup(const QJsonObject &object) {
    SearchResult result;
    const QString contentType =
        object.value(QStringLiteral("contentType")).toString();
    result.id = object.value(QStringLiteral("contentId")).toString();
    if (result.id.isEmpty()) {
        return result;
    }
    if (contentType.contains(QStringLiteral("PLAYLIST")) ||
        contentType.contains(QStringLiteral("ALBUM"))) {
        result.kind = SearchResult::Kind::Playlist;
        result.squareThumbnail =
            contentType.contains(QStringLiteral("ALBUM"));
        result.playlistId = result.id;
        result.url = QStringLiteral("https://www.youtube.com/playlist?list=") +
                     result.id;
    } else if (contentType.contains(QStringLiteral("VIDEO")) ||
               result.id.size() == 11) {
        result.kind = SearchResult::Kind::Track;
        result.url = QStringLiteral("https://www.youtube.com/watch?v=") +
                     result.id;
    } else {
        return result;
    }

    const QJsonObject metadata =
        object.value(QStringLiteral("metadata"))
            .toObject()
            .value(QStringLiteral("lockupMetadataViewModel"))
            .toObject();
    result.title = metadata.value(QStringLiteral("title"))
                       .toObject()
                       .value(QStringLiteral("content"))
                       .toString();

    const QJsonArray rows = metadata.value(QStringLiteral("metadata"))
                                .toObject()
                                .value(QStringLiteral("contentMetadataViewModel"))
                                .toObject()
                                .value(QStringLiteral("metadataRows"))
                                .toArray();
    if (!rows.isEmpty()) {
        const QJsonArray parts =
            rows.first()
                .toObject()
                .value(QStringLiteral("metadataParts"))
                .toArray();
        if (!parts.isEmpty()) {
            result.uploader =
                parts.first()
                    .toObject()
                    .value(QStringLiteral("text"))
                    .toObject()
                    .value(QStringLiteral("content"))
                    .toString();
            if (result.uploader.isEmpty()) {
                result.uploader =
                    parts.first()
                        .toObject()
                        .value(QStringLiteral("avatarStack"))
                        .toObject()
                        .value(QStringLiteral("avatarStackViewModel"))
                        .toObject()
                        .value(QStringLiteral("text"))
                        .toObject()
                        .value(QStringLiteral("content"))
                        .toString();
            }
            findBrowseId(parts.first(), result.channelId);
        }
        const QRegularExpression countRe(
            QStringLiteral("(\\d[\\d,.]*)\\s+videos?"),
            QRegularExpression::CaseInsensitiveOption);
        for (const QJsonValue &row : rows) {
            for (const QJsonValue &part :
                 row.toObject().value(QStringLiteral("metadataParts")).toArray()) {
                const QString text = part.toObject()
                                         .value(QStringLiteral("text"))
                                         .toObject()
                                         .value(QStringLiteral("content"))
                                         .toString();
                const auto match = countRe.match(text);
                if (match.hasMatch()) {
                    QString count = match.captured(1);
                    count.remove(QLatin1Char(','));
                    result.itemCount = count.toInt();
                }
            }
        }
    }

    const QJsonObject contentImage =
        object.value(QStringLiteral("contentImage")).toObject();
    QJsonObject thumbnail =
        contentImage.value(QStringLiteral("thumbnailViewModel")).toObject();
    if (thumbnail.isEmpty()) {
        thumbnail = contentImage
                        .value(QStringLiteral("collectionThumbnailViewModel"))
                        .toObject()
                        .value(QStringLiteral("primaryThumbnail"))
                        .toObject()
                        .value(QStringLiteral("thumbnailViewModel"))
                        .toObject();
    }
    const QJsonArray sources =
        thumbnail.value(QStringLiteral("image")).toObject().value(
            QStringLiteral("sources")).toArray();
    for (const QJsonValue &value : sources) {
        const QString candidate =
            value.toObject().value(QStringLiteral("url")).toString();
        if (!candidate.isEmpty()) {
            result.thumbnail = absoluteUrl(candidate);
        }
    }
    if (result.thumbnail.isEmpty() && result.kind == SearchResult::Kind::Track) {
        result.thumbnail = QStringLiteral("https://i.ytimg.com/vi/") +
                           result.id + QStringLiteral("/mqdefault.jpg");
    }

    const QJsonArray overlays =
        thumbnail.value(QStringLiteral("overlays")).toArray();
    for (const QJsonValue &overlay : overlays) {
        const QJsonArray badges =
            overlay.toObject()
                .value(QStringLiteral("thumbnailBottomOverlayViewModel"))
                .toObject()
                .value(QStringLiteral("badges"))
                .toArray();
        for (const QJsonValue &badge : badges) {
            const QString text =
                badge.toObject()
                    .value(QStringLiteral("thumbnailBadgeViewModel"))
                    .toObject()
                    .value(QStringLiteral("text"))
                    .toString();
            if (text.contains(QLatin1Char(':'))) {
                result.duration = parseDuration(text);
            } else if (result.kind == SearchResult::Kind::Playlist) {
                const QRegularExpression numberRe(QStringLiteral("(\\d+)"));
                const auto match = numberRe.match(text);
                if (match.hasMatch()) {
                    result.itemCount = match.captured(1).toInt();
                }
            }
        }
    }
    return result;
}

void collect(const QJsonValue &value,
             QVector<SearchResult> &results,
             QSet<QString> &seen) {
    if (value.isObject()) {
        const QJsonObject object = value.toObject();
        const auto add = [&](SearchResult result) {
            if (result.title.isEmpty() || result.id.isEmpty()) {
                return;
            }
            const QString key = QString::number(static_cast<int>(result.kind)) +
                                QLatin1Char(':') + result.id;
            if (seen.contains(key)) {
                return;
            }
            seen.insert(key);
            results.push_back(result);
        };
        if (object.contains(QStringLiteral("videoRenderer"))) {
            add(parseVideoRenderer(
                object.value(QStringLiteral("videoRenderer")).toObject()));
        }
        if (object.contains(QStringLiteral("channelRenderer"))) {
            add(parseChannelRenderer(
                object.value(QStringLiteral("channelRenderer")).toObject()));
        }
        if (object.contains(QStringLiteral("lockupViewModel"))) {
            add(parseLockup(
                object.value(QStringLiteral("lockupViewModel")).toObject()));
        }
        for (auto it = object.begin(); it != object.end(); ++it) {
            collect(it.value(), results, seen);
        }
    } else if (value.isArray()) {
        for (const QJsonValue &entry : value.toArray()) {
            collect(entry, results, seen);
        }
    }
}

QString decodeJsString(const QString &input) {
    QString output;
    output.reserve(input.size());
    for (int i = 0; i < input.size(); ++i) {
        const QChar ch = input.at(i);
        if (ch != QLatin1Char('\\') || i + 1 >= input.size()) {
            output.append(ch);
            continue;
        }
        const QChar next = input.at(i + 1);
        if (next == QLatin1Char('x') && i + 3 < input.size()) {
            bool ok = false;
            const ushort value =
                input.mid(i + 2, 2).toUShort(&ok, 16);
            if (ok) {
                output.append(QChar(value));
                i += 3;
                continue;
            }
        }
        if (next == QLatin1Char('u') && i + 5 < input.size()) {
            bool ok = false;
            const ushort value =
                input.mid(i + 2, 4).toUShort(&ok, 16);
            if (ok) {
                output.append(QChar(value));
                i += 5;
                continue;
            }
        }
        const QChar mapped =
            next == QLatin1Char('n')   ? QLatin1Char('\n')
            : next == QLatin1Char('r') ? QLatin1Char('\r')
            : next == QLatin1Char('t') ? QLatin1Char('\t')
            : next == QLatin1Char('\\') ? QLatin1Char('\\')
            : next == QLatin1Char('\'') ? QLatin1Char('\'')
            : next == QLatin1Char('"') ? QLatin1Char('"')
                                       : next;
        output.append(mapped);
        ++i;
    }
    return output;
}

QString extractMusicSearchData(const QString &html) {
    const QString marker = QStringLiteral("path: '\\/search'");
    const int pathPos = html.indexOf(marker);
    if (pathPos < 0) {
        return {};
    }
    const int dataPos = html.indexOf(QStringLiteral("data: '"), pathPos);
    if (dataPos < 0) {
        return {};
    }
    const int start = dataPos + 7;
    QString raw;
    for (int i = start; i < html.size(); ++i) {
        const QChar ch = html.at(i);
        if (ch == QLatin1Char('\\') && i + 1 < html.size()) {
            raw.append(ch);
            raw.append(html.at(++i));
            continue;
        }
        if (ch == QLatin1Char('\'')) {
            break;
        }
        raw.append(ch);
    }
    return decodeJsString(raw);
}

QStringList musicTexts(const QJsonObject &object) {
    QStringList texts;
    for (const QJsonValue &column :
         object.value(QStringLiteral("flexColumns")).toArray()) {
        const QJsonObject text = column.toObject()
                                     .value(QStringLiteral("musicResponsiveListItemFlexColumnRenderer"))
                                     .toObject()
                                     .value(QStringLiteral("text"))
                                     .toObject();
        texts.push_back(runsText(text));
    }
    for (const QJsonValue &column :
         object.value(QStringLiteral("fixedColumns")).toArray()) {
        const QJsonObject text = column.toObject()
                                     .value(QStringLiteral("musicResponsiveListItemFixedColumnRenderer"))
                                     .toObject()
                                     .value(QStringLiteral("text"))
                                     .toObject();
        const QString value = runsText(text);
        if (!value.isEmpty()) {
            texts.push_back(value);
        }
    }
    return texts;
}

QString findFirstString(const QJsonValue &value, const QString &key) {
    if (value.isObject()) {
        const QJsonObject object = value.toObject();
        const QJsonValue direct = object.value(key);
        if (direct.isString() && !direct.toString().isEmpty()) {
            return direct.toString();
        }
        for (auto it = object.begin(); it != object.end(); ++it) {
            const QString found = findFirstString(it.value(), key);
            if (!found.isEmpty()) {
                return found;
            }
        }
    } else if (value.isArray()) {
        for (const QJsonValue &entry : value.toArray()) {
            const QString found = findFirstString(entry, key);
            if (!found.isEmpty()) {
                return found;
            }
        }
    }
    return {};
}

QString findChannelId(const QJsonValue &value) {
    if (value.isObject()) {
        const QJsonObject object = value.toObject();
        const QString browse =
            object.value(QStringLiteral("browseEndpoint"))
                .toObject()
                .value(QStringLiteral("browseId"))
                .toString();
        if (browse.startsWith(QStringLiteral("UC"))) {
            return browse;
        }
        for (auto it = object.begin(); it != object.end(); ++it) {
            const QString found = findChannelId(it.value());
            if (!found.isEmpty()) {
                return found;
            }
        }
    } else if (value.isArray()) {
        for (const QJsonValue &entry : value.toArray()) {
            const QString found = findChannelId(entry);
            if (!found.isEmpty()) {
                return found;
            }
        }
    }
    return {};
}

QString musicThumbnail(const QJsonObject &object) {
    const QJsonObject thumbnail =
        object.value(QStringLiteral("thumbnail"))
            .toObject()
            .value(QStringLiteral("musicThumbnailRenderer"))
            .toObject()
            .value(QStringLiteral("thumbnail"))
            .toObject();
    return thumbnailUrl(thumbnail);
}

QString findPlayLabel(const QJsonValue &value) {
    if (value.isObject()) {
        const QJsonObject object = value.toObject();
        const QJsonObject data =
            object.value(QStringLiteral("accessibilityPlayData")).toObject();
        const QString label =
            data.value(QStringLiteral("accessibilityData"))
                .toObject()
                .value(QStringLiteral("label"))
                .toString();
        if (!label.isEmpty()) {
            return label;
        }
        for (auto it = object.begin(); it != object.end(); ++it) {
            const QString found = findPlayLabel(it.value());
            if (!found.isEmpty()) {
                return found;
            }
        }
    } else if (value.isArray()) {
        for (const QJsonValue &entry : value.toArray()) {
            const QString found = findPlayLabel(entry);
            if (!found.isEmpty()) {
                return found;
            }
        }
    }
    return {};
}

QString cleanArtistName(QString name) {
    name = name.trimmed();
    if (name.endsWith(QStringLiteral(" - Topic"),
                      Qt::CaseInsensitive)) {
        name.chop(8);
    }
    return name.trimmed();
}

SearchResult parseMusicItem(const QJsonObject &object) {
    SearchResult result;
    const QStringList texts = musicTexts(object);
    if (texts.isEmpty()) {
        return result;
    }
    QString type;
    int typeIndex = -1;
    for (int i = 1; i < texts.size(); ++i) {
        const QString first = texts[i].section(QStringLiteral(" • "), 0, 0);
        if (first == QStringLiteral("Song") || first == QStringLiteral("Video") ||
            first == QStringLiteral("Artist") ||
            first == QStringLiteral("Album") ||
            first == QStringLiteral("Single") ||
            first == QStringLiteral("EP") ||
            first == QStringLiteral("Playlist") ||
            first == QStringLiteral("Podcast") ||
            first == QStringLiteral("Episode") ||
            first == QStringLiteral("Profile")) {
            type = first;
            typeIndex = i;
            break;
        }
    }
    if (type.isEmpty() || type == QStringLiteral("Podcast") ||
        type == QStringLiteral("Episode") ||
        type == QStringLiteral("Profile")) {
        return result;
    }

    result.title = texts.first().trimmed();
    result.squareThumbnail = true;
    result.thumbnail = musicThumbnail(object);
    result.channelId = findChannelId(object);

    for (const QString &text : texts) {
        const QString lower = text.toLower();
        if (type == QStringLiteral("Song") ||
            type == QStringLiteral("Video") ||
            type == QStringLiteral("Album") ||
            type == QStringLiteral("Single") ||
            type == QStringLiteral("EP")) {
            if (lower.contains(QStringLiteral("plays")) ||
                lower.contains(QStringLiteral("views"))) {
                result.popularity =
                    parseCompactCount(text, &result.hasPopularity);
                if (result.hasPopularity) {
                    break;
                }
            }
        } else if (type == QStringLiteral("Artist")) {
            if (lower.contains(QStringLiteral("subscriber")) ||
                lower.contains(QStringLiteral("monthly audience")) ||
                lower.contains(QStringLiteral("audience"))) {
                result.popularity =
                    parseCompactCount(text, &result.hasPopularity);
                if (result.hasPopularity) {
                    break;
                }
            }
        }
    }

    const QString typeLine = typeIndex >= 0 ? texts[typeIndex] : QString();
    const QStringList parts = typeLine.split(QStringLiteral(" • "));
    if (type == QStringLiteral("Song") || type == QStringLiteral("Video")) {
        result.kind = SearchResult::Kind::Track;
        result.id = findFirstString(object, QStringLiteral("videoId"));
        if (result.id.isEmpty()) {
            return result;
        }
        result.url = QStringLiteral("https://www.youtube.com/watch?v=") +
                     result.id;
        const QString label = findPlayLabel(object);
        if (label.startsWith(QStringLiteral("Play "))) {
            const QString played = label.mid(5);
            const int split = played.lastIndexOf(QStringLiteral(" - "));
            if (split > 0) {
                result.uploader =
                    cleanArtistName(played.mid(split + 3));
            }
        }
        if (result.uploader.isEmpty() && parts.size() > 1) {
            for (int i = 1; i < parts.size(); ++i) {
                const QString part = parts[i].trimmed();
                if (!part.contains(QLatin1Char(':')) &&
                    !part.endsWith(QStringLiteral(" plays"))) {
                    result.uploader = part;
                    break;
                }
            }
        }
        const QRegularExpression durationRe(
            QStringLiteral("(\\d{1,3}:\\d{2}(?::\\d{2})?)"));
        for (const QString &text : texts) {
            const auto match = durationRe.match(text);
            if (match.hasMatch()) {
                result.duration = parseDuration(match.captured(1));
                break;
            }
        }
        return result;
    }

    if (type == QStringLiteral("Artist")) {
        result.kind = SearchResult::Kind::Artist;
        result.id = result.channelId;
        if (result.id.isEmpty()) {
            return result;
        }
        result.title = cleanArtistName(result.title);
        result.uploader = parts.size() > 1
                              ? cleanArtistName(
                                    parts.mid(1).join(QStringLiteral(" · ")))
                              : QString();
        if (result.uploader == result.title ||
            result.uploader == QStringLiteral("Topic")) {
            result.uploader.clear();
        }
        result.url = QStringLiteral("https://www.youtube.com/channel/") +
                     result.id + QStringLiteral("/videos");
        return result;
    }

    result.kind = SearchResult::Kind::Playlist;
    result.playlistId = findFirstString(object, QStringLiteral("playlistId"));
    if (result.playlistId.isEmpty()) {
        result.playlistId = findFirstString(object, QStringLiteral("browseId"));
    }
    if (result.playlistId.isEmpty()) {
        return result;
    }
    result.id = result.playlistId;
    result.url = QStringLiteral("https://www.youtube.com/playlist?list=") +
                 result.playlistId;
    result.uploader =
        parts.size() > 1 ? parts[1].trimmed() : QString();
    const QRegularExpression countRe(
        QStringLiteral("(\\d[\\d,.]*)\\s+(?:songs?|tracks?|videos?)"),
        QRegularExpression::CaseInsensitiveOption);
    for (const QString &text : texts) {
        const auto match = countRe.match(text);
        if (match.hasMatch()) {
            QString count = match.captured(1);
            count.remove(QLatin1Char(','));
            result.itemCount = count.toInt();
            break;
        }
    }
    return result;
}

void collectMusicItems(const QJsonValue &value,
                       QVector<SearchResult> &results,
                       QSet<QString> &seen) {
    if (value.isObject()) {
        const QJsonObject object = value.toObject();
        if (object.contains(
                QStringLiteral("musicResponsiveListItemRenderer"))) {
            const SearchResult result = parseMusicItem(
                object.value(
                          QStringLiteral("musicResponsiveListItemRenderer"))
                    .toObject());
            if (!result.title.isEmpty() && !result.id.isEmpty()) {
                const QString key =
                    QString::number(static_cast<int>(result.kind)) +
                    QLatin1Char(':') + result.id;
                if (!seen.contains(key)) {
                    seen.insert(key);
                    results.push_back(result);
                }
            }
        }
        for (auto it = object.begin(); it != object.end(); ++it) {
            collectMusicItems(it.value(), results, seen);
        }
    } else if (value.isArray()) {
        for (const QJsonValue &entry : value.toArray()) {
            collectMusicItems(entry, results, seen);
        }
    }
}

QVector<SearchResult> parseDocument(const QString &html,
                                    bool onlyTracks) {
    const QString initial = YouTubeParser::extractInitialData(html);
    if (initial.isEmpty()) {
        return {};
    }
    QJsonParseError error;
    const QJsonDocument document =
        QJsonDocument::fromJson(initial.toUtf8(), &error);
    if (error.error != QJsonParseError::NoError || !document.isObject()) {
        return {};
    }
    QVector<SearchResult> results;
    QSet<QString> seen;
    collect(document.object(), results, seen);
    if (onlyTracks) {
        QVector<SearchResult> tracks;
        for (const SearchResult &result : results) {
            if (result.kind == SearchResult::Kind::Track) {
                tracks.push_back(result);
            }
        }
        return tracks;
    }
    return results;
}

} // namespace

namespace YouTubeParser {

QString extractInitialData(const QString &html) {
    int marker = html.indexOf(QStringLiteral("var ytInitialData"));
    if (marker < 0) {
        marker = html.indexOf(QStringLiteral("ytInitialData"));
    }
    if (marker < 0) {
        return {};
    }
    const int start = html.indexOf(QLatin1Char('{'), marker);
    if (start < 0) {
        return {};
    }
    int depth = 0;
    bool inString = false;
    bool escaped = false;
    for (int i = start; i < html.size(); ++i) {
        const QChar ch = html.at(i);
        if (inString) {
            if (escaped) {
                escaped = false;
            } else if (ch == QLatin1Char('\\')) {
                escaped = true;
            } else if (ch == QLatin1Char('"')) {
                inString = false;
            }
            continue;
        }
        if (ch == QLatin1Char('"')) {
            inString = true;
        } else if (ch == QLatin1Char('{')) {
            ++depth;
        } else if (ch == QLatin1Char('}')) {
            --depth;
            if (depth == 0) {
                return html.mid(start, i - start + 1);
            }
        }
    }
    return {};
}

QVector<SearchResult> parseSearch(const QString &html) {
    return parseDocument(html, false);
}

QVector<SearchResult> parseMusicSearch(const QString &html) {
    const QString data = extractMusicSearchData(html);
    if (data.isEmpty()) {
        return {};
    }
    QJsonParseError error;
    const QJsonDocument document =
        QJsonDocument::fromJson(data.toUtf8(), &error);
    if (error.error != QJsonParseError::NoError || !document.isObject()) {
        return {};
    }
    QVector<SearchResult> results;
    QSet<QString> seen;
    collectMusicItems(document.object(), results, seen);
    return results;
}

QVector<SearchResult> parseRelated(const QString &html) {
    return parseDocument(html, true);
}

QVector<SearchResult> parseChannelVideos(const QString &html) {
    return parseDocument(html, true);
}

QVector<SearchResult> parseChannelPlaylists(const QString &html) {
    const QVector<SearchResult> all = parseDocument(html, false);
    QVector<SearchResult> playlists;
    for (const SearchResult &result : all) {
        if (result.kind == SearchResult::Kind::Playlist) {
            playlists.push_back(result);
        }
    }
    return playlists;
}

QVector<SearchResult> parsePlaylist(const QString &html) {
    return parseDocument(html, true);
}

} // namespace YouTubeParser
