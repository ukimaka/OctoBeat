#include "RemoteImageCache.h"

#include "app/CoverCache.h"

#include <QGuiApplication>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QDateTime>
#include <QNetworkRequest>
#include <QTimer>

RemoteImageCache::RemoteImageCache(QObject *parent)
    : QObject(parent), m_network(new QNetworkAccessManager(this)) {}

QString RemoteImageCache::keyFor(const QString &url,
                                 const QSize &size,
                                 const QString &mode) const {
    return QStringLiteral("%1|%2:%3:%4")
        .arg(url, mode)
        .arg(size.width())
        .arg(size.height());
}

void RemoteImageCache::request(
    const QString &url,
    int size,
    std::function<void(const QPixmap &)> callback) {
    if (url.isEmpty() || !callback || size <= 0) {
        return;
    }
    const QSize box(size, size);
    const QString key = keyFor(url, box, QStringLiteral("square"));
    if (m_cache.contains(key)) {
        callback(m_cache.value(key));
        return;
    }
    if (m_failed.contains(key)) {
        const qint64 failedAt = m_failedAt.value(key, 0);
        if (QDateTime::currentMSecsSinceEpoch() - failedAt < 15000) {
            return;
        }
        m_failed.remove(key);
        m_attempts.remove(key);
    }
    if (m_pending.contains(key)) {
        m_waiters[key].push_back(std::move(callback));
        return;
    }
    m_pending.insert(key);
    m_waiters[key].push_back(std::move(callback));
    fetch(url, key, box, QStringLiteral("square"), {});
}

void RemoteImageCache::requestRaw(
    const QString &url,
    int size,
    std::function<void(const QPixmap &)> callback) {
    if (url.isEmpty() || !callback || size <= 0) {
        return;
    }
    const QSize box(size, size);
    const QString key = keyFor(url, box, QStringLiteral("raw"));
    if (m_cache.contains(key)) {
        callback(m_cache.value(key));
        return;
    }
    if (m_failed.contains(key)) {
        const qint64 failedAt = m_failedAt.value(key, 0);
        if (QDateTime::currentMSecsSinceEpoch() - failedAt < 15000) {
            return;
        }
        m_failed.remove(key);
        m_attempts.remove(key);
    }
    if (m_pending.contains(key)) {
        m_waiters[key].push_back(std::move(callback));
        return;
    }
    m_pending.insert(key);
    m_waiters[key].push_back(std::move(callback));
    fetch(url, key, box, QStringLiteral("raw"), {});
}

void RemoteImageCache::requestFit(
    const QString &url,
    const QSize &box,
    std::function<void(const QPixmap &)> callback) {
    if (url.isEmpty() || !callback || box.isEmpty()) {
        return;
    }
    const bool square = box.width() == box.height();
    const QString mode =
        square ? QStringLiteral("square") : QStringLiteral("fit");
    const QString key = keyFor(url, box, mode);
    if (m_cache.contains(key)) {
        callback(m_cache.value(key));
        return;
    }
    if (m_failed.contains(key)) {
        const qint64 failedAt = m_failedAt.value(key, 0);
        if (QDateTime::currentMSecsSinceEpoch() - failedAt < 15000) {
            return;
        }
        m_failed.remove(key);
        m_attempts.remove(key);
    }
    if (m_pending.contains(key)) {
        m_waiters[key].push_back(std::move(callback));
        return;
    }
    m_pending.insert(key);
    m_waiters[key].push_back(std::move(callback));
    fetch(url, key, box, mode, {});
}

void RemoteImageCache::fetch(
    const QString &url,
    const QString &key,
    const QSize &box,
    const QString &mode,
    std::function<void(const QPixmap &)>) {
    QNetworkRequest request{QUrl(url)};
    request.setHeader(QNetworkRequest::UserAgentHeader,
                      QStringLiteral("Mozilla/5.0 (X11; Linux x86_64) "
                                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                                     "Chrome/131.0.0.0 Safari/537.36"));
    QNetworkReply *reply = m_network->get(request);
    connect(reply, &QNetworkReply::finished, this,
            [this, url, key, box, mode, reply] {
                const QByteArray data = reply->readAll();
                QImage image;
                const bool ok = !data.isEmpty() && image.loadFromData(data);
                reply->deleteLater();

                QPixmap pixmap;
                if (ok) {
                    const qreal dpr = qGuiApp
                                          ? qGuiApp->devicePixelRatio()
                                          : qreal(1.0);
                    if (mode == QStringLiteral("square")) {
                        pixmap = CoverCache::square(
                            QPixmap::fromImage(image), box.width());
                    } else {
                        // Crop to the slot on all sides. No blurred backdrop
                        // and no letterboxing for mismatched aspect ratios.
                        pixmap = CoverCache::crop(
                            QPixmap::fromImage(image), box);
                    }
                }
                if (pixmap.isNull()) {
                    const int attempt = m_attempts.value(key, 0) + 1;
                    m_attempts.insert(key, attempt);
                    if (attempt <= 2) {
                        QTimer::singleShot(350 * attempt, this,
                                           [this, url, key, box, mode] {
                            if (m_cache.contains(key)) {
                                return;
                            }
                            fetch(url, key, box, mode, {});
                        });
                    } else {
                        m_failed.insert(key);
                        m_failedAt.insert(
                            key, QDateTime::currentMSecsSinceEpoch());
                        m_pending.remove(key);
                        m_waiters.remove(key);
                    }
                    return;
                }
                m_attempts.remove(key);
                m_failed.remove(key);
                m_failedAt.remove(key);
                m_cache.insert(key, pixmap);
                m_pending.remove(key);
                const auto callbacks = m_waiters.take(key);
                for (const auto &callback : callbacks) {
                    callback(pixmap);
                }
            });
}
