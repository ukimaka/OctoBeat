#pragma once

#include <QWidget>

#include "core/CoreClient.h"

class QHBoxLayout;
class QLabel;
class QListWidget;
class ProfileTextBrowser;
class ProfileAvatarButton;
class ProfileBannerButton;
class ProfileNameWidget;

class ProfilePage : public QWidget {
    Q_OBJECT

public:
    ProfilePage(CoreClient *core,
                const QString &dataDir,
                QWidget *parent = nullptr);

    void reload();
    void changeAvatar();

signals:
    void playRequested(qint64 trackId);
    void playlistRequested(qint64 playlistId);
    void avatarChanged();

private:
    void changeBanner();
    void editNickname();
    void editAbout();
    void setAvatarPixmap(const QPixmap &source);
    void setBannerPixmap(const QPixmap &source);
    void fillAchievements(const ProfileData &data);

    CoreClient *m_core = nullptr;
    QString m_dataDir;
    ProfileBannerButton *m_banner = nullptr;
    ProfileAvatarButton *m_avatar = nullptr;
    ProfileNameWidget *m_nickname = nullptr;
    ProfileTextBrowser *m_about = nullptr;
    QString m_description;
    QWidget *m_achievements = nullptr;
    QHBoxLayout *m_achievementsLayout = nullptr;
    QLabel *m_favorite = nullptr;
    QListWidget *m_topTracks = nullptr;
    QListWidget *m_publicPlaylists = nullptr;
};
