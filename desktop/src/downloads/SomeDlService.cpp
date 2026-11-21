#include "SomeDlService.h"

#include "app/ToolPaths.h"

#include <QCoreApplication>
#include <QDir>
#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QProcess>
#include <QRegularExpression>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QTimer>

namespace {
const QStringList AudioExtensions = {
    QStringLiteral("opus"), QStringLiteral("ogg"), QStringLiteral("flac"),
    QStringLiteral("m4a"), QStringLiteral("mp3"), QStringLiteral("webm")};
constexpr int StartTimeoutMs = 30 * 60 * 1000;
constexpr int StallTimeoutMs = 5 * 60 * 1000;

// Non-blocking process teardown; see FastStreamService for the rationale.
void retireProcess(QProcess *process) {
    if (!process) {
        return;
    }
    process->disconnect();
    process->setParent(nullptr);
    QObject::connect(process,
                     QOverload<int, QProcess::ExitStatus>::of(
                         &QProcess::finished),
                     process, &QObject::deleteLater);
    QObject::connect(process, &QProcess::errorOccurred, process,
                     &QObject::deleteLater);
    if (process->state() != QProcess::NotRunning) {
        process->kill();
    } else {
        process->deleteLater();
    }
}

QString uniqueTarget(const QString &directory, const QString &fileName) {
    const QString base = QFileInfo(fileName).completeBaseName();
    const QString suffix = QFileInfo(fileName).suffix();
    QString candidate = QDir(directory).filePath(fileName);
    int index = 2;
    while (QFileInfo::exists(candidate)) {
        candidate = QDir(directory).filePath(
            QStringLiteral("%1 (%2).%3").arg(base).arg(index).arg(suffix));
        ++index;
    }
    return candidate;
}
} // namespace

SomeDlService::SomeDlService(const QString &dataDir, QObject *parent)
    : QObject(parent), m_dataDir(dataDir) {
    m_timeout = new QTimer(this);
    m_timeout->setSingleShot(true);
    connect(m_timeout, &QTimer::timeout, this, [this] {
        fail(tr("SomeDL did not finish in time."));
    });
    m_stall = new QTimer(this);
    m_stall->setSingleShot(true);
    connect(m_stall, &QTimer::timeout, this, [this] {
        fail(tr("SomeDL stopped responding."));
    });
}

SomeDlService::~SomeDlService() {
    if (m_process) {
        m_canceled = true;
        stopProcess();
    }
    cleanup();
}

QString SomeDlService::executablePath() {
    return ToolPaths::executable(QStringLiteral("somedl"));
}

bool SomeDlService::isAvailable() {
    return !executablePath().isEmpty();
}

bool SomeDlService::isBusy() const {
    return m_process && m_process->state() != QProcess::NotRunning;
}

void SomeDlService::download(const QString &query,
                             const QString &outputDir,
                             const QString &cookiesPath) {
    if (isBusy()) {
        emit failed(tr("A download is already in progress."));
        return;
    }
    const QString clean = query.trimmed();
    if (clean.isEmpty()) {
        emit failed(tr("No track selected."));
        return;
    }
    const QString executable = executablePath();
    if (executable.isEmpty()) {
        emit failed(tr("SomeDL is not installed. Install it with: "
                       "pip install somedl"));
        return;
    }
    if (!QDir().mkpath(outputDir)) {
        emit failed(tr("Could not create the download folder: %1").arg(outputDir));
        return;
    }

    cleanup();
    m_query = clean;
    m_outputDir = outputDir;
    m_cookies = cookiesPath;
    m_output.clear();
    m_lastError.clear();
    m_canceled = false;
    m_staging = new QTemporaryDir(
        QDir(outputDir).filePath(QStringLiteral(".somedl-XXXXXX")));
    if (!m_staging->isValid()) {
        fail(tr("Could not create a SomeDL staging folder."));
        return;
    }

    QStringList args = {
        clean,
        QStringLiteral("-o"), m_staging->path(),
        QStringLiteral("-f"), QStringLiteral("opus"),
        QStringLiteral("--disable-report"),
        QStringLiteral("--no-album"),
        QStringLiteral("--get-song")};
    if (!cookiesPath.isEmpty() && QFileInfo::exists(cookiesPath)) {
        args << QStringLiteral("--cookies") << cookiesPath;
    }

    m_process = new QProcess(this);
    m_process->setProcessChannelMode(QProcess::MergedChannels);
    QProcessEnvironment env = ToolPaths::processEnvironment();
    const QString configHome =
        QDir(m_dataDir).filePath(QStringLiteral("somedl-config"));
    QDir().mkpath(configHome);
    env.insert(QStringLiteral("XDG_CONFIG_HOME"), configHome);
    env.insert(QStringLiteral("APPDATA"), configHome);
    env.insert(QStringLiteral("PYTHONUNBUFFERED"), QStringLiteral("1"));
    m_process->setProcessEnvironment(env);
    m_process->setProgram(executable);
    m_process->setArguments(args);
    connect(m_process, &QProcess::readyReadStandardOutput, this,
            &SomeDlService::handleOutput);
    connect(m_process, &QProcess::finished, this,
            [this](int exitCode, QProcess::ExitStatus) {
                handleFinished(exitCode);
            });
    connect(m_process, &QProcess::errorOccurred, this,
            [this](QProcess::ProcessError error) {
                if (error == QProcess::FailedToStart) {
                    fail(tr("Could not start SomeDL."));
                }
            });
    m_timeout->start(StartTimeoutMs);
    m_stall->start(StallTimeoutMs);
    m_process->start();
}

