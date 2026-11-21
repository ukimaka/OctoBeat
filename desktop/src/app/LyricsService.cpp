#include "LyricsService.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QRegularExpression>
#include <QStringList>
#include <QUrl>
#include <QUrlQuery>

#include <algorithm>
#include <limits>

namespace {

constexpr qint64 DurationToleranceMs = 5000;

QString fold(const QString &value) {
    QString text = value.toLower();
    text.replace(QRegularExpression(QStringLiteral("[^\\w\\s]"),
                                    QRegularExpression::UseUnicodePropertiesOption),
                 QStringLiteral(" "));
    text.replace(QRegularExpression(QStringLiteral("\\s+")), QStringLiteral(" "));
    return text.trimmed();
}

QString stripFeat(const QString &value) {
    const QRegularExpression re(QStringLiteral("\\b(?:feat|ft|featuring)\\b"),
                                QRegularExpression::CaseInsensitiveOption);
    const QRegularExpressionMatch match = re.match(value);
    if (match.hasMatch()) {
        return value.left(match.capturedStart()).trimmed();
    }
    return value;
}

double similarity(const QString &left, const QString &right) {
    const int a = left.size();
    const int b = right.size();
    if (a == 0 && b == 0) {
        return 1.0;
    }
    if (a == 0 || b == 0) {
        return 0.0;
    }
    QVector<int> previous(b + 1);
    QVector<int> current(b + 1);
    for (int j = 0; j <= b; ++j) {
        previous[j] = j;
    }
    for (int i = 1; i <= a; ++i) {
        current[0] = i;
        for (int j = 1; j <= b; ++j) {
            const int cost = left.at(i - 1) == right.at(j - 1) ? 0 : 1;
            current[j] = std::min({previous[j] + 1, current[j - 1] + 1,
                                   previous[j - 1] + cost});
        }
        previous = current;
    }
    return 1.0 - static_cast<double>(previous[b]) /
                     static_cast<double>(std::max(a, b));
}

QStringList artistVariants(const QString &value) {
    QString raw = stripFeat(value);
    QStringList variants;
    const auto add = [&variants](const QString &text) {
        QString folded = fold(text);
        if (folded.isEmpty()) {
            return;
        }
        variants.push_back(folded);
        if (folded.startsWith(QStringLiteral("the "))) {
            variants.push_back(folded.mid(4));
        }
    };
    add(raw);
    QString noAnd = raw;
    noAnd.replace(QRegularExpression(QStringLiteral("\\band\\b"),
                                     QRegularExpression::CaseInsensitiveOption),
                  QStringLiteral(" "));
    add(noAnd);
    for (const QString &part :
         raw.split(QRegularExpression(QStringLiteral("\\s*[;,\\/&+]\\s*")),
                   Qt::SkipEmptyParts)) {
        add(part);
    }
    return variants;
}

bool artistsMatch(const QString &left, const QString &right) {
    const QStringList a = artistVariants(left);
    const QStringList b = artistVariants(right);
    if (a.isEmpty() || b.isEmpty()) {
        return false;
    }
    for (const QString &first : a) {
        for (const QString &second : b) {
            if (first == second || similarity(first, second) >= 0.9) {
                return true;
            }
        }
    }
    return false;
}

bool titlesMatch(const QString &left, const QString &right) {
    const QString a = fold(left);
    const QString b = fold(right);
    if (a.isEmpty() || b.isEmpty()) {
        return false;
    }
    if (a == b) {
        return true;
    }
    const QString aBase = stripFeat(a);
    const QString bBase = stripFeat(b);
    if (!aBase.isEmpty() && aBase == bBase) {
        return true;
    }
    return similarity(aBase.isEmpty() ? a : aBase,
                      bBase.isEmpty() ? b : bBase) >= 0.9;
}

bool recordMatches(const QJsonObject &record,
                   const QString &artist,
                   const QString &title,
                   qint64 durationSeconds) {
    const QString recArtist = record.value(QStringLiteral("artistName")).toString();
    const QString recTitle = record.value(QStringLiteral("trackName")).toString();
    if (recArtist.trimmed().isEmpty() || recTitle.trimmed().isEmpty()) {
        return false;
    }
    if (!artistsMatch(artist, recArtist) || !titlesMatch(title, recTitle)) {
        return false;
    }
    const qint64 expectedMs = durationSeconds * 1000;
    const double candidateSeconds =
        record.value(QStringLiteral("duration")).toDouble();
    if (expectedMs > 0 && candidateSeconds > 0) {
        const qint64 candidateMs = qRound64(candidateSeconds * 1000.0);
        const qint64 tolerance =
            qMax<qint64>(DurationToleranceMs, expectedMs * 3 / 100);
        if (qAbs(expectedMs - candidateMs) > tolerance) {
            return false;
        }
    }
    return true;
}

bool hasLyrics(const QJsonObject &record) {
    return !record.value(QStringLiteral("syncedLyrics")).toString().trimmed().isEmpty() ||
           !record.value(QStringLiteral("plainLyrics")).toString().trimmed().isEmpty() ||
           !record.value(QStringLiteral("lyricsfile")).toString().trimmed().isEmpty();
}

qint64 timeToMs(const QString &minutes, const QString &seconds) {
    QString value = seconds;
    value.replace(QLatin1Char(':'), QLatin1Char('.'));
    return qRound64((minutes.toInt() * 60.0 + value.toDouble()) * 1000.0);
}

QVector<LyricsWord> parseWordTags(const QString &content, qint64 lineTime) {
    static const QRegularExpression wordRe(
        QStringLiteral("<(\\d{1,3}):(\\d{1,2}(?:[.:]\\d{1,3})?)>"));
    QVector<LyricsWord> words;
    QRegularExpressionMatchIterator it = wordRe.globalMatch(content);
    QVector<QRegularExpressionMatch> matches;
    while (it.hasNext()) {
        matches.push_back(it.next());
    }
    if (matches.isEmpty()) {
        return words;
    }
    const QString lead = content.left(matches.first().capturedStart()).trimmed();
    if (!lead.isEmpty()) {
        words.push_back({lineTime, lead});
    }
    for (int i = 0; i < matches.size(); ++i) {
        const int start = matches[i].capturedEnd();
        const int end = (i + 1 < matches.size())
                            ? matches[i + 1].capturedStart()
                            : content.size();
        const QString text = content.mid(start, end - start).trimmed();
        if (!text.isEmpty()) {
            words.push_back({timeToMs(matches[i].captured(1),
                                      matches[i].captured(2)),
                             text});
        }
    }
    return words;
}

QVector<LyricsLine> parseLrc(const QString &text) {
    static const QRegularExpression lineRe(
        QStringLiteral("\\[(\\d{1,3}):(\\d{1,2}(?:[.:]\\d{1,3})?)\\]"));
    static const QRegularExpression wordTagRe(
        QStringLiteral("<\\d{1,3}:\\d{1,2}(?:[.:]\\d{1,3})?>"));

    QVector<LyricsLine> lines;
    for (const QString &raw : text.split(QLatin1Char('\n'))) {
        QVector<QRegularExpressionMatch> marks;
        auto it = lineRe.globalMatch(raw);
        while (it.hasNext()) {
            marks.push_back(it.next());
        }
        if (marks.isEmpty()) {
            continue;
        }
        const QString content = raw.mid(marks.last().capturedEnd()).trimmed();
        QString display = content;
        display.remove(wordTagRe);
        display = display.trimmed();
        const qint64 firstTime =
            timeToMs(marks.first().captured(1), marks.first().captured(2));
        const QVector<LyricsWord> words = parseWordTags(content, firstTime);
        for (const auto &mark : marks) {
            LyricsLine line;
            line.timeMs = timeToMs(mark.captured(1), mark.captured(2));
            line.text = display;
            line.words = words;
            for (LyricsWord &word : line.words) {
                if (word.timeMs < 0) {
                    word.timeMs = line.timeMs;
                }
            }
            lines.push_back(line);
        }
    }
    std::stable_sort(lines.begin(), lines.end(),
                     [](const LyricsLine &a, const LyricsLine &b) {
                         return a.timeMs < b.timeMs;
                     });
    return lines;
}

QString unquoteYaml(const QString &value) {
    QString text = value.trimmed();
    if (text.size() >= 2 &&
        ((text.startsWith(QLatin1Char('\'')) && text.endsWith(QLatin1Char('\''))) ||
         (text.startsWith(QLatin1Char('"')) && text.endsWith(QLatin1Char('"'))))) {
        text = text.mid(1, text.size() - 2);
    }
    text.replace(QStringLiteral("''"), QStringLiteral("'"));
    text.replace(QStringLiteral("\\'"), QStringLiteral("'"));
    text.replace(QStringLiteral("\\\""), QStringLiteral("\""));
    return text;
}

QVector<LyricsLine> parseLyricsFile(const QString &text) {
    QVector<LyricsLine> lines;
    if (!text.contains(QStringLiteral("lines:"))) {
        return lines;
    }
    bool inLines = false;
    bool inWords = false;
    LyricsLine current;
    LyricsWord currentWord;
    bool haveLine = false;
    bool haveWord = false;

    const auto flushWord = [&] {
        if (haveWord) {
            if (!currentWord.text.isEmpty()) {
                current.words.push_back(currentWord);
            }
            currentWord = {};
            haveWord = false;
        }
    };
    const auto flushLine = [&] {
        flushWord();
        if (haveLine) {
            current.text = current.text.trimmed();
            if (!current.text.isEmpty() || !current.words.isEmpty()) {
                lines.push_back(current);
            }
            current = {};
            haveLine = false;
        }
    };

    for (const QString &raw : text.split(QLatin1Char('\n'))) {
        const QString trimmed = raw.trimmed();
        if (trimmed == QStringLiteral("lines:")) {
            inLines = true;
            continue;
        }
        if (!inLines || trimmed.isEmpty()) {
            continue;
        }
        int indent = 0;
        while (indent < raw.size() &&
               (raw.at(indent) == QLatin1Char(' ') ||
                raw.at(indent) == QLatin1Char('\t'))) {
            ++indent;
        }
        if (trimmed.startsWith(QStringLiteral("words:"))) {
            inWords = true;
            continue;
        }
        if (trimmed.startsWith(QStringLiteral("- text:"))) {
            const QString value =
                unquoteYaml(trimmed.mid(QStringLiteral("- text:").size()));
            if (indent <= 0) {
                flushLine();
                current = {};
                current.text = value;
                haveLine = true;
                inWords = false;
            } else {
                flushWord();
                currentWord = {};
                currentWord.text = value;
                haveWord = true;
            }
            continue;
        }
        if (trimmed.startsWith(QStringLiteral("start_ms:"))) {
            const qint64 value =
                trimmed.mid(QStringLiteral("start_ms:").size()).trimmed().toLongLong();
            if (haveWord) {
                currentWord.timeMs = value;
            } else if (haveLine) {
                current.timeMs = value;
            }
            continue;
        }
        if (trimmed.startsWith(QStringLiteral("end_ms:")) ||
            trimmed.startsWith(QStringLiteral("metadata:")) ||
            trimmed.startsWith(QStringLiteral("version:")) ||
            trimmed.startsWith(QStringLiteral("title:")) ||
            trimmed.startsWith(QStringLiteral("artist:")) ||
            trimmed.startsWith(QStringLiteral("album:")) ||
            trimmed.startsWith(QStringLiteral("duration_ms:")) ||
            trimmed.startsWith(QStringLiteral("instrumental:")) ||
            trimmed.startsWith(QStringLiteral("language:"))) {
            continue;
        }
    }
    flushLine();
    return lines;
}

QString formatLrcTime(qint64 ms) {
    const qint64 totalSeconds = qMax<qint64>(0, ms) / 1000;
    const qint64 minutes = totalSeconds / 60;
    const qint64 seconds = totalSeconds % 60;
    const qint64 centis = (qMax<qint64>(0, ms) % 1000) / 10;
    return QStringLiteral("%1:%2.%3")
        .arg(minutes, 2, 10, QLatin1Char('0'))
        .arg(seconds, 2, 10, QLatin1Char('0'))
        .arg(centis, 2, 10, QLatin1Char('0'));
}

QString enhancedLrc(const QVector<LyricsLine> &lines) {
    QStringList output;
    for (const LyricsLine &line : lines) {
        QString row = QStringLiteral("[") + formatLrcTime(line.timeMs) + QStringLiteral("]");
        if (line.words.isEmpty()) {
            row += QLatin1Char(' ') + line.text;
        } else {
            for (const LyricsWord &word : line.words) {
                row += QStringLiteral(" <") + formatLrcTime(word.timeMs) +
                       QStringLiteral(">") + word.text;
            }
        }
        output.push_back(row);
    }
    return output.join(QLatin1Char('\n'));
}

} // namespace

