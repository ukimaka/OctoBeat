#pragma once

#include <QColor>
#include <QIcon>
#include <QPixmap>
#include <QString>

namespace IconUtils {

QIcon tinted(const QString &fileName, const QColor &color, int size = 32);
QPixmap logo(int size = 24);

} // namespace IconUtils
