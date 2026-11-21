#include "TitleBar.h"

#include "IconUtils.h"

#include <QColor>
#include <QFont>
#include <QHBoxLayout>
#include <QLabel>
#include <QMouseEvent>
#include <QPixmap>
#include <QToolButton>
#include <QWindow>

TitleBar::TitleBar(QWidget *parent) : QWidget(parent) {
    setObjectName(QStringLiteral("titleBar"));
    setFixedHeight(44);

    auto *layout = new QHBoxLayout(this);
    layout->setContentsMargins(18, 0, 10, 0);
    layout->setSpacing(6);

    auto *logo = new QLabel(this);
    logo->setObjectName(QStringLiteral("titleLogo"));
    logo->setFixedSize(26, 26);
    const QPixmap logoPixmap = IconUtils::logo(24);
    if (!logoPixmap.isNull()) {
        logo->setPixmap(logoPixmap);
    }
    logo->setAlignment(Qt::AlignCenter);
    layout->addWidget(logo);

    m_title = new QLabel(QStringLiteral("OctoBeat"), this);
    m_title->setObjectName(QStringLiteral("appTitle"));
    QFont font = m_title->font();
    font.setBold(true);
    font.setPointSize(font.pointSize() + 2);
    m_title->setFont(font);
    layout->addWidget(m_title);
    layout->addStretch(1);

    auto makeButton = [this](const QString &text, const QString &name) {
        auto *button = new QToolButton(this);
        button->setObjectName(name);
        button->setText(text);
        button->setFixedSize(34, 30);
        button->setCursor(Qt::PointingHandCursor);
        button->setAutoRaise(true);
        return button;
    };

    auto *mini = makeButton(QString(), QStringLiteral("titleMini"));
    mini->setIcon(IconUtils::tinted(QStringLiteral("expand.svg"),
                                    QColor(205, 205, 215), 18));
    mini->setIconSize(QSize(15, 15));
    mini->setToolTip(tr("Mini player"));
    auto *minimize = makeButton(QStringLiteral("—"), QStringLiteral("titleMinimize"));
    auto *maximize = makeButton(QStringLiteral("□"), QStringLiteral("titleMaximize"));
    auto *close = makeButton(QStringLiteral("×"), QStringLiteral("titleClose"));
    layout->addWidget(mini);
    layout->addWidget(minimize);
    layout->addWidget(maximize);
    layout->addWidget(close);

    connect(mini, &QToolButton::clicked, this, &TitleBar::miniPlayerRequested);
    connect(minimize, &QToolButton::clicked, this, [this] {
        if (window()) {
            window()->showMinimized();
        }
    });
    connect(maximize, &QToolButton::clicked, this, [this] {
        if (!window()) {
            return;
        }
        if (window()->isMaximized()) {
            window()->showNormal();
        } else {
            window()->showMaximized();
        }
    });
    connect(close, &QToolButton::clicked, this, [this] {
        if (window()) {
            window()->close();
        }
    });
}

void TitleBar::mousePressEvent(QMouseEvent *event) {
    if (event->button() == Qt::LeftButton && window()) {
        if (QWindow *handle = window()->windowHandle()) {
            handle->startSystemMove();
        }
        event->accept();
        return;
    }
    QWidget::mousePressEvent(event);
}

void TitleBar::mouseDoubleClickEvent(QMouseEvent *event) {
    if (event->button() == Qt::LeftButton && window()) {
        if (window()->isMaximized()) {
            window()->showNormal();
        } else {
            window()->showMaximized();
        }
        event->accept();
        return;
    }
    QWidget::mouseDoubleClickEvent(event);
}
