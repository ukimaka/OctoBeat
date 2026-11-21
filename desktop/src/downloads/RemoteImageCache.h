#pragma once

#include <QHash>
#include <QObject>
#include <QPixmap>
#include <QSet>
#include <QSize>
#include <QString>
#include <QVector>

#include <functional>

class QNetworkAccessManager;

class RemoteImageCache : public QObject {
    Q_OBJECT

public:
    explicit RemoteImageCache(QObject *parent = nullptr);

    void request(const QString &url,
                 int size,
                 std::function<void(const QPixmap &)> callback);
    void requestFit(const QString &url,
                    const QSize &box,
                    std::function<void(const QPixmap &)> callback);
    void requestRaw(const QString &url,
                    int size,
                    std::function<void(const QPixmap &)> callback);

private:
    QString keyFor(const QString &url,
                   const QSize &size,
                   const QString &mode) const;
    void fetch(const QString &url,
               const QString &key,
               const QSize &size,
               const QString &mode,
               std::function<void(const QPixmap &)> callback);

    QNetworkAccessManager *m_network = nullptr;
    QHash<QString, QPixmap> m_cache;
    QHash<QString, QVector<std::function<void(const QPixmap &)>>> m_waiters;
    QSet<QString> m_pending;
    QSet<QString> m_failed;
    QHash<QString, int> m_attempts;
    QHash<QString, qint64> m_failedAt;
};
