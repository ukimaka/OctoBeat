#include "IconUtils.h"

#include "ResourcePaths.h"

#include <QDir>
#include <QGuiApplication>
#include <QPainter>
#include <QPixmap>
#include <QSvgRenderer>

namespace {

QPixmap renderSvg(const QString &path, int size, const QColor *tint) {
    QSvgRenderer renderer(path);
    if (!renderer.isValid() || size <= 0) {
        return {};
    }

    const qreal dpr =
        qGuiApp ? qGuiApp->devicePixelRatio() : qreal(1.0);
    QPixmap pixmap(qRound(size * dpr), qRound(size * dpr));
    pixmap.fill(Qt::transparent);
    QPainter painter(&pixmap);
    painter.setRenderHint(QPainter::Antialiasing, true);
    painter.setRenderHint(QPainter::SmoothPixmapTransform, true);
    renderer.render(&painter);
    if (tint) {
        painter.setCompositionMode(QPainter::CompositionMode_SourceIn);
        painter.fillRect(pixmap.rect(), *tint);
    }
    painter.end();
    pixmap.setDevicePixelRatio(dpr);
    return pixmap;
}

QString blackIconPath(const QString &fileName) {
    return ResourcePaths::file(QStringLiteral("icons/black/") + fileName);
}

} // namespace

namespace IconUtils {

QIcon tinted(const QString &fileName, const QColor &color, int size) {
    const QPixmap pixmap = renderSvg(blackIconPath(fileName), size, &color);
    if (pixmap.isNull()) {
        return {};
    }
    return QIcon(pixmap);
}

QPixmap logo(int size) {
    const QString path = ResourcePaths::file(QStringLiteral("icons/OctoBeat.svg"));
    return renderSvg(path, size, nullptr);
}

} // namespace IconUtils
