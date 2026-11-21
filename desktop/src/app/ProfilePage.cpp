#include "ProfilePage.h"

#include "CoverCache.h"
#include "IconUtils.h"
#include "Theme.h"

#include <QAbstractTextDocumentLayout>
#include <QColor>
#include <QDir>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QFont>
#include <QFontMetrics>
#include <QFrame>
#include <QCoreApplication>
#include <QGuiApplication>
#include <QHash>
#include <QHBoxLayout>
#include <QIcon>
#include <QInputDialog>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QPainter>
#include <QPainterPath>
#include <QPixmap>
#include <QPushButton>
#include <QRegularExpression>
#include <QScrollArea>
#include <QScrollBar>
#include <QSet>
#include <QTextBrowser>
#include <QTextDocument>
#include <QMouseEvent>
#include <QTimer>
#include <QUrl>
#include <functional>
#include <QVBoxLayout>

namespace {

QPixmap circularAvatar(const QPixmap &source, int size) {
    if (source.isNull() || size <= 0) {
        return {};
    }
    const qreal dpr = qGuiApp ? qGuiApp->devicePixelRatio() : qreal(1.0);
    const int physical = qRound(size * dpr);
    const QImage scaled = source.toImage().scaled(
        physical, physical, Qt::KeepAspectRatioByExpanding,
        Qt::SmoothTransformation);
    const int x = qMax(0, (scaled.width() - physical) / 2);
    const int y = qMax(0, (scaled.height() - physical) / 2);
    QImage rounded(physical, physical, QImage::Format_ARGB32_Premultiplied);
    rounded.fill(Qt::transparent);
    QPainter painter(&rounded);
    painter.setRenderHint(QPainter::Antialiasing, true);
    painter.setRenderHint(QPainter::SmoothPixmapTransform, true);
    QPainterPath path;
    path.addEllipse(QRectF(0, 0, physical, physical));
    painter.setClipPath(path);
    painter.drawImage(0, 0, scaled.copy(x, y, physical, physical));
    painter.end();
    QPixmap output = QPixmap::fromImage(rounded);
    output.setDevicePixelRatio(dpr);
    return output;
}

QString renderBbcode(const QString &source) {
    QString html = source.toHtmlEscaped();
    const auto flags = QRegularExpression::CaseInsensitiveOption |
                       QRegularExpression::DotMatchesEverythingOption;
    html.replace(QRegularExpression(
                     QStringLiteral("\\[youtube\\](.*?)\\[/youtube\\]"),
                     flags),
                 QStringLiteral("<a href=\"https://youtu.be/\\1\">YouTube Video</a>"));
    html.replace(QRegularExpression(
                     QStringLiteral("\\[img\\](.*?)\\[/img\\]"), flags),
                 QStringLiteral("<img src=\"\\1\">"));
    html.replace(QRegularExpression(
                     QStringLiteral("\\[url=([^\\]]+)\\](.*?)\\[/url\\]"),
                     flags),
                 QStringLiteral("<a href=\"\\1\">\\2</a>"));
    html.replace(QRegularExpression(
                     QStringLiteral("\\[color=([^\\]]+)\\](.*?)\\[/color\\]"),
                     flags),
                 QStringLiteral("<span style=\"color: \\1;\">\\2</span>"));
    html.replace(QRegularExpression(
                     QStringLiteral("\\[size=([^\\]]+)\\](.*?)\\[/size\\]"),
                     flags),
                 QStringLiteral("<span style=\"font-size: \\1%;\">\\2</span>"));
    html.replace(QRegularExpression(QStringLiteral("\\[(?:centre|center)\\]"),
                                    QRegularExpression::CaseInsensitiveOption),
                 QStringLiteral("<div align=\"center\">"));
    html.replace(QRegularExpression(QStringLiteral("\\[/(?:centre|center)\\]"),
                                    QRegularExpression::CaseInsensitiveOption),
                 QStringLiteral("</div>"));
    html.replace(QRegularExpression(QStringLiteral("\\[heading\\]"),
                                    QRegularExpression::CaseInsensitiveOption),
                 QStringLiteral("<h2>"));
    html.replace(QRegularExpression(QStringLiteral("\\[/heading\\]"),
                                    QRegularExpression::CaseInsensitiveOption),
                 QStringLiteral("</h2>"));
    const QVector<QPair<QString, QString>> simple = {
        {QStringLiteral("b"), QStringLiteral("b")},
        {QStringLiteral("i"), QStringLiteral("i")},
        {QStringLiteral("u"), QStringLiteral("u")},
        {QStringLiteral("s"), QStringLiteral("s")},
    };
    for (const auto &tag : simple) {
        html.replace(QRegularExpression(
                         QStringLiteral("\\[%1\\](.*?)\\[/%1\\]")
                             .arg(tag.first),
                         flags),
                     QStringLiteral("<%1>\\1</%1>").arg(tag.second));
    }
    html.remove(QRegularExpression(QStringLiteral("\\[[^\\]]+\\]")));
    return html.replace(QStringLiteral("\r\n"), QStringLiteral("\n"))
        .replace(QStringLiteral("\n"), QStringLiteral("<br>"));
}



} // namespace

