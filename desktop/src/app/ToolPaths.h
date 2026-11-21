#pragma once

#include <QProcessEnvironment>
#include <QString>
#include <QStringList>

// Locates bundled helper binaries (yt-dlp, ffmpeg, deno, somedl) without
// relying on the user's PATH. Dev builds fall back to the system PATH.
namespace ToolPaths {

QString directory();
QString executable(const QString &name);
QStringList searchPath();
QProcessEnvironment processEnvironment();

} // namespace ToolPaths
