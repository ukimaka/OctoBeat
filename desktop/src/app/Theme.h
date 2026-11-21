#pragma once

#include <QColor>
#include <QString>
#include <QStringList>

namespace Theme {

QStringList availableThemes();
QString styleSheet(const QString &name);
void apply(const QString &name);
QString current();

bool isDark(const QString &name);
QColor accent(const QString &name = {});
QColor iconColor(const QString &name = {});

} // namespace Theme