LyricsService::LyricsService(CoreClient *core, QObject *parent)
    : QObject(parent),
      m_core(core),
      m_network(new QNetworkAccessManager(this)) {}

void LyricsService::setTrack(const Track &track) {
    m_track = track;
    m_trackId = track.id;
    m_lines.clear();
    m_plain.clear();
    m_mode = QStringLiteral("empty");
    m_lineIndex = -1;
    m_wordIndex = -1;
    m_position = 0;
    m_loading = false;
    ++m_fetchToken;

    if (!m_core || m_trackId <= 0) {
        emitContent();
        emit highlightChanged(-1, -1);
        return;
    }

    loadForTrack();
}

void LyricsService::clear() {
    setTrack({});
}

void LyricsService::loadForTrack() {
    if (!m_core || m_trackId <= 0) {
        emitContent();
        return;
    }
    const LyricsData data = m_core->trackLyrics(m_trackId);
    m_offsetMs = static_cast<int>(data.offsetMs);
    emit offsetChanged(m_offsetMs);
    const bool hasSaved =
        !data.synced.trimmed().isEmpty() || !data.plain.trimmed().isEmpty();
    if (hasSaved) {
        applyPayload(data.synced, data.plain, false);
    }

    if (!data.checked && !m_attempted.contains(m_trackId)) {
        m_attempted.insert(m_trackId);
        m_loading = true;
        if (!hasSaved) {
            m_mode = QStringLiteral("loading");
            emitContent();
        }
        fetchFromLrclib();
    } else if (!hasSaved) {
        m_mode = QStringLiteral("empty");
        emitContent();
        emit highlightChanged(-1, -1);
    }
}

