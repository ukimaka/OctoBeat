#include "Translations.h"

#include "ResourcePaths.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QHash>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTranslator>

namespace {

QString russianPlural(int n, const QString &one, const QString &few,
                      const QString &many) {
    const int mod100 = n % 100;
    const int mod10 = n % 10;
    if (mod100 >= 11 && mod100 <= 14) {
        return many;
    }
    if (mod10 == 1) {
        return one;
    }
    if (mod10 >= 2 && mod10 <= 4) {
        return few;
    }
    return many;
}

class JsonTranslator final : public QTranslator {
public:
    explicit JsonTranslator(QObject *parent = nullptr) : QTranslator(parent) {}

    bool load(const QString &path) {
        QFile file(path);
        if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) {
            return false;
        }
        const QJsonDocument document = QJsonDocument::fromJson(file.readAll());
        if (!document.isObject()) {
            return false;
        }
        const QJsonObject object = document.object();
        for (auto it = object.constBegin(); it != object.constEnd(); ++it) {
            if (it.value().isString()) {
                m_map.insert(it.key(), it.value().toString());
            }
        }
        return !m_map.isEmpty();
    }

    bool isEmpty() const override { return m_map.isEmpty(); }

    QString translate(const char *context,
                      const char *sourceText,
                      const char *disambiguation,
                      int n) const override {
        Q_UNUSED(context);
        Q_UNUSED(disambiguation);
        if (!sourceText) {
            return {};
        }
        const QString source = QString::fromUtf8(sourceText);

        // Russian plural forms need more than a simple %n substitution.
        if (source == QStringLiteral("%n track(s)")) {
            return QStringLiteral("%1 %2")
                .arg(n)
                .arg(russianPlural(n, QStringLiteral("трек"),
                                   QStringLiteral("трека"),
                                   QStringLiteral("треков")));
        }
        if (source == QStringLiteral("%n result(s)")) {
            return QStringLiteral("%1 %2")
                .arg(n)
                .arg(russianPlural(n, QStringLiteral("результат"),
                                   QStringLiteral("результата"),
                                   QStringLiteral("результатов")));
        }

        const auto it = m_map.constFind(source);
        if (it == m_map.constEnd()) {
            return {};
        }
        QString result = it.value();
        if (result.contains(QStringLiteral("%n"))) {
            result.replace(QStringLiteral("%n"), QString::number(n));
        }
        return result;
    }

private:
    QHash<QString, QString> m_map;
};

} // namespace

namespace Translations {

bool install(QCoreApplication *app, const QString &language) {
    if (!app || language != QStringLiteral("ru")) {
        return false;
    }
    const QString path = ResourcePaths::file(
        QStringLiteral("resources/translations/ru.json"));
    auto *translator = new JsonTranslator(app);
    if (!translator->load(path)) {
        delete translator;
        return false;
    }
    return app->installTranslator(translator);
}

} // namespace Translations
