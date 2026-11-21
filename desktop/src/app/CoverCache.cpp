#include "CoverCache.h"

#include <QGuiApplication>
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