void LyricsService::reloadCurrent() {
    if (m_trackId > 0) {
        loadForTrack();
    }
}

void LyricsService::refreshHighlight() {
    computeHighlight(true);
}

void LyricsService::applyPayload(const QString &synced,
                                 const QString &plain,
                                 bool loading,
                                 const QString &lyricsFile) {
    QVector<LyricsLine> parsed;
    QString syncedForSave = synced;
    if (!lyricsFile.trimmed().isEmpty()) {
        parsed = parseLyricsFile(lyricsFile);
        if (!parsed.isEmpty()) {
            syncedForSave = enhancedLrc(parsed);
        }
    }
    if (parsed.isEmpty()) {
        parsed = parseLrc(syncedForSave);
    }
    m_lines = parsed;
    m_plain = plain;
    m_loading = loading;
    if (!m_lines.isEmpty()) {
        m_mode = QStringLiteral("synced");
    } else if (!m_plain.isEmpty()) {
        m_mode = QStringLiteral("plain");
    } else {
        m_mode = loading ? QStringLiteral("loading") : QStringLiteral("empty");
    }
    emitContent();
    computeHighlight(true);
}

void LyricsService::emitContent() {
    emit contentChanged(m_mode, m_lines, m_plain);
}

void LyricsService::setPosition(qint64 milliseconds) {
    m_position = milliseconds;
    computeHighlight(false);
}

