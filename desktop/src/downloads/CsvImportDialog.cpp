#include "CsvImportDialog.h"

#include "SomeDlService.h"
#include "app/Theme.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QLabel>
#include <QPlainTextEdit>
#include <QProgressBar>
#include <QPushButton>
#include <QTimer>
#include <QVBoxLayout>

#include <cstdio>

namespace {

bool readCsvRows(const QString &path,
                 QVector<QPair<QString, QString>> &rows,
                 QString &error) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        error = QObject::tr("Could not read the CSV file.");
        return false;
    }
    QString text = QString::fromUtf8(file.readAll());
    if (!text.isEmpty() && text.at(0) == QChar(0xFEFF)) {
        text.remove(0, 1);
    }
    if (text.trimmed().isEmpty()) {
        error = QObject::tr("The CSV file is empty.");
        return false;
    }

    QVector<QStringList> records;
    QStringList fields;
    QString field;
    bool quoted = false;
    for (int i = 0; i < text.size(); ++i) {
        const QChar ch = text.at(i);
        if (quoted) {
            if (ch == QLatin1Char('"')) {
                if (i + 1 < text.size() &&
                    text.at(i + 1) == QLatin1Char('"')) {
                    field.append(QLatin1Char('"'));
                    ++i;
                } else {
                    quoted = false;
                }
            } else {
                field.append(ch);
            }
            continue;
        }
        if (ch == QLatin1Char('"')) {
            quoted = true;
        } else if (ch == QLatin1Char(',')) {
            fields.push_back(field);
            field.clear();
        } else if (ch == QLatin1Char('\n')) {
            fields.push_back(field);
            field.clear();
            records.push_back(fields);
            fields.clear();
        } else if (ch == QLatin1Char('\r')) {
            continue;
        } else {
            field.append(ch);
        }
    }
    if (quoted) {
        error = QObject::tr("The CSV file has an unterminated quote.");
        return false;
    }
    if (!field.isEmpty() || !fields.isEmpty()) {
        fields.push_back(field);
        records.push_back(fields);
    }
    if (records.isEmpty()) {
        error = QObject::tr("The CSV file is empty.");
        return false;
    }

    const QStringList header = records.takeFirst();
    int trackColumn = -1;
    int artistColumn = -1;
    for (int i = 0; i < header.size(); ++i) {
        const QString name = header.at(i).trimmed().toLower();
        if (name == QStringLiteral("track name")) {
            trackColumn = i;
        } else if (name == QStringLiteral("artist name(s)") ||
                   name == QStringLiteral("artist name") ||
                   name == QStringLiteral("artist")) {
            artistColumn = i;
        }
    }
    if (trackColumn < 0 || artistColumn < 0) {
        error = QObject::tr(
            "The CSV has no Track Name and Artist Name(s) columns.");
        return false;
    }

    for (const QStringList &record : records) {
        if (record.size() <= trackColumn ||
            record.size() <= artistColumn) {
            continue;
        }
        const QString title = record.at(trackColumn).trimmed();
        const QString artist = record.at(artistColumn).trimmed();
        if (!title.isEmpty() && !artist.isEmpty()) {
            rows.push_back({artist, title});
        }
    }
    if (rows.isEmpty()) {
        error = QObject::tr("The CSV file has no tracks.");
        return false;
    }
    return true;
}

} // namespace