class ProfileAvatarButton : public QWidget {
public:
    explicit ProfileAvatarButton(QWidget *parent = nullptr) : QWidget(parent) {
        setFixedSize(96, 96);
        setCursor(Qt::PointingHandCursor);
        setAttribute(Qt::WA_Hover, true);
    }

    std::function<void()> onClick;

    void setAvatar(const QPixmap &avatar) {
        m_avatar = avatar;
        update();
    }

protected:
    void enterEvent(QEnterEvent *event) override {
        m_hovered = true;
        update();
        QWidget::enterEvent(event);
    }

    void leaveEvent(QEvent *event) override {
        m_hovered = false;
        update();
        QWidget::leaveEvent(event);
    }

    void mousePressEvent(QMouseEvent *event) override {
        if (event->button() == Qt::LeftButton && onClick) {
            onClick();
        }
        QWidget::mousePressEvent(event);
    }

    void paintEvent(QPaintEvent *) override {
        QPainter painter(this);
        painter.setRenderHint(QPainter::Antialiasing, true);
        painter.setRenderHint(QPainter::SmoothPixmapTransform, true);
        const QRectF rect = QRectF(0, 0, width(), height());
        QPainterPath circle;
        circle.addEllipse(rect);
        painter.setClipPath(circle);
        if (!m_avatar.isNull()) {
            painter.drawPixmap(rect.toRect(), m_avatar);
        } else {
            painter.fillRect(rect, QColor(46, 46, 56));
            const QPixmap user =
                IconUtils::tinted(QStringLiteral("user.svg"),
                                  QColor(185, 185, 205), 48)
                    .pixmap(48, 48);
            painter.drawPixmap(width() / 2 - 24, height() / 2 - 24, user);
        }
        if (m_hovered) {
            painter.fillRect(rect, QColor(0, 0, 0, 150));
            if (m_pencil.isNull()) {
                m_pencil = IconUtils::tinted(QStringLiteral("pencil.svg"),
                                             QColor(Qt::white), 16)
                               .pixmap(16, 16);
            }
            painter.drawPixmap(width() / 2 - 8, height() / 2 - 22, m_pencil);
            QFont font = painter.font();
            font.setPixelSize(10);
            font.setBold(true);
            painter.setFont(font);
            painter.setPen(Qt::white);
            painter.drawText(QRect(0, height() / 2 + 2, width(), 16),
                             Qt::AlignHCenter | Qt::AlignTop,
                             QCoreApplication::translate("ProfilePage",
                                                         "Change"));
        }
        painter.end();
    }

private:
    QPixmap m_avatar;
    QPixmap m_pencil;
    bool m_hovered = false;
};

class ProfileBannerButton : public QWidget {
public:
    explicit ProfileBannerButton(QWidget *parent = nullptr) : QWidget(parent) {
        setCursor(Qt::PointingHandCursor);
        setAttribute(Qt::WA_Hover, true);
        setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Fixed);
        setMinimumWidth(0);
    }

    std::function<void()> onClick;

    void setBanner(const QPixmap &banner) {
        m_banner = banner;
        update();
    }

