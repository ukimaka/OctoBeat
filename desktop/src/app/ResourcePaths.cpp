#include "ResourcePaths.h"

#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>

namespace {

QString existing(const QString &path) {
    return QFileInfo::exists(path) ? path : QString();
}

} // namespace

namespace ResourcePaths {

QString root() {
    const QString override =
        qEnvironmentVariable("OCTOBEAT_RESOURCES_DIR");
    if (!override.isEmpty() && QFileInfo::exists(override)) {
        return override;
    }

    const QString appDir = QCoreApplication::applicationDirPath();
    const QStringList candidates = {
        QDir(appDir).filePath(QStringLiteral("resources")),
        QDir(appDir).filePath(QStringLiteral("../share/octobeat")),
        QDir(appDir).filePath(QStringLiteral("../../share/octobeat")),
        QStringLiteral(OCTOBEAT_RESOURCES_DIR),
    };
    for (const QString &candidate : candidates) {
        if (!candidate.isEmpty() && QFileInfo::exists(candidate)) {
            const QString clean = QDir(candidate).absolutePath();
            if (QFileInfo::exists(QDir(clean).filePath(
                    QStringLiteral("themes/dark.qss")))) {
                return clean;
            }
        }
    }
    return QDir(appDir).absolutePath();
}

QString file(const QString &relativePath) {
    return QDir(root()).filePath(relativePath);
}

} // namespace ResourcePaths
