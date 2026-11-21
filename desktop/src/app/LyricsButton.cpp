#include "LyricsButton.h"

#include <QMouseEvent>

LyricsButton::LyricsButton(QWidget *parent) : QPushButton(parent) {}

void LyricsButton::mouseDoubleClickEvent(QMouseEvent *event) {
    // Swallow the event: otherwise the base button emits an extra clicked()
    // and the lyrics panel flashes before karaoke opens.
    if (event->button() == Qt::LeftButton) {
        emit doubleClicked();
        event->accept();
        return;
    }
    QPushButton::mouseDoubleClickEvent(event);
}