protected:
    void enterEvent(QEnterEvent *event) override {
        m_hovered = true;
        update();
        QWidget::enterEvent(event);
    }

    void leaveEvent(QEvent *event) override {
        m_hovered = false;
        update();
        QWidget::leaveEvent(event);
    }

    void mousePressEvent(QMouseEvent *event) override {
        if (event->button() == Qt::LeftButton && onClick) {
            onClick();
        }
        QWidget::mousePressEvent(event);
    }

    void paintEvent(QPaintEvent *) override {
        QPainter painter(this);
        painter.setRenderHint(QPainter::Antialiasing, true);
        painter.setRenderHint(QPainter::SmoothPixmapTransform, true);
        const QRectF rect = QRectF(0, 0, width(), height());
        QPainterPath clip;
        clip.addRoundedRect(rect, 12, 12);
        painter.setClipPath(clip);
        if (!m_banner.isNull()) {
            const qreal dpr =
                qGuiApp ? qGuiApp->devicePixelRatio() : qreal(1.0);
            const QSize target(qRound(width() * dpr), qRound(height() * dpr));
            const QImage scaled = m_banner.toImage().scaled(
                target, Qt::KeepAspectRatioByExpanding,
                Qt::SmoothTransformation);
            const int x = qMax(0, (scaled.width() - target.width()) / 2);
            const int y = qMax(0, (scaled.height() - target.height()) / 2);
            painter.drawImage(rect, scaled.copy(x, y, target.width(),
                                                target.height()));
        } else {
            QLinearGradient gradient(rect.topLeft(), rect.bottomRight());
            gradient.setColorAt(0.0, QColor(0x24, 0x24, 0x3a));
            gradient.setColorAt(1.0, QColor(0x35, 0x2a, 0x3f));
            painter.fillRect(rect, gradient);
        }
        if (m_hovered) {
            painter.fillRect(rect, QColor(0, 0, 0, 130));
            if (m_pencil.isNull()) {
                m_pencil = IconUtils::tinted(QStringLiteral("pencil.svg"),
                                             QColor(Qt::white), 20)
                               .pixmap(20, 20);
            }
            QFont font = painter.font();
            font.setPixelSize(13);
            font.setBold(true);
            painter.setFont(font);
            painter.setPen(Qt::white);
            const QString text = QCoreApplication::translate(
                "ProfilePage", "Change banner");
            const int textWidth = QFontMetrics(font).horizontalAdvance(text);
            const int gap = 8;
            const int total = 20 + gap + textWidth;
            const int startX = width() / 2 - total / 2;
            const int centerY = height() / 2;
            painter.drawPixmap(startX, centerY - 10, m_pencil);
            painter.drawText(startX + 20 + gap, centerY - 10, textWidth, 20,
                             Qt::AlignLeft | Qt::AlignVCenter, text);
        }
        painter.end();
    }

private:
    QPixmap m_banner;
    QPixmap m_pencil;
    bool m_hovered = false;
};

class ProfileNameWidget : public QWidget {
public:
    explicit ProfileNameWidget(QWidget *parent = nullptr) : QWidget(parent) {
        setCursor(Qt::PointingHandCursor);
        setAttribute(Qt::WA_Hover, true);
        auto *layout = new QHBoxLayout(this);
        layout->setContentsMargins(0, 0, 0, 0);
        layout->setSpacing(8);
        label = new QLabel(this);
        label->setObjectName(QStringLiteral("profileNickname"));
        label->setAttribute(Qt::WA_TransparentForMouseEvents, true);
        pencil = new QLabel(this);
        pencil->setAttribute(Qt::WA_TransparentForMouseEvents, true);
        pencil->hide();
        layout->addWidget(label);
        layout->addWidget(pencil);
        layout->addStretch(1);
    }

    std::function<void()> onClick;
    QLabel *label = nullptr;
    QLabel *pencil = nullptr;