CsvImportDialog::CsvImportDialog(const QString &csvPath,
                                 const QString &musicDir,
                                 const QString &dataDir,
                                 QWidget *parent)
    : QDialog(parent),
      m_csvPath(csvPath),
      m_musicDir(musicDir),
      m_dataDir(dataDir) {
    setWindowTitle(tr("Import from CSV"));
    setModal(true);
    setMinimumWidth(520);

    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(18, 16, 18, 14);
    layout->setSpacing(10);

    auto *title = new QLabel(tr("Import from CSV"), this);
    QFont titleFont = title->font();
    titleFont.setPixelSize(17);
    titleFont.setBold(true);
    title->setFont(titleFont);
    layout->addWidget(title);

    m_fileLabel = new QLabel(QFileInfo(csvPath).fileName(), this);
    m_fileLabel->setStyleSheet(
        QStringLiteral("color: rgba(220, 220, 232, 150);"));
    m_fileLabel->setWordWrap(true);
    layout->addWidget(m_fileLabel);

    m_progress = new QProgressBar(this);
    m_progress->setObjectName(QStringLiteral("csvProgress"));
    m_progress->setTextVisible(true);
    m_progress->setFixedHeight(16);
    m_progress->setStyleSheet(
        QStringLiteral(
            "QProgressBar { background: rgba(255, 255, 255, 18);"
            " border: none; border-radius: 8px; text-align: center;"
            " color: #f0f0f5; font-size: 10px; }"
            "QProgressBar::chunk { background: %1;"
            " border-radius: 8px; }")
            .arg(Theme::accent().name()));
    m_progress->setRange(0, 1);
    m_progress->setValue(0);
    layout->addWidget(m_progress);

    m_status = new QLabel(tr("Preparing import…"), this);
    m_status->setWordWrap(true);
    layout->addWidget(m_status);

    m_log = new QPlainTextEdit(this);
    m_log->setObjectName(QStringLiteral("csvLog"));
    m_log->setReadOnly(true);
    m_log->setMaximumBlockCount(200);
    m_log->setFixedHeight(110);
    m_log->setPlaceholderText(tr("Failures will be listed here."));
    layout->addWidget(m_log);

    auto *buttons = new QHBoxLayout();
    buttons->addStretch(1);
    m_action = new QPushButton(tr("Cancel"), this);
    m_action->setCursor(Qt::PointingHandCursor);
    buttons->addWidget(m_action);
    layout->addLayout(buttons);

    m_downloader = new SomeDlService(dataDir, this);

    connect(m_action, &QPushButton::clicked, this,
            &CsvImportDialog::cancelOrClose);
    connect(m_downloader, &SomeDlService::downloadProgress, this,
            [this](int percent) {
                if (!m_running) {
                    return;
                }
                const Row &row = m_rows.at(m_index);
                setStatus(tr("Downloading: %1 — %2 · %3%")
                              .arg(row.artist, row.title)
                              .arg(percent));
            });
    connect(m_downloader, &SomeDlService::downloadFinished, this,
            [this](const QString &path) {
                if (!m_running) {
                    return;
                }
                const Row &row = m_rows.at(m_index);
                ++m_added;
                ++m_index;
                m_progress->setValue(m_index);
                m_log->appendPlainText(
                    tr("Downloaded: %1 — %2 (%3)")
                        .arg(row.artist, row.title,
                             QFileInfo(path).fileName()));
                QTimer::singleShot(0, this, &CsvImportDialog::processNext);
            });
    connect(m_downloader, &SomeDlService::failed, this,
            [this](const QString &message) {
                if (m_running) {
                    failCurrent(message);
                }
            });
    connect(m_downloader, &SomeDlService::canceled, this, [this] {
        if (m_running) {
            failCurrent(tr("Download canceled."));
        }
    });

    parseFile();
}

CsvImportDialog::~CsvImportDialog() {
    m_running = false;
    if (m_downloader) {
        m_downloader->cancel();
    }
}

void CsvImportDialog::parseFile() {
    QVector<QPair<QString, QString>> rows;
    m_parseError.clear();
    if (!readCsvRows(m_csvPath, rows, m_parseError)) {
        if (m_status) {
            m_status->setText(m_parseError);
        }
        return;
    }
    m_rows.reserve(rows.size());
    for (const auto &[artist, title] : rows) {
        m_rows.push_back({artist, title});
    }
    if (m_fileLabel) {
        const QString count = m_rows.size() == 1
                                  ? tr("1 track")
                                  : tr("%1 tracks").arg(m_rows.size());
        m_fileLabel->setText(
            QStringLiteral("%1 · %2")
                .arg(QFileInfo(m_csvPath).fileName(), count));
    }
    if (m_status) {
        m_status->setText(
            m_rows.size() == 1
                ? tr("Ready to import 1 track.")
                : tr("Ready to import %1 tracks.").arg(m_rows.size()));
    }
}

