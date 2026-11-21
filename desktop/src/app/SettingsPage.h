#pragma once

#include <QPair>
#include <QVector>
#include <QWidget>

class QComboBox;
class QPushButton;
class QLabel;
class QStackedWidget;

class SettingsPage : public QWidget {
    Q_OBJECT

public:
    SettingsPage(const QString &dataDir,
                 const QString &musicDir,
                 QWidget *parent = nullptr);

    void applyTheme();

signals:
    void themeChanged(const QString &theme);
    void clearCoversRequested();
    void clearCacheRequested();
    void musicFolderChanged(const QString &path);
    void csvImportRequested();
    void crossfadeChanged(bool enabled);

private:
    QWidget *buildGeneral();
    QWidget *buildAppearance();
    QWidget *buildYouTube();
    QWidget *buildData();
    QWidget *buildAbout();
    void updateCookiesStatus();
    void importCookies();

    QString m_dataDir;
    QString m_musicDir;
    QComboBox *m_theme = nullptr;
    QLabel *m_cookiesStatus = nullptr;
    QLabel *m_musicPath = nullptr;
    QVector<QPair<QPushButton *, QString>> m_iconButtons;
    QStackedWidget *m_stack = nullptr;
};