    void setText(const QString &text) { label->setText(text); }
    QString text() const { return label->text(); }
    void setPencil(const QPixmap &icon) { pencil->setPixmap(icon); }

protected:
    void enterEvent(QEnterEvent *event) override {
        pencil->show();
        QWidget::enterEvent(event);
    }

    void leaveEvent(QEvent *event) override {
        pencil->hide();
        QWidget::leaveEvent(event);
    }

    void mousePressEvent(QMouseEvent *event) override {
        if (event->button() == Qt::LeftButton && onClick) {
            onClick();
        }
        QWidget::mousePressEvent(event);
    }
};

class ProfileTextBrowser : public QTextBrowser {
public:
    explicit ProfileTextBrowser(QWidget *parent = nullptr)
        : QTextBrowser(parent) {
        setFrameShape(QFrame::NoFrame);
        setVerticalScrollBarPolicy(Qt::ScrollBarAsNeeded);
        setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        setOpenExternalLinks(true);
        setReadOnly(true);
        setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Fixed);
        setMinimumWidth(0);
        setMaximumHeight(MaxHeight);
        setStyleSheet(QStringLiteral(
            "QTextBrowser { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 8px;"
            " margin: 0; }"
            "QScrollBar::handle:vertical {"
            " background: #b4b4c3; border-radius: 4px; min-height: 24px; }"
            "QScrollBar::handle:vertical:hover { background: #d7d7e6; }"
            "QScrollBar::add-line:vertical,"
            "QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical,"
            "QScrollBar::sub-page:vertical { background: transparent; }"));
        QPalette pal = palette();
        pal.setColor(QPalette::Base, Qt::transparent);
        setPalette(pal);
        viewport()->setAutoFillBackground(false);
        m_network = new QNetworkAccessManager(this);
    }

    QSize sizeHint() const override { return QSize(1, height()); }

    QSize minimumSizeHint() const override { return QSize(1, 1); }

    std::function<void()> onDoubleClick;

    void setDescription(const QString &description) {
        m_html = renderBbcode(description);
        m_images.clear();
        m_failed.clear();
        m_loading.clear();
        render();
    }

protected:
    QVariant loadResource(int type, const QUrl &url) override {
        if (type != QTextDocument::ImageResource) {
            return QTextBrowser::loadResource(type, url);
        }
        const QString key = url.toString();
        if (m_images.contains(key)) {
            return scaledImage(m_images.value(key));
        }
        if (m_failed.contains(key)) {
            return {};
        }
        if (url.scheme().compare(QStringLiteral("http"),
                                 Qt::CaseInsensitive) == 0 ||
            url.scheme().compare(QStringLiteral("https"),
                                 Qt::CaseInsensitive) == 0) {
            if (!m_loading.contains(key) && m_network) {
                m_loading.insert(key);
                QNetworkReply *reply = m_network->get(QNetworkRequest(url));
                connect(reply, &QNetworkReply::finished, this,
                        [this, key, reply] {
                            const QByteArray data = reply->readAll();
                            QImage image;
                            if (!data.isEmpty() &&
                                image.loadFromData(data) &&
                                !image.isNull()) {
                                m_images.insert(key, image);
                            } else {
                                m_failed.insert(key);
                            }
                            m_loading.remove(key);
                            render();
                            reply->deleteLater();
                        });
            }
            return transparentImage();
        }
        const QString local =
            url.isLocalFile() ? url.toLocalFile() : url.toString();
        if (!local.isEmpty()) {
            QImage image(local);
            if (!image.isNull()) {
                m_images.insert(key, image);
                return scaledImage(image);
            }
        }
        return QTextBrowser::loadResource(type, url);
    }

    void mouseDoubleClickEvent(QMouseEvent *event) override {
        if (event->button() == Qt::LeftButton && onDoubleClick) {
            onDoubleClick();
            event->accept();
            return;
        }
        QTextBrowser::mouseDoubleClickEvent(event);
    }

    void resizeEvent(QResizeEvent *event) override {
        QTextBrowser::resizeEvent(event);
        if (m_html.isEmpty()) {
            return;
        }
        const int width = viewport()->width();
        if (width > 0 && qAbs(width - m_lastWidth) > 4) {
            const int position = verticalScrollBar()->value();
            render();
            verticalScrollBar()->setValue(position);
        }
    }

