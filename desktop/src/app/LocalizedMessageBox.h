#pragma once

#include <QMessageBox>
#include <QString>
#include <QWidget>

namespace LocalizedMessageBox {

QMessageBox::StandardButton question(
    QWidget *parent,
    const QString &title,
    const QString &text,
    QMessageBox::StandardButtons buttons = QMessageBox::Yes | QMessageBox::No,
    QMessageBox::StandardButton defaultButton = QMessageBox::No);

void warning(QWidget *parent, const QString &title, const QString &text);
void information(QWidget *parent, const QString &title, const QString &text);

} // namespace LocalizedMessageBox
