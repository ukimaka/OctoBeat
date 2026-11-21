#include "ToolPaths.h"

#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QStandardPaths>

namespace {

QString findInDirectory(const QString &directory, const QString &name) {
    if (directory.isEmpty()) {
        return {};
    }
    QDir dir(directory);
    const QStringList names = {
        name,
        name + QStringLiteral(".exe"),
    };
    for (const QString &candidate : names) {
        const QString path = dir.filePath(candidate);
        if (QFileInfo(path).isFile()) {
            return QFileInfo(path).absoluteFilePath();
        }
    }
    return {};
}

} // namespace

namespace ToolPaths {

QString directory() {
    const QString override = qEnvironmentVariable("OCTOBEAT_TOOLS_DIR");
    if (!override.isEmpty() && QFileInfo(override).isDir()) {
        return override;
    }
    const QString appDir = QCoreApplication::applicationDirPath();
    const QStringList candidates = {
        QDir(appDir).filePath(QStringLiteral("tools")),
        QDir(appDir).filePath(QStringLiteral("../share/octobeat/tools")),
        QDir(appDir).filePath(QStringLiteral("../../share/octobeat/tools")),
    };
    for (const QString &candidate : candidates) {
        if (QFileInfo(candidate).isDir()) {
            return candidate;
        }
    }
    return {};
}

QString executable(const QString &name) {
    const QString bundled = findInDirectory(directory(), name);
    if (!bundled.isEmpty()) {
        return bundled;
    }
    return QStandardPaths::findExecutable(name);
}

QStringList searchPath() {
    QStringList paths;
    const QString tools = directory();
    if (!tools.isEmpty()) {
        paths.push_back(tools);
    }
    const QString current = qEnvironmentVariable("PATH");
    if (!current.isEmpty()) {
        paths += current.split(QDir::listSeparator(), Qt::SkipEmptyParts);
    }
    return paths;
}

QProcessEnvironment processEnvironment() {
    QProcessEnvironment environment = QProcessEnvironment::systemEnvironment();
    environment.insert(QStringLiteral("PATH"),
                       searchPath().join(QDir::listSeparator()));
    return environment;
}

} // namespace ToolPaths