private:
    static constexpr int MaxHeight = 450;

    static QImage transparentImage() {
        QImage image(1, 1, QImage::Format_ARGB32_Premultiplied);
        image.fill(Qt::transparent);
        return image;
    }

    QVariant scaledImage(const QImage &image) const {
        const int available = viewport()->width() - 32;
        if (available > 0 && image.width() != available) {
            return QVariant::fromValue(
                image.scaledToWidth(available, Qt::SmoothTransformation));
        }
        return QVariant::fromValue(image);
    }

    void render() {
        if (m_rendering) {
            return;
        }
        m_rendering = true;
        const int position = verticalScrollBar()->value();
        const int width = viewport()->width();
        m_lastWidth = width;
        setHtml(m_html);
        syncHeight();
        if (position > 0) {
            verticalScrollBar()->setValue(position);
        }
        m_rendering = false;
    }

    void syncHeight() {
        if (viewport()->width() <= 0 || m_syncPending) {
            return;
        }
        m_syncPending = true;
        QTimer::singleShot(0, this, [this] {
            m_syncPending = false;
            if (viewport()->width() <= 0) {
                return;
            }
            const int documentHeight =
                qCeil(document()->size().height()) + frameWidth() * 2;
            const int targetHeight = qBound(1, documentHeight, MaxHeight);
            if (this->height() != targetHeight) {
                setFixedHeight(targetHeight);
            }
        });
    }

    QNetworkAccessManager *m_network = nullptr;
    QHash<QString, QImage> m_images;
    QSet<QString> m_loading;
    QSet<QString> m_failed;
    QString m_html;
    int m_lastWidth = 0;
    bool m_syncPending = false;
    bool m_rendering = false;
};

