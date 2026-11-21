#pragma once

#include <QPixmap>
#include <QSize>
#include <QString>

namespace CoverCache {

QPixmap cover(const QString &path, int size);
QPixmap square(const QPixmap &source, int size);
QPixmap crop(const QPixmap &source, const QSize &size);
void clear();

} // namespace CoverCache
