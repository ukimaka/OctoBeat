#pragma once

#include <QDialog>
#include <QSet>
#include <QVector>

#include "core/CoreClient.h"

class QListWidget;
class QPushButton;

class AddTracksDialog : public QDialog {
    Q_OBJECT

public:
    AddTracksDialog(const QVector<Track> &tracks,
                    const QSet<qint64> &existingIds,
                    QWidget *parent = nullptr);

    QVector<qint64> selectedTrackIds() const;

private:
    void updateConfirmState();

    QListWidget *m_list = nullptr;
    QPushButton *m_confirm = nullptr;
};
