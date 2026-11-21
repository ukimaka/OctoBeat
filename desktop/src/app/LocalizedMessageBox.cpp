#include "LocalizedMessageBox.h"

#include <QAbstractButton>
#include <QCoreApplication>

namespace {

void localizeButtons(QMessageBox &box) {
    const auto setText = [&box](QMessageBox::StandardButton button,
                                const char *source) {
        if (QAbstractButton *widget = box.button(button)) {
            widget->setText(QCoreApplication::translate("QMessageBox", source));
        }
    };
    setText(QMessageBox::Yes, "Yes");
    setText(QMessageBox::No, "No");
    setText(QMessageBox::Ok, "OK");
    setText(QMessageBox::Cancel, "Cancel");
    setText(QMessageBox::Save, "Save");
    setText(QMessageBox::Discard, "Discard");
    setText(QMessageBox::Close, "Close");
}

} // namespace

namespace LocalizedMessageBox {

QMessageBox::StandardButton question(
    QWidget *parent,
    const QString &title,
    const QString &text,
    QMessageBox::StandardButtons buttons,
    QMessageBox::StandardButton defaultButton) {
    QMessageBox box(QMessageBox::Question, title, text,
                    QMessageBox::NoButton, parent);
    box.setStandardButtons(buttons);
    if (defaultButton != QMessageBox::NoButton) {
        box.setDefaultButton(defaultButton);
    }
    localizeButtons(box);
    return static_cast<QMessageBox::StandardButton>(box.exec());
}

void warning(QWidget *parent, const QString &title, const QString &text) {
    QMessageBox box(QMessageBox::Warning, title, text,
                    QMessageBox::NoButton, parent);
    box.setStandardButtons(QMessageBox::Ok);
    localizeButtons(box);
    box.exec();
}

void information(QWidget *parent, const QString &title, const QString &text) {
    QMessageBox box(QMessageBox::Information, title, text,
                    QMessageBox::NoButton, parent);
    box.setStandardButtons(QMessageBox::Ok);
    localizeButtons(box);
    box.exec();
}

} // namespace LocalizedMessageBox