ProfilePage::ProfilePage(CoreClient *core,
                         const QString &dataDir,
                         QWidget *parent)
    : QWidget(parent), m_core(core), m_dataDir(dataDir) {
    auto *outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);

    auto *scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    auto *content = new QWidget(scroll);
    auto *layout = new QVBoxLayout(content);
    layout->setContentsMargins(24, 18, 24, 24);
    layout->setSpacing(14);

    m_banner = new ProfileBannerButton(content);
    m_banner->setObjectName(QStringLiteral("profileBanner"));
    m_banner->setFixedHeight(150);
    m_banner->onClick = [this] { changeBanner(); };
    layout->addWidget(m_banner);

    auto *header = new QHBoxLayout();
    header->setSpacing(16);
    m_avatar = new ProfileAvatarButton(content);
    m_avatar->onClick = [this] { changeAvatar(); };
    header->addWidget(m_avatar, 0, Qt::AlignTop);

    auto *nameColumn = new QVBoxLayout();
    nameColumn->setSpacing(6);
    m_nickname = new ProfileNameWidget(content);
    m_nickname->onClick = [this] { editNickname(); };
    QFont nicknameFont = m_nickname->label->font();
    nicknameFont.setBold(true);
    nicknameFont.setPixelSize(26);
    m_nickname->label->setFont(nicknameFont);
    m_nickname->label->setStyleSheet(
        QStringLiteral("font-size: 26px; font-weight: 700;"));
    m_nickname->setPencil(
        IconUtils::tinted(QStringLiteral("pencil.svg"), Theme::iconColor(),
                          16)
            .pixmap(16, 16));
    nameColumn->addWidget(m_nickname);

    header->addLayout(nameColumn, 1);

    m_achievements = new QWidget(content);
    m_achievementsLayout = new QHBoxLayout(m_achievements);
    m_achievementsLayout->setContentsMargins(0, 0, 0, 0);
    m_achievementsLayout->setSpacing(12);
    header->addWidget(m_achievements, 0, Qt::AlignTop);
    layout->addLayout(header);

    auto *aboutTitle = new QLabel(tr("About Me"), content);
    aboutTitle->setObjectName(QStringLiteral("profileSectionTitle"));
    QFont sectionFont = aboutTitle->font();
    sectionFont.setBold(true);
    aboutTitle->setFont(sectionFont);
    layout->addWidget(aboutTitle);
    m_about = new ProfileTextBrowser(content);
    m_about->setObjectName(QStringLiteral("profileAbout"));
    m_about->setToolTip(tr("Double-click to edit About Me"));
    m_about->onDoubleClick = [this] { editAbout(); };
    layout->addWidget(m_about);
    auto *aboutButton = new QPushButton(tr("Edit About Me"), content);
    aboutButton->setCursor(Qt::PointingHandCursor);
    layout->addWidget(aboutButton, 0, Qt::AlignLeft);

    auto *favoriteTitle = new QLabel(tr("Favorite Track"), content);
    favoriteTitle->setObjectName(QStringLiteral("profileSectionTitle"));
    favoriteTitle->setFont(sectionFont);
    layout->addWidget(favoriteTitle);
    m_favorite = new QLabel(content);
    m_favorite->setObjectName(QStringLiteral("profileFavorite"));
    m_favorite->setWordWrap(true);
    layout->addWidget(m_favorite);

    auto *topTitle = new QLabel(tr("Top Tracks"), content);
    topTitle->setObjectName(QStringLiteral("profileSectionTitle"));
    topTitle->setFont(sectionFont);
    layout->addWidget(topTitle);
    m_topTracks = new QListWidget(content);
    m_topTracks->setObjectName(QStringLiteral("profileTopTracks"));
    m_topTracks->setIconSize(QSize(36, 36));
    m_topTracks->setMaximumHeight(260);
    layout->addWidget(m_topTracks);

    auto *publicTitle = new QLabel(tr("Public Playlists"), content);
    publicTitle->setObjectName(QStringLiteral("profileSectionTitle"));
    publicTitle->setFont(sectionFont);
    layout->addWidget(publicTitle);
    m_publicPlaylists = new QListWidget(content);
    m_publicPlaylists->setObjectName(QStringLiteral("profilePlaylists"));
    m_publicPlaylists->setViewMode(QListView::IconMode);
    m_publicPlaylists->setResizeMode(QListView::Adjust);
    m_publicPlaylists->setMovement(QListView::Static);
    m_publicPlaylists->setIconSize(QSize(92, 92));
    m_publicPlaylists->setGridSize(QSize(118, 126));
    m_publicPlaylists->setMaximumHeight(150);
    layout->addWidget(m_publicPlaylists);

    layout->addStretch(1);
    scroll->setWidget(content);
    outer->addWidget(scroll);

    connect(aboutButton, &QPushButton::clicked, this, &ProfilePage::editAbout);
    connect(m_topTracks, &QListWidget::itemDoubleClicked, this,
            [this](QListWidgetItem *item) {
                if (item) {
                    emit playRequested(item->data(Qt::UserRole).toLongLong());
                }
            });
    connect(m_publicPlaylists, &QListWidget::itemDoubleClicked, this,
            [this](QListWidgetItem *item) {
                if (item) {
                    emit playlistRequested(item->data(Qt::UserRole).toLongLong());
                }
            });

    reload();
}

