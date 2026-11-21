#include "CoverCache.h"

#include <QCryptographicHash>
#include <QFile>
#include <QFileInfo>
#include <QGuiApplication>
#include <QHash>
#include <QPainterPath>
#include <QImageReader>
#include <QPainter>
#include <QPixmapCache>

namespace {

QPixmap croppedFromImage(const QImage &source, const QSize &size, qreal dpr) {
    if (source.isNull() || size.isEmpty()) {
        return {};
    }
    const QSize physical(qRound(size.width() * dpr),
                         qRound(size.height() * dpr));
    const QImage scaled = source.scaled(physical,
                                        Qt::KeepAspectRatioByExpanding,
                                        Qt::SmoothTransformation);
    const int x = qMax(0, (scaled.width() - physical.width()) / 2);
    const int y = qMax(0, (scaled.height() - physical.height()) / 2);
    QPixmap pixmap = QPixmap::fromImage(
        scaled.copy(x, y, physical.width(), physical.height()));
    pixmap.setDevicePixelRatio(dpr);
    return pixmap;
}

} // namespace

namespace CoverCache {

QPixmap cover(const QString &path, int size) {
    if (path.isEmpty() || size <= 0) {
        return {};
    }
    const qreal dpr = qGuiApp ? qGuiApp->devicePixelRatio() : qreal(1.0);
    const int physical = qRound(size * dpr);
    const QString key = QStringLiteral("octobeat-cover:%1:%2:%3")
                            .arg(path)
                            .arg(physical)
                            .arg(dpr);

    QPixmap pixmap;
    if (QPixmapCache::find(key, &pixmap)) {
        return pixmap;
    }

    QImageReader reader(path);
    reader.setAutoTransform(true);
    const QSize original = reader.size();
    if (original.isValid()) {
        const QSize loadSize = original.scaled(physical * 2, physical * 2,
                                               Qt::KeepAspectRatio);
        if (!loadSize.isEmpty()) {
            reader.setScaledSize(loadSize);
        }
    }
    const QImage image = reader.read();
    if (image.isNull()) {
        return {};
    }

    pixmap = croppedFromImage(image, QSize(size, size), dpr);
    if (!pixmap.isNull()) {
        QPixmapCache::insert(key, pixmap);
    }
    return pixmap;
}

QPixmap circularCover(const QString &path, int size) {
    const QPixmap source = cover(path, size);
    if (source.isNull() || size <= 0) {
        return {};
    }
    const QSize target = source.deviceIndependentSize().toSize();
    QImage image(target * source.devicePixelRatio(),
                 QImage::Format_ARGB32_Premultiplied);
    image.setDevicePixelRatio(source.devicePixelRatio());
    image.fill(Qt::transparent);
    QPainter painter(&image);
    painter.setRenderHint(QPainter::Antialiasing, true);
    QPainterPath circle;
    circle.addEllipse(QRectF(0, 0, image.width(), image.height()));
    painter.setClipPath(circle);
    painter.drawPixmap(0, 0, source);
    painter.end();
    return QPixmap::fromImage(image);
}

bool sameImage(const QString &first, const QString &second) {
    if (first.isEmpty() || second.isEmpty()) {
        return false;
    }
    const QFileInfo firstInfo(first);
    const QFileInfo secondInfo(second);
    if (!firstInfo.isFile() || !secondInfo.isFile()) {
        return false;
    }
    if (firstInfo.canonicalFilePath() == secondInfo.canonicalFilePath()) {
        return true;
    }
    if (firstInfo.size() != secondInfo.size()) {
        return false;
    }
    static QHash<QString, QByteArray> hashes;
    const auto digest = [](const QFileInfo &info) {
        const QString path = info.canonicalFilePath();
        const auto cached = hashes.constFind(path);
        if (cached != hashes.constEnd()) {
            return *cached;
        }
        QFile file(path);
        if (!file.open(QIODevice::ReadOnly)) {
            return QByteArray();
        }
        const QByteArray hash =
            QCryptographicHash::hash(file.readAll(), QCryptographicHash::Sha256);
        hashes.insert(path, hash);
        return hash;
    };
    const QByteArray firstHash = digest(firstInfo);
    return !firstHash.isEmpty() && firstHash == digest(secondInfo);
}

QPixmap square(const QPixmap &source, int size) {
    if (source.isNull() || size <= 0) {
        return {};
    }
    const qreal dpr = qGuiApp ? qGuiApp->devicePixelRatio() : qreal(1.0);
    return croppedFromImage(source.toImage(), QSize(size, size), dpr);
}

QPixmap crop(const QPixmap &source, const QSize &size) {
    if (source.isNull() || size.isEmpty()) {
        return {};
    }
    const qreal dpr = qGuiApp ? qGuiApp->devicePixelRatio() : qreal(1.0);
    return croppedFromImage(source.toImage(), size, dpr);
}

void clear() {
    QPixmapCache::clear();
}

} // namespace CoverCache