void SomeDlService::cancel() {
    if (!m_process) {
        return;
    }
    m_canceled = true;
    stopProcess();
    cleanup();
    emit canceled();
}

void SomeDlService::stopProcess() {
    m_timeout->stop();
    m_stall->stop();
    if (!m_process) {
        return;
    }
    QProcess *process = m_process;
    m_process = nullptr;
    retireProcess(process);
}

void SomeDlService::handleOutput() {
    if (!m_process) {
        return;
    }
    const QString chunk = QString::fromUtf8(m_process->readAllStandardOutput());
    m_output += chunk;
    if (m_output.size() > 8000) {
        m_output = m_output.right(8000);
    }
    if (!chunk.isEmpty()) {
        m_stall->start(StallTimeoutMs);
    }
    static const QRegularExpression percentRe(
        QStringLiteral("(\\d{1,3})%"));
    const auto matches = percentRe.globalMatch(chunk);
    int last = -1;
    auto match = matches;
    while (match.hasNext()) {
        last = qBound(0, match.next().captured(1).toInt(), 100);
    }
    if (last >= 0) {
        emit downloadProgress(last);
    }
}

void SomeDlService::handleFinished(int exitCode) {
    m_timeout->stop();
    m_stall->stop();
    if (m_process) {
        m_process->deleteLater();
        m_process = nullptr;
    }
    if (m_canceled) {
        cleanup();
        return;
    }
    if (exitCode != 0) {
        fail(m_output.trimmed().isEmpty()
                 ? tr("SomeDL exited with code %1.").arg(exitCode)
                 : m_output.trimmed().right(1200));
        return;
    }

    QString source;
    if (m_staging) {
        QDirIterator it(m_staging->path(),
                        QDir::Files | QDir::NoDotAndDotDot,
                        QDirIterator::Subdirectories);
        while (it.hasNext()) {
            const QString path = it.next();
            if (AudioExtensions.contains(
                    QFileInfo(path).suffix().toLower())) {
                source = path;
                break;
            }
        }
    }
    if (source.isEmpty()) {
        fail(tr("SomeDL finished, but no audio file was created."));
        return;
    }

    const QString target = uniqueTarget(m_outputDir,
                                        QFileInfo(source).fileName());
    bool moved = QFile::rename(source, target);
    if (!moved) {
        moved = QFile::copy(source, target);
        if (moved) {
            QFile::remove(source);
        }
    }
    if (!moved) {
        fail(tr("Could not move the downloaded file to %1.").arg(target));
        return;
    }
    emit downloadProgress(100);
    cleanup();
    emit downloadFinished(target);
}

void SomeDlService::handleError() {
    if (m_process &&
        m_process->error() == QProcess::FailedToStart) {
        fail(tr("Could not start SomeDL."));
    }
}

void SomeDlService::fail(const QString &message) {
    m_lastError = message;
    stopProcess();
    cleanup();
    emit failed(message);
}

void SomeDlService::cleanup() {
    if (m_staging) {
        m_staging->remove();
        delete m_staging;
        m_staging = nullptr;
    }
}