void ProfilePage::fillAchievements(const ProfileData &data) {
    while (QLayoutItem *item = m_achievementsLayout->takeAt(0)) {
        if (QWidget *widget = item->widget()) {
            widget->deleteLater();
        }
        delete item;
    }

    struct Achievement {
        QString icon;
        QVector<qint64> thresholds;
        QString caption;
        qint64 value;
        bool time;
    };
    const QVector<Achievement> achievements = {
        {QStringLiteral("count.svg"),
         {100, 500, 1000, 2000},
         tr("Tracks downloaded"),
         data.tracks,
         false},
        {QStringLiteral("create-playlist.svg"),
         {5, 10, 25, 50},
         tr("Playlists created"),
         data.playlistsCount,
         false},
        {QStringLiteral("time.svg"),
         {3600, 36000, 180000, 360000},
         tr("Listening time"),
         data.listeningSeconds,
         true},
        {QStringLiteral("favorite.svg"),
         {30, 90, 180, 365},
         tr("Library age"),
         data.appAgeDays,
         false},
    };
    static const QColor colors[] = {
        QColor(0xcd, 0x7f, 0x32), QColor(0xc0, 0xc0, 0xc0),
        QColor(0xff, 0xd7, 0x00), QColor(0x7f, 0xdf, 0xff)};
    static const QStringList tiers = {
        tr("Bronze"), tr("Silver"), tr("Gold"), tr("Diamond")};
    for (const Achievement &achievement : achievements) {
        int level = 0;
        for (qint64 threshold : achievement.thresholds) {
            if (achievement.value >= threshold) {
                ++level;
            } else {
                break;
            }
        }
        const QColor color = level > 0 ? colors[level - 1]
                                       : QColor(0x5a, 0x5a, 0x5a);
        const auto formatted = [&achievement](qint64 value) {
            return achievement.time
                       ? QStringLiteral("%1h").arg(value / 3600)
                       : QString::number(value);
        };
        const QString shown = formatted(achievement.value);
        QString tooltip;
        if (level >= achievement.thresholds.size()) {
            tooltip = QStringLiteral("%1: %2 — %3")
                          .arg(achievement.caption, shown,
                               tiers.at(level - 1));
        } else {
            tooltip = QStringLiteral("%1: %2 / %3")
                          .arg(achievement.caption, shown,
                               formatted(achievement.thresholds.at(level)));
        }

        auto *box = new QWidget(m_achievements);
        box->setToolTip(tooltip);
        auto *column = new QVBoxLayout(box);
        column->setContentsMargins(0, 0, 0, 0);
        column->setSpacing(2);
        auto *icon = new QLabel(box);
        icon->setAlignment(Qt::AlignCenter);
        icon->setPixmap(
            IconUtils::tinted(achievement.icon, color, 28).pixmap(28, 28));
        column->addWidget(icon);
        auto *value = new QLabel(shown, box);
        value->setAlignment(Qt::AlignCenter);
        QFont valueFont = value->font();
        valueFont.setPixelSize(10);
        value->setFont(valueFont);
        value->setStyleSheet(QStringLiteral("color: #8a8a8a;"));
        column->addWidget(value);
        m_achievementsLayout->addWidget(box);
    }
}

void ProfilePage::reload() {
    if (!m_core) {
        return;
    }
    const ProfileData data = m_core->profile();
    m_nickname->setText(data.nickname.isEmpty() ? tr("Music Lover") : data.nickname);
    fillAchievements(data);
    m_description = data.description;
    m_about->setDescription(data.description.isEmpty()
                                ? tr("No description yet.")
                                : data.description);

    QPixmap avatar;
    if (!data.avatarPath.isEmpty()) {
        avatar.load(data.avatarPath);
    }
    if (avatar.isNull()) {
        avatar = IconUtils::tinted(QStringLiteral("user.svg"),
                                   QColor(185, 185, 205), 96)
                     .pixmap(96, 96);
    }
    setAvatarPixmap(avatar);

    QPixmap banner;
    if (!data.bannerPath.isEmpty()) {
        banner.load(data.bannerPath);
    }
    setBannerPixmap(banner);

    if (data.hasFavorite) {
        m_favorite->setText(QStringLiteral("%1 — %2")
                                .arg(data.favorite.title.isEmpty() ? tr("Unknown title")
                                                                   : data.favorite.title)
                                .arg(data.favorite.artist.isEmpty() ? tr("Unknown artist")
                                                                    : data.favorite.artist));
    } else {
        m_favorite->setText(tr("No favorite track yet."));
    }

    m_publicPlaylists->clear();
    for (const Playlist &playlist : data.playlists) {
        QString coverPath = playlist.coverPath;
        if (coverPath.isEmpty() && m_core) {
            const QVector<Track> tracks = m_core->playlistTracks(playlist.id);
            if (!tracks.isEmpty()) {
                coverPath = tracks.first().coverPath;
            }
        }
        const QPixmap cover = CoverCache::cover(coverPath, 92);
        QIcon icon;
        if (!cover.isNull()) {
            icon = QIcon(cover);
        } else {
            QPixmap placeholder(92, 92);
            placeholder.fill(QColor(38, 38, 42));
            QPainter painter(&placeholder);
            painter.setPen(QColor(210, 210, 220));
            QFont font = painter.font();
            font.setPointSize(26);
            font.setBold(true);
            painter.setFont(font);
            painter.drawText(placeholder.rect(), Qt::AlignCenter,
                             playlist.name.left(1).toUpper());
            icon = QIcon(placeholder);
        }
        auto *item = new QListWidgetItem(icon, playlist.name, m_publicPlaylists);
        item->setData(Qt::UserRole, playlist.id);
        item->setTextAlignment(Qt::AlignHCenter | Qt::AlignBottom);
        item->setSizeHint(QSize(108, 120));
    }

    m_topTracks->clear();
    for (const Track &track : data.topTracks) {
        auto *item = new QListWidgetItem(m_topTracks);
        item->setData(Qt::UserRole, track.id);
        item->setText((track.title.isEmpty() ? tr("Unknown title") : track.title) +
                      QStringLiteral(" — ") +
                      (track.artist.isEmpty() ? tr("Unknown artist") : track.artist));
        item->setSizeHint(QSize(0, 46));
        if (!track.coverPath.isEmpty()) {
            const QPixmap cover = CoverCache::cover(track.coverPath, 36);
            if (!cover.isNull()) {
                item->setIcon(QIcon(cover));
            }
        }
    }
}

