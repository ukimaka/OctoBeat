#include "MprisService.h"

#ifdef OCTOBEAT_NO_MPRIS
MprisService::MprisService(QObject *parent) : QObject(parent) {}
MprisService::~MprisService() = default;
bool MprisService::registerService() { return false; }
void MprisService::setTrack(const QString &, const QString &, const QString &,
                            const QString &, qint64, const QString &,
                            const QString &) {}
void MprisService::clearTrack() {}
void MprisService::setPlaybackStatus(const QString &) {}
void MprisService::setPosition(qint64) {}
void MprisService::setLength(qint64) {}
void MprisService::setVolumePercent(int) {}
void MprisService::setShuffle(bool) {}
void MprisService::setLoopStatus(const QString &) {}
void MprisService::setCanGoNext(bool) {}
void MprisService::setCanGoPrevious(bool) {}
void MprisService::setCanSeek(bool) {}
QStringList MprisService::supportedUriSchemes() const { return {}; }
QStringList MprisService::supportedMimeTypes() const { return {}; }
void MprisService::requestPlay() {}
void MprisService::requestPause() {}
void MprisService::requestPlayPause() {}
void MprisService::requestStop() {}
void MprisService::requestNext() {}
void MprisService::requestPrevious() {}
void MprisService::requestSeekTo(qint64) {}
void MprisService::requestSeekBy(qint64) {}
void MprisService::requestVolume(int) {}
void MprisService::requestShuffle(bool) {}
void MprisService::requestLoopStatus(const QString &) {}
void MprisService::requestOpenUri(const QString &) {}
void MprisService::Raise() {}
void MprisService::Quit() {}
#else

#include <QDBusConnection>
#include <QDBusMessage>
#include <QDBusObjectPath>
#include <QStringList>
#include <QUrl>

#include <algorithm>

namespace {
const QString ServiceName = QStringLiteral("org.mpris.MediaPlayer2.octobeat");
const QString ObjectPath = QStringLiteral("/org/mpris/MediaPlayer2");
const QString PlayerInterface =
    QStringLiteral("org.mpris.MediaPlayer2.Player");
const QString NoTrack =
    QStringLiteral("/org/mpris/MediaPlayer2/TrackList/NoTrack");

QString normalizedLoopStatus(const QString &status) {
    if (status == QStringLiteral("Track") ||
        status == QStringLiteral("Playlist")) {
        return status;
    }
    return QStringLiteral("None");
}

QString normalizedPlaybackStatus(const QString &status) {
    if (status == QStringLiteral("Playing") ||
        status == QStringLiteral("Paused")) {
        return status;
    }
    return QStringLiteral("Stopped");
}
} // namespace

MprisPlayerAdaptor::MprisPlayerAdaptor(MprisService *service)
    : QDBusAbstractAdaptor(service), m_service(service) {}

QString MprisPlayerAdaptor::playbackStatus() const {
    return m_service->playbackStatus();
}

QString MprisPlayerAdaptor::loopStatus() const {
    return m_service->loopStatus();
}

double MprisPlayerAdaptor::rate() const {
    return m_service->rate();
}

bool MprisPlayerAdaptor::shuffle() const {
    return m_service->shuffle();
}

QVariantMap MprisPlayerAdaptor::metadata() const {
    return m_service->metadata();
}

double MprisPlayerAdaptor::volume() const {
    return m_service->volume();
}

qlonglong MprisPlayerAdaptor::position() const {
    return m_service->position();
}

double MprisPlayerAdaptor::minimumRate() const {
    return m_service->minimumRate();
}

double MprisPlayerAdaptor::maximumRate() const {
    return m_service->maximumRate();
}

bool MprisPlayerAdaptor::canGoNext() const {
    return m_service->canGoNext();
}

bool MprisPlayerAdaptor::canGoPrevious() const {
    return m_service->canGoPrevious();
}

bool MprisPlayerAdaptor::canPlay() const {
    return m_service->canPlay();
}

bool MprisPlayerAdaptor::canPause() const {
    return m_service->canPause();
}

bool MprisPlayerAdaptor::canSeek() const {
    return m_service->canSeek();
}

bool MprisPlayerAdaptor::canControl() const {
    return m_service->canControl();
}

void MprisPlayerAdaptor::setLoopStatus(const QString &status) {
    m_service->requestLoopStatus(status);
}

void MprisPlayerAdaptor::setRate(double rate) {
    Q_UNUSED(rate);
}