void LyricsService::adjustOffset(int deltaMs) {
    m_offsetMs += deltaMs;
    if (m_core && m_trackId > 0) {
        m_core->setLyricsOffset(m_trackId, m_offsetMs);
    }
    emit offsetChanged(m_offsetMs);
    computeHighlight(true);
}

int LyricsService::lineIndexFor(qint64 position) const {
    int index = -1;
    for (int i = 0; i < m_lines.size(); ++i) {
        if (m_lines[i].timeMs <= position) {
            index = i;
        } else {
            break;
        }
    }
    return index;
}

int LyricsService::wordIndexFor(int lineIndex, qint64 position) const {
    if (lineIndex < 0 || lineIndex >= m_lines.size()) {
        return -1;
    }
    const LyricsLine &line = m_lines[lineIndex];
    if (line.words.isEmpty()) {
        return -1;
    }
    int index = -1;
    for (int i = 0; i < line.words.size(); ++i) {
        const qint64 time = line.words[i].timeMs >= 0
                                ? line.words[i].timeMs
                                : line.timeMs;
        if (time <= position) {
            index = i;
        } else {
            break;
        }
    }
    return index;
}

void LyricsService::computeHighlight(bool force) {
    const qint64 adjusted = m_position + m_offsetMs;
    const int line = lineIndexFor(adjusted);
    const int word = wordIndexFor(line, adjusted);
    if (!force && line == m_lineIndex && word == m_wordIndex) {
        return;
    }
    m_lineIndex = line;
    m_wordIndex = word;
    emit highlightChanged(line, word);
}

