#pragma once

#ifndef OCTOBEAT_NO_MPRIS
#include <QDBusAbstractAdaptor>
#include <QDBusObjectPath>
#endif
#include <QObject>
#include <QString>
#include <QStringList>
#include <QVariantMap>

class MprisService;

#ifndef OCTOBEAT_NO_MPRIS
class MprisPlayerAdaptor : public QDBusAbstractAdaptor {
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "org.mpris.MediaPlayer2.Player")
    Q_PROPERTY(QString PlaybackStatus READ playbackStatus)
    Q_PROPERTY(QString LoopStatus READ loopStatus WRITE setLoopStatus)
    Q_PROPERTY(double Rate READ rate WRITE setRate)
    Q_PROPERTY(bool Shuffle READ shuffle WRITE setShuffle)
    Q_PROPERTY(QVariantMap Metadata READ metadata)
    Q_PROPERTY(double Volume READ volume WRITE setVolume)
    Q_PROPERTY(qlonglong Position READ position)
    Q_PROPERTY(double MinimumRate READ minimumRate)
    Q_PROPERTY(double MaximumRate READ maximumRate)
    Q_PROPERTY(bool CanGoNext READ canGoNext)
    Q_PROPERTY(bool CanGoPrevious READ canGoPrevious)
    Q_PROPERTY(bool CanPlay READ canPlay)
    Q_PROPERTY(bool CanPause READ canPause)
    Q_PROPERTY(bool CanSeek READ canSeek)
    Q_PROPERTY(bool CanControl READ canControl)

public:
    explicit MprisPlayerAdaptor(MprisService *service);

    QString playbackStatus() const;
    QString loopStatus() const;
    double rate() const;
    bool shuffle() const;
    QVariantMap metadata() const;
    double volume() const;
    qlonglong position() const;
    double minimumRate() const;
    double maximumRate() const;
    bool canGoNext() const;
    bool canGoPrevious() const;
    bool canPlay() const;
    bool canPause() const;
    bool canSeek() const;
    bool canControl() const;

    void setLoopStatus(const QString &status);
    void setRate(double rate);
    void setShuffle(bool shuffle);
    void setVolume(double volume);

signals:
    void Seeked(qlonglong position);

public slots:
    void Next();
    void Previous();
    void Pause();
    void PlayPause();
    void Stop();
    void Play();
    void Seek(qlonglong offset);
    void SetPosition(const QDBusObjectPath &trackId, qlonglong position);
    void OpenUri(const QString &uri);

private:
    MprisService *m_service = nullptr;
};
#endif

class MprisService : public QObject {
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "org.mpris.MediaPlayer2")
    Q_PROPERTY(bool CanQuit READ canQuit CONSTANT)
    Q_PROPERTY(bool CanRaise READ canRaise CONSTANT)
    Q_PROPERTY(bool HasTrackList READ hasTrackList CONSTANT)
    Q_PROPERTY(QString Identity READ identity CONSTANT)
    Q_PROPERTY(QString DesktopEntry READ desktopEntry CONSTANT)
    Q_PROPERTY(QStringList SupportedUriSchemes READ supportedUriSchemes CONSTANT)
    Q_PROPERTY(QStringList SupportedMimeTypes READ supportedMimeTypes CONSTANT)

public:
    explicit MprisService(QObject *parent = nullptr);
    ~MprisService() override;

    bool registerService();
    bool isRegistered() const { return m_registered; }

    void setTrack(const QString &title,
                  const QString &artist,
                  const QString &album,
                  const QString &artUrl,
                  qint64 lengthUs,
                  const QString &url,
                  const QString &trackId);
    void clearTrack();
    void setPlaybackStatus(const QString &status);
    void setPosition(qint64 positionUs);
    void setLength(qint64 lengthUs);
    void setVolumePercent(int percent);
    void setShuffle(bool shuffle);
    void setLoopStatus(const QString &status);
    void setCanGoNext(bool canGoNext);
    void setCanGoPrevious(bool canGoPrevious);
    void setCanSeek(bool canSeek);

    // Getters used by MprisPlayerAdaptor.
    QString playbackStatus() const { return m_playbackStatus; }
    QString loopStatus() const { return m_loopStatus; }
    double rate() const { return 1.0; }
    bool shuffle() const { return m_shuffle; }
    QVariantMap metadata() const { return m_metadata; }
    double volume() const { return m_volume; }
    qlonglong position() const { return m_positionUs; }
    double minimumRate() const { return 1.0; }
    double maximumRate() const { return 1.0; }
    bool canGoNext() const { return m_canGoNext; }
    bool canGoPrevious() const { return m_canGoPrevious; }
    bool canPlay() const { return true; }
    bool canPause() const { return true; }
    bool canSeek() const { return m_canSeek; }
    bool canControl() const { return true; }

    // Root interface properties.
    bool canQuit() const { return true; }
    bool canRaise() const { return true; }
    bool hasTrackList() const { return false; }
    QString identity() const { return QStringLiteral("OctoBeat"); }
    QString desktopEntry() const { return QStringLiteral("octobeat"); }
    QStringList supportedUriSchemes() const;
    QStringList supportedMimeTypes() const;

    // Requests coming from D-Bus.
    void requestPlay();
    void requestPause();
    void requestPlayPause();
    void requestStop();
    void requestNext();
    void requestPrevious();
    void requestSeekTo(qint64 positionUs);
    void requestSeekBy(qint64 offsetUs);
    void requestVolume(int percent);
    void requestShuffle(bool shuffle);
    void requestLoopStatus(const QString &status);
    void requestOpenUri(const QString &uri);
    QString trackId() const { return m_trackId; }

public slots:
    void Raise();
    void Quit();

signals:
    void raiseRequested();
    void quitRequested();
    void playRequested();
    void pauseRequested();
    void playPauseRequested();
    void stopRequested();
    void nextRequested();
    void previousRequested();
    void seekRequested(qint64 positionUs);
    void volumeChangeRequested(int percent);
    void shuffleChangeRequested(bool shuffle);
    void loopStatusChangeRequested(const QString &status);
    void openUriRequested(const QString &uri);

private:
    void notifyPlayer(const QString &property, const QVariant &value);
    void emitSeeked(qint64 positionUs);

#ifndef OCTOBEAT_NO_MPRIS
    MprisPlayerAdaptor *m_player = nullptr;
#endif
    QString m_playbackStatus = QStringLiteral("Stopped");
    QString m_loopStatus = QStringLiteral("None");
    QVariantMap m_metadata;
    QString m_trackId;
    qint64 m_positionUs = 0;
    double m_volume = 0.7;
    bool m_shuffle = false;
    bool m_canGoNext = false;
    bool m_canGoPrevious = false;
    bool m_canSeek = true;
    bool m_registered = false;
};