void MprisPlayerAdaptor::setShuffle(bool shuffle) {
    m_service->requestShuffle(shuffle);
}

void MprisPlayerAdaptor::setVolume(double volume) {
    m_service->requestVolume(qRound(volume * 100.0));
}

void MprisPlayerAdaptor::Next() {
    m_service->requestNext();
}

void MprisPlayerAdaptor::Previous() {
    m_service->requestPrevious();
}

void MprisPlayerAdaptor::Pause() {
    m_service->requestPause();
}

void MprisPlayerAdaptor::PlayPause() {
    m_service->requestPlayPause();
}

void MprisPlayerAdaptor::Stop() {
    m_service->requestStop();
}

void MprisPlayerAdaptor::Play() {
    m_service->requestPlay();
}

void MprisPlayerAdaptor::Seek(qlonglong offset) {
    m_service->requestSeekBy(offset);
}

void MprisPlayerAdaptor::SetPosition(const QDBusObjectPath &trackId,
                                     qlonglong position) {
    if (trackId.path() != m_service->trackId()) {
        return;
    }
    m_service->requestSeekTo(position);
}

void MprisPlayerAdaptor::OpenUri(const QString &uri) {
    m_service->requestOpenUri(uri);
}

MprisService::MprisService(QObject *parent) : QObject(parent) {}

MprisService::~MprisService() {
    if (!m_registered) {
        return;
    }
    QDBusConnection bus = QDBusConnection::sessionBus();
    bus.unregisterObject(ObjectPath);
    bus.unregisterService(ServiceName);
}

bool MprisService::registerService() {
    if (m_registered) {
        return true;
    }
    QDBusConnection bus = QDBusConnection::sessionBus();
    if (!bus.isConnected()) {
        return false;
    }
    if (!bus.registerService(ServiceName)) {
        return false;
    }
    m_player = new MprisPlayerAdaptor(this);
    const auto options = QDBusConnection::ExportAdaptors |
                         QDBusConnection::ExportAllSlots |
                         QDBusConnection::ExportAllProperties;
    if (!bus.registerObject(ObjectPath, this, options)) {
        bus.unregisterService(ServiceName);
        return false;
    }
    m_registered = true;
    return true;
}

QStringList MprisService::supportedUriSchemes() const {
    return {QStringLiteral("file"), QStringLiteral("http"),
            QStringLiteral("https")};
}

QStringList MprisService::supportedMimeTypes() const {
    return {QStringLiteral("audio/mpeg"), QStringLiteral("audio/mp4"),
            QStringLiteral("audio/flac"), QStringLiteral("audio/ogg"),
            QStringLiteral("audio/opus"), QStringLiteral("audio/x-wav")};
}

void MprisService::setTrack(const QString &title,
                            const QString &artist,
                            const QString &album,
                            const QString &artUrl,
                            qint64 lengthUs,
                            const QString &url,
                            const QString &trackId) {
    m_trackId = trackId.isEmpty() ? NoTrack : trackId;
    QVariantMap metadata;
    metadata.insert(QStringLiteral("mpris:trackid"),
                    QVariant::fromValue(QDBusObjectPath(m_trackId)));
    m_positionUs = 0;
    if (lengthUs > 0) {
        metadata.insert(QStringLiteral("mpris:length"), lengthUs);
    }
    if (!title.isEmpty()) {
        metadata.insert(QStringLiteral("xesam:title"), title);
    }
    if (!artist.isEmpty()) {
        metadata.insert(QStringLiteral("xesam:artist"),
                        QStringList{artist});
    }
    if (!album.isEmpty()) {
        metadata.insert(QStringLiteral("xesam:album"), album);
    }
    if (!artUrl.isEmpty()) {
        metadata.insert(QStringLiteral("mpris:artUrl"), artUrl);
    }
    if (!url.isEmpty()) {
        metadata.insert(QStringLiteral("xesam:url"), url);
    }
    m_metadata = metadata;
    notifyPlayer(QStringLiteral("Metadata"),
                 QVariant::fromValue(m_metadata));
}

void MprisService::clearTrack() {
    m_trackId = NoTrack;
    m_positionUs = 0;
    m_metadata.clear();
    m_metadata.insert(QStringLiteral("mpris:trackid"),
                      QVariant::fromValue(QDBusObjectPath(NoTrack)));
    notifyPlayer(QStringLiteral("Metadata"),
                 QVariant::fromValue(m_metadata));
}