void LyricsService::fetchFromLrclib() {
    if (!m_network || m_track.artist.trimmed().isEmpty() ||
        m_track.title.trimmed().isEmpty()) {
        m_loading = false;
        if (m_lines.isEmpty() && m_plain.isEmpty()) {
            m_mode = QStringLiteral("empty");
            emitContent();
        }
        return;
    }

    QUrl url(QStringLiteral("https://lrclib.net/api/search"));
    QUrlQuery query;
    query.addQueryItem(QStringLiteral("artist_name"), m_track.artist);
    query.addQueryItem(QStringLiteral("track_name"), m_track.title);
    url.setQuery(query);

    QNetworkRequest request(url);
    request.setHeader(QNetworkRequest::UserAgentHeader,
                      QStringLiteral("OctoBeat/0.1"));
    request.setTransferTimeout(10000);
    const qint64 trackId = m_trackId;
    const int token = ++m_fetchToken;
    QNetworkReply *reply = m_network->get(request);
    connect(reply, &QNetworkReply::finished, this,
            [this, reply, trackId, token] {
                handleSearchReply(reply, trackId, token);
                reply->deleteLater();
            });
}

void LyricsService::handleSearchReply(QNetworkReply *reply,
                                      qint64 trackId,
                                      int token) {
    if (trackId != m_trackId || token != m_fetchToken) {
        return;
    }
    const QByteArray payload = reply->readAll();
    const int status = reply->attribute(
                               QNetworkRequest::HttpStatusCodeAttribute)
                           .toInt();
    if (status != 200 || reply->error() != QNetworkReply::NoError) {
        m_loading = false;
        if (m_lines.isEmpty() && m_plain.isEmpty()) {
            m_mode = QStringLiteral("empty");
            emitContent();
        }
        return;
    }

    const QJsonDocument document = QJsonDocument::fromJson(payload);
    const QJsonArray records =
        document.isArray() ? document.array() : QJsonArray();
    QJsonObject best;
    qint64 bestDiff = std::numeric_limits<qint64>::max();
    for (const QJsonValue &value : records) {
        if (!value.isObject()) {
            continue;
        }
        const QJsonObject record = value.toObject();
        if (!recordMatches(record, m_track.artist, m_track.title,
                           m_track.duration) ||
            !hasLyrics(record)) {
            continue;
        }
        const double candidate =
            record.value(QStringLiteral("duration")).toDouble();
        const qint64 candidateMs = qRound64(candidate * 1000.0);
        const qint64 diff = qAbs(candidateMs - m_track.duration * 1000);
        const bool synced =
            !record.value(QStringLiteral("syncedLyrics")).toString().trimmed().isEmpty() ||
            !record.value(QStringLiteral("lyricsfile")).toString().trimmed().isEmpty();
        const bool bestSynced =
            !best.value(QStringLiteral("syncedLyrics")).toString().trimmed().isEmpty() ||
            !best.value(QStringLiteral("lyricsfile")).toString().trimmed().isEmpty();
        if (best.isEmpty() || (synced && !bestSynced) ||
            (synced == bestSynced && diff < bestDiff)) {
            best = record;
            bestDiff = diff;
        }
    }

    if (!best.isEmpty()) {
        pickRecord(best);
        return;
    }

    QUrl url(QStringLiteral("https://lrclib.net/api/get"));
    QUrlQuery query;
    query.addQueryItem(QStringLiteral("artist_name"), m_track.artist);
    query.addQueryItem(QStringLiteral("track_name"), m_track.title);
    url.setQuery(query);
    QNetworkRequest request(url);
    request.setHeader(QNetworkRequest::UserAgentHeader,
                      QStringLiteral("OctoBeat/0.1"));
    request.setTransferTimeout(10000);
    QNetworkReply *getReply = m_network->get(request);
    connect(getReply, &QNetworkReply::finished, this,
            [this, getReply, trackId, token] {
                handleGetReply(getReply, trackId, token);
                getReply->deleteLater();
            });
}