void CsvImportDialog::start() {
    if (m_running || m_completed) {
        return;
    }
    if (m_rows.isEmpty()) {
        m_completed = true;
        m_progress->setRange(0, 1);
        m_progress->setValue(0);
        m_action->setText(tr("Close"));
        return;
    }
    if (!SomeDlService::isAvailable()) {
        m_completed = true;
        setStatus(tr("SomeDL is not installed. Install it with: "
                     "pip install somedl"));
        m_log->appendPlainText(m_status->text());
        m_action->setText(tr("Close"));
        return;
    }
    m_running = true;
    m_action->setText(tr("Cancel"));
    m_progress->setRange(0, m_rows.size());
    m_progress->setValue(0);
    processNext();
}

void CsvImportDialog::processNext() {
    if (!m_running) {
        return;
    }
    if (m_index >= m_rows.size()) {
        finishImport();
        return;
    }
    const Row &row = m_rows.at(m_index);
    setStatus(tr("Downloading: %1 — %2").arg(row.artist, row.title));
    m_downloader->download(
        row.artist + QStringLiteral(" - ") + row.title,
        m_musicDir, cookiesPath());
}

void CsvImportDialog::failCurrent(const QString &reason) {
    if (!m_running) {
        return;
    }
    const Row &row = m_rows.at(m_index);
    ++m_failed;
    ++m_index;
    m_progress->setValue(m_index);
    m_log->appendPlainText(
        tr("Failed: %1 — %2: %3").arg(row.artist, row.title, reason));
    QTimer::singleShot(0, this, &CsvImportDialog::processNext);
}

void CsvImportDialog::finishImport() {
    m_running = false;
    m_completed = true;
    m_progress->setValue(m_rows.size());
    const QString summary =
        m_rows.size() == 1
            ? tr("Imported 1 track. Failed: %1.").arg(m_failed)
            : tr("Imported %1 of %2 tracks. Failed: %3.")
                  .arg(m_added)
                  .arg(m_rows.size())
                  .arg(m_failed);
    setStatus(summary);
    m_action->setText(tr("Close"));
    std::fprintf(stderr, "csv-import: added=%d failed=%d total=%d\n",
                 m_added, m_failed,
                 static_cast<int>(m_rows.size()));
    emit libraryChanged();
    emit finished(m_added, m_failed);
}

void CsvImportDialog::cancelOrClose() {
    if (!m_running) {
        accept();
        return;
    }
    m_running = false;
    m_downloader->cancel();
    m_completed = true;
    m_progress->setValue(m_index);
    setStatus(tr("Import canceled."));
    std::fprintf(stderr, "csv-import: canceled added=%d failed=%d\n",
                 m_added, m_failed);
    emit libraryChanged();
    emit finished(m_added, m_failed);
    accept();
}

void CsvImportDialog::reject() {
    if (m_running) {
        cancelOrClose();
        return;
    }
    QDialog::reject();
}

void CsvImportDialog::setStatus(const QString &text) {
    if (m_status) {
        m_status->setText(text);
    }
}

QString CsvImportDialog::cookiesPath() const {
    const QStringList candidates = {
        QDir(m_dataDir).filePath(QStringLiteral("cookies.txt")),
        QDir(m_musicDir).filePath(QStringLiteral("cookies.txt")),
    };
    for (const QString &candidate : candidates) {
        if (QFileInfo(candidate).isFile()) {
            return candidate;
        }
    }
    return {};
}