void MprisService::setPlaybackStatus(const QString &status) {
    const QString normalized = normalizedPlaybackStatus(status);
    if (m_playbackStatus == normalized) {
        return;
    }
    m_playbackStatus = normalized;
    notifyPlayer(QStringLiteral("PlaybackStatus"), m_playbackStatus);
}

void MprisService::setPosition(qint64 positionUs) {
    m_positionUs = std::max<qint64>(0, positionUs);
}

void MprisService::setLength(qint64 lengthUs) {
    if (lengthUs <= 0) {
        return;
    }
    if (m_metadata.value(QStringLiteral("mpris:length")).toLongLong() ==
        lengthUs) {
        return;
    }
    if (m_metadata.isEmpty()) {
        return;
    }
    m_metadata.insert(QStringLiteral("mpris:length"), lengthUs);
    notifyPlayer(QStringLiteral("Metadata"),
                 QVariant::fromValue(m_metadata));
}

void MprisService::setVolumePercent(int percent) {
    const double volume = qBound(0, percent, 100) / 100.0;
    if (qFuzzyCompare(m_volume, volume)) {
        return;
    }
    m_volume = volume;
    notifyPlayer(QStringLiteral("Volume"), m_volume);
}

void MprisService::setShuffle(bool shuffle) {
    if (m_shuffle == shuffle) {
        return;
    }
    m_shuffle = shuffle;
    notifyPlayer(QStringLiteral("Shuffle"), m_shuffle);
}

void MprisService::setLoopStatus(const QString &status) {
    const QString normalized = normalizedLoopStatus(status);
    if (m_loopStatus == normalized) {
        return;
    }
    m_loopStatus = normalized;
    notifyPlayer(QStringLiteral("LoopStatus"), m_loopStatus);
}

void MprisService::setCanGoNext(bool canGoNext) {
    if (m_canGoNext == canGoNext) {
        return;
    }
    m_canGoNext = canGoNext;
    notifyPlayer(QStringLiteral("CanGoNext"), m_canGoNext);
}

void MprisService::setCanGoPrevious(bool canGoPrevious) {
    if (m_canGoPrevious == canGoPrevious) {
        return;
    }
    m_canGoPrevious = canGoPrevious;
    notifyPlayer(QStringLiteral("CanGoPrevious"), m_canGoPrevious);
}

void MprisService::setCanSeek(bool canSeek) {
    if (m_canSeek == canSeek) {
        return;
    }
    m_canSeek = canSeek;
    notifyPlayer(QStringLiteral("CanSeek"), m_canSeek);
}

void MprisService::notifyPlayer(const QString &property,
                                const QVariant &value) {
    if (!m_registered) {
        return;
    }
    QVariantMap changed;
    changed.insert(property, value);
    QDBusMessage signal = QDBusMessage::createSignal(
        ObjectPath, QStringLiteral("org.freedesktop.DBus.Properties"),
        QStringLiteral("PropertiesChanged"));
    signal << PlayerInterface << changed << QStringList();
    QDBusConnection::sessionBus().send(signal);
}

void MprisService::emitSeeked(qint64 positionUs) {
    if (!m_registered || !m_player) {
        return;
    }
    emit m_player->Seeked(positionUs);
}

void MprisService::requestPlay() {
    emit playRequested();
}

void MprisService::requestPause() {
    emit pauseRequested();
}

void MprisService::requestPlayPause() {
    emit playPauseRequested();
}

void MprisService::requestStop() {
    emit stopRequested();
}

void MprisService::requestNext() {
    emit nextRequested();
}

void MprisService::requestPrevious() {
    emit previousRequested();
}

void MprisService::requestSeekTo(qint64 positionUs) {
    const qint64 target = std::max<qint64>(0, positionUs);
    m_positionUs = target;
    emit seekRequested(target);
    emitSeeked(target);
}

void MprisService::requestSeekBy(qint64 offsetUs) {
    requestSeekTo(m_positionUs + offsetUs);
}

void MprisService::requestVolume(int percent) {
    emit volumeChangeRequested(qBound(0, percent, 100));
}

void MprisService::requestShuffle(bool shuffle) {
    emit shuffleChangeRequested(shuffle);
}

void MprisService::requestLoopStatus(const QString &status) {
    emit loopStatusChangeRequested(normalizedLoopStatus(status));
}

void MprisService::requestOpenUri(const QString &uri) {
    emit openUriRequested(uri);
}

void MprisService::Raise() {
    emit raiseRequested();
}

void MprisService::Quit() {
    emit quitRequested();
}

#endif // OCTOBEAT_NO_MPRIS