void LyricsService::handleGetReply(QNetworkReply *reply,
                                   qint64 trackId,
                                   int token) {
    if (trackId != m_trackId || token != m_fetchToken) {
        return;
    }
    const int status = reply->attribute(
                               QNetworkRequest::HttpStatusCodeAttribute)
                           .toInt();
    const QJsonDocument document = QJsonDocument::fromJson(reply->readAll());
    if (status == 200 && document.isObject() &&
        recordMatches(document.object(), m_track.artist, m_track.title,
                      m_track.duration) &&
        hasLyrics(document.object())) {
        pickRecord(document.object());
        return;
    }
    m_loading = false;
    if (m_lines.isEmpty() && m_plain.isEmpty()) {
        m_mode = QStringLiteral("empty");
        emitContent();
        emit highlightChanged(-1, -1);
    }
}

void LyricsService::pickRecord(const QJsonObject &record) {
    const QString synced =
        record.value(QStringLiteral("syncedLyrics")).toString().trimmed();
    const QString plain =
        record.value(QStringLiteral("plainLyrics")).toString().trimmed();
    const QString lyricsFile =
        record.value(QStringLiteral("lyricsfile")).toString().trimmed();
    if (synced.isEmpty() && plain.isEmpty() && lyricsFile.isEmpty()) {
        m_loading = false;
        return;
    }

    QString syncedToSave = synced;
    if (!lyricsFile.isEmpty()) {
        const QVector<LyricsLine> wordLines = parseLyricsFile(lyricsFile);
        if (!wordLines.isEmpty()) {
            syncedToSave = enhancedLrc(wordLines);
        }
    }
    if (m_core && m_trackId > 0) {
        m_core->updateTrackLyrics(m_trackId, syncedToSave, plain, false);
    }
    m_loading = false;
    applyPayload(syncedToSave, plain, false);
}
