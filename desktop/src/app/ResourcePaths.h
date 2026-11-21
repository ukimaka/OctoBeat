#pragma once

#include <QString>

// Locates the read-only application assets (icons, themes, translations).
// Development builds use the source tree; installed builds use resources next
// to the executable (Windows) or share/octobeat (Linux/Flatpak).
namespace ResourcePaths {

QString root();
QString file(const QString &relativePath);

} // namespace ResourcePaths