void ProfilePage::setAvatarPixmap(const QPixmap &source) {
    m_avatar->setAvatar(circularAvatar(source, 96));
}

void ProfilePage::setBannerPixmap(const QPixmap &source) {
    m_banner->setBanner(source);
}

void ProfilePage::changeAvatar() {
    const QString source = QFileDialog::getOpenFileName(
        this, tr("Choose avatar"), QString(),
        QStringLiteral("Images (*.png *.jpg *.jpeg *.webp *.gif)"));
    if (source.isEmpty()) {
        return;
    }
    QDir().mkpath(QDir(m_dataDir).filePath(QStringLiteral("profile")));
    const QString suffix = QFileInfo(source).suffix();
    const QString target = QDir(m_dataDir).filePath(
        QStringLiteral("profile/avatar.") + (suffix.isEmpty() ? QStringLiteral("png") : suffix));
    QFile::remove(target);
    if (!QFile::copy(source, target)) {
        return;
    }
    if (m_core) {
        m_core->setProfileField(QStringLiteral("avatar_path"), target);
    }
    reload();
    emit avatarChanged();
}

void ProfilePage::changeBanner() {
    const QString source = QFileDialog::getOpenFileName(
        this, tr("Choose banner"), QString(),
        QStringLiteral("Images (*.png *.jpg *.jpeg *.webp *.gif)"));
    if (source.isEmpty()) {
        return;
    }
    QDir().mkpath(QDir(m_dataDir).filePath(QStringLiteral("profile")));
    const QString suffix = QFileInfo(source).suffix();
    const QString target = QDir(m_dataDir).filePath(
        QStringLiteral("profile/banner.") + (suffix.isEmpty() ? QStringLiteral("png") : suffix));
    QFile::remove(target);
    if (!QFile::copy(source, target)) {
        return;
    }
    if (m_core) {
        m_core->setProfileField(QStringLiteral("banner_path"), target);
    }
    reload();
}

void ProfilePage::editNickname() {
    if (!m_core) {
        return;
    }
    bool ok = false;
    const QString value = QInputDialog::getText(
        this, tr("Edit name"), tr("Nickname:"), QLineEdit::Normal,
        m_nickname->text(), &ok);
    if (ok && !value.trimmed().isEmpty()) {
        m_core->setProfileField(QStringLiteral("nickname"), value.trimmed());
        reload();
    }
}

void ProfilePage::editAbout() {
    if (!m_core) {
        return;
    }
    bool ok = false;
    const QString value = QInputDialog::getMultiLineText(
        this, tr("Edit About Me"), tr("Tell something about yourself:"),
        m_description, &ok);
    if (ok) {
        m_core->setProfileField(QStringLiteral("description"), value);
        reload();
    }
}
