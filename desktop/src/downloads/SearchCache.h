#pragma once

#include <QString>
#include <QVector>

#include "SearchResult.h"

namespace SearchCache {

QString directory();
void setDirectory(const QString &path);
QString keyFor(const QString &query, int filter, int limit);
bool load(const QString &key, QVector<SearchResult> &results);
void save(const QString &key, const QVector<SearchResult> &results);
void clear();

} // namespace SearchCache
