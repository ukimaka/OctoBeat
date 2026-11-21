#pragma once

#include <QString>

class QCoreApplication;

namespace Translations {

/// Installs the JSON translator for the given language code. Returns true
/// when a translation file was loaded and installed.
bool install(QCoreApplication *app, const QString &language);

} // namespace Translations
