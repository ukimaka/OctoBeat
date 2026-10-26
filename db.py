# OctoBeat - музыкальный плеер
# Copyright (C) 2026 ukimaka
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Слой данных: работа с SQLite. Никакого PyQt здесь нет."""

import sqlite3
from contextlib import closing
from pathlib import Path

DB_FILE = Path(__file__).parent / "music.db"


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    # Записи из фонового потока (например, LyricsWorker) не должны падать с
    # «database is locked», пока главный поток читает библиотеку.
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создаёт таблицы, если их нет. И мигрирует старые схемы."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS folders (
                id     INTEGER PRIMARY KEY,
                name   TEXT UNIQUE NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tracks (
                id            INTEGER PRIMARY KEY,
                file_path     TEXT UNIQUE NOT NULL,
                title         TEXT,
                artist        TEXT,
                album         TEXT,
                duration      INTEGER,
                loudness      REAL,
                folder_id     INTEGER REFERENCES folders(id) ON DELETE SET NULL,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                lyrics_synced TEXT,
                lyrics_plain  TEXT,
                lyrics_checked INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS playlists (
                id           INTEGER PRIMARY KEY,
                name         TEXT UNIQUE NOT NULL,
                cover_path   TEXT,
                description  TEXT,
                is_pinned    INTEGER DEFAULT 0,
                position     INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS playlist_tracks (
                playlist_id  INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                track_id     INTEGER NOT NULL REFERENCES tracks(id)    ON DELETE CASCADE,
                added_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (playlist_id, track_id)
            );

            CREATE TABLE IF NOT EXISTS profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                nickname TEXT DEFAULT 'Music Lover',
                avatar_path TEXT,
                banner_path TEXT,
                description TEXT,
                favorite_track_id INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
                listening_seconds INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS play_history (
                id INTEGER PRIMARY KEY,
                track_id INTEGER REFERENCES tracks(id) ON DELETE CASCADE,
                played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS playlist_visibility (
                playlist_id INTEGER PRIMARY KEY,
                is_public   INTEGER DEFAULT 0
            );
        """)

        # Миграция: добавляем loudness, если её нет в старой базе
        cols = [row[1] for row in conn.execute("PRAGMA table_info(tracks)").fetchall()]
        if "loudness" not in cols:
            conn.execute("ALTER TABLE tracks ADD COLUMN loudness REAL")
        if "folder_id" not in cols:
            conn.execute(
                "ALTER TABLE tracks ADD COLUMN folder_id INTEGER "
                "REFERENCES folders(id) ON DELETE SET NULL"
            )
        # Миграция: тексты песен (синхронизированный LRC и обычный текст)
        if "lyrics_synced" not in cols:
            conn.execute("ALTER TABLE tracks ADD COLUMN lyrics_synced TEXT")
        if "lyrics_plain" not in cols:
            conn.execute("ALTER TABLE tracks ADD COLUMN lyrics_plain TEXT")
        if "lyrics_checked" not in cols:
            conn.execute(
                "ALTER TABLE tracks ADD COLUMN lyrics_checked INTEGER DEFAULT 0"
            )
            # Старые версии сохраняли пустые строки даже при сетевом сбое,
            # из-за чего текст «пропадал» навсегда. Уже найденные тексты
            # помечаем проверенными, а пустые — оставляем непроверенными,
            # чтобы при следующем воспроизведении они загрузились заново.
            conn.execute(
                "UPDATE tracks SET lyrics_checked = 1 "
                "WHERE length(COALESCE(lyrics_synced, '')) > 0 "
                "   OR length(COALESCE(lyrics_plain, '')) > 0"
            )
        # Миграция: дата добавления трека (для достижения «возраст»)
        if "created_at" not in cols:
            # CURRENT_TIMESTAMP в ALTER TABLE запрещён, если в таблице есть
            # строки, поэтому добавляем без DEFAULT и заполняем вручную.
            conn.execute("ALTER TABLE tracks ADD COLUMN created_at TIMESTAMP")
            conn.execute(
                "UPDATE tracks SET created_at = CURRENT_TIMESTAMP "
                "WHERE created_at IS NULL"
            )

        # Миграция: добавляем added_at, если её нет в старой базе
        cols = [row[1] for row in conn.execute("PRAGMA table_info(playlist_tracks)").fetchall()]
        if "added_at" not in cols:
            # CURRENT_TIMESTAMP в ALTER TABLE запрещён, если в таблице есть строки,
            # поэтому добавляем без DEFAULT и заполняем существующие вручную.
            conn.execute("ALTER TABLE playlist_tracks ADD COLUMN added_at TIMESTAMP")
            conn.execute(
                "UPDATE playlist_tracks SET added_at = CURRENT_TIMESTAMP "
                "WHERE added_at IS NULL"
            )

        # Миграция: добавляем cover_path и description, если их нет в старой базе
        cols = [row[1] for row in conn.execute("PRAGMA table_info(playlists)").fetchall()]
        if "cover_path" not in cols:
            conn.execute("ALTER TABLE playlists ADD COLUMN cover_path TEXT")
        if "description" not in cols:
            conn.execute("ALTER TABLE playlists ADD COLUMN description TEXT")
        if "is_pinned" not in cols:
            conn.execute("ALTER TABLE playlists ADD COLUMN is_pinned INTEGER DEFAULT 0")
        if "position" not in cols:
            conn.execute("ALTER TABLE playlists ADD COLUMN position INTEGER DEFAULT 0")

        # Миграция: добавляем favorite_track_id, если профиль создан старой версией
        cols = [row[1] for row in conn.execute("PRAGMA table_info(profile)").fetchall()]
        if "favorite_track_id" not in cols:
            conn.execute(
                "ALTER TABLE profile ADD COLUMN favorite_track_id INTEGER "
                "REFERENCES tracks(id) ON DELETE SET NULL"
            )

        # Миграция: время прослушивания раньше вычислялось как сумма
        # длительностей всех записей play_history. Теперь оно хранится в
        # профиле и увеличивается только пока плеер действительно играет.
        # Старую статистику переносим один раз, чтобы она не потерялась.
        if "listening_seconds" not in cols:
            conn.execute(
                "ALTER TABLE profile ADD COLUMN listening_seconds "
                "INTEGER DEFAULT 0"
            )
            conn.execute(
                """UPDATE profile SET listening_seconds = COALESCE((
                       SELECT SUM(t.duration)
                       FROM play_history ph
                       JOIN tracks t ON t.id = ph.track_id
                   ), 0)
                   WHERE id = 1"""
            )


# ---------------------------------------------------------------------------
#  Tracks
# ---------------------------------------------------------------------------

def add_track(file_path):
    try:
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO tracks (file_path) VALUES (?)",
                (file_path,),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_all_tracks():
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, file_path, title, artist, album, duration, loudness, folder_id "
            "FROM tracks ORDER BY id"
        ).fetchall()


def get_track_by_id(track_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, file_path, title, artist, album, duration, loudness "
            "FROM tracks WHERE id = ?",
            (track_id,),
        ).fetchone()


def get_track_by_path(file_path):
    """Возвращает трек по пути к файлу (или None, если такого нет).

    file_path в таблице UNIQUE, поэтому перед переименованием файла нужно
    убедиться, что новый путь ещё не занят другим треком."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, file_path, title, artist, album, duration, loudness "
            "FROM tracks WHERE file_path = ?",
            (file_path,),
        ).fetchone()


def delete_track(track_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))


def update_track_path(track_id, new_path):
    with get_connection() as conn:
        conn.execute(
            "UPDATE tracks SET file_path = ? WHERE id = ?",
            (new_path, track_id),
        )


def update_track_metadata(track_id, title, artist, album, duration):
    with get_connection() as conn:
        conn.execute(
            """UPDATE tracks
               SET title = ?, artist = ?, album = ?, duration = ?
               WHERE id = ?""",
            (title, artist, album, duration, track_id),
        )


def get_tracks_without_loudness():
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, file_path FROM tracks WHERE loudness IS NULL ORDER BY id"
        ).fetchall()


def update_track_loudness(track_id, loudness):
    with get_connection() as conn:
        conn.execute(
            "UPDATE tracks SET loudness = ? WHERE id = ?",
            (loudness, track_id),
        )


def update_track_lyrics(track_id, synced, plain):
    """Сохраняет найденный текст и помечает трек как проверенный.

    Вызывается только при успешном ответе провайдеров. Сетевые сбои сюда не
    доходят — тогда воркер ничего не пишет и попытка повторится позже.
    """
    # closing() важен для воркера: соединение создаётся в фоновом потоке и
    # должно быть закрыто, иначе SQLite-файлы/дескрипторы копятся.
    with closing(get_connection()) as conn, conn:
        conn.execute(
            "UPDATE tracks "
            "SET lyrics_synced = ?, lyrics_plain = ?, lyrics_checked = 1 "
            "WHERE id = ?",
            (synced, plain, track_id),
        )


def get_track_lyrics(track_id):
    """Возвращает ``(synced, plain, checked)`` для трека.

    ``checked`` = 1 означает, что текст уже успешно загружался (в том числе
    подтверждённое «текста нет»). Если ``checked`` = 0, результат не
    окончательный: прошлая попытка могла сорваться из-за сети, и загрузку
    стоит повторить.
    """
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT lyrics_synced, lyrics_plain, lyrics_checked "
            "FROM tracks WHERE id = ?",
            (track_id,),
        ).fetchone()
        if row is None:
            return None, None, 1
        return row["lyrics_synced"], row["lyrics_plain"], bool(row["lyrics_checked"])


# ---------------------------------------------------------------------------
#  Folders
# ---------------------------------------------------------------------------

def create_folder(name):
    try:
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO folders (name) VALUES (?)",
                (name,),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_all_folders():
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, name FROM folders ORDER BY name"
        ).fetchall()


def delete_folder(folder_id):
    """Удаляет папку. Треки остаются и становятся «без папки»."""
    with get_connection() as conn:
        conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))


def move_track_to_folder(track_id, folder_id):
    """Переносит трек в папку. folder_id=None возвращает трек в корень."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE tracks SET folder_id = ? WHERE id = ?",
            (folder_id, track_id),
        )


def get_tracks_in_folder(folder_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, file_path, title, artist, album, duration, loudness, folder_id "
            "FROM tracks WHERE folder_id = ? ORDER BY id",
            (folder_id,),
        ).fetchall()


# ---------------------------------------------------------------------------
#  Playlists
# ---------------------------------------------------------------------------

def create_playlist(name):
    try:
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO playlists (name, position) "
                "VALUES (?, (SELECT COALESCE(MAX(position), 0) + 1 FROM playlists))",
                (name,),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_all_playlists():
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, name, cover_path, is_pinned, position FROM playlists "
            "ORDER BY is_pinned DESC, position ASC, id ASC"
        ).fetchall()


def update_playlist_position(playlist_id, new_position):
    with get_connection() as conn:
        conn.execute(
            "UPDATE playlists SET position = ? WHERE id = ?",
            (new_position, playlist_id),
        )


def update_all_playlists_positions(playlist_ids):
    """Сохраняет новый порядок плейлистов: индекс в списке = новая позиция."""
    with get_connection() as conn:
        conn.executemany(
            "UPDATE playlists SET position = ? WHERE id = ?",
            [(pos, pid) for pos, pid in enumerate(playlist_ids)],
        )


def set_playlist_pinned(playlist_id, is_pinned):
    with get_connection() as conn:
        conn.execute(
            "UPDATE playlists SET is_pinned = ? WHERE id = ?",
            (1 if is_pinned else 0, playlist_id),
        )


def get_playlist_by_id(playlist_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, name, cover_path, description FROM playlists WHERE id = ?",
            (playlist_id,),
        ).fetchone()


def update_playlist_cover(playlist_id, cover_path):
    with get_connection() as conn:
        conn.execute(
            "UPDATE playlists SET cover_path = ? WHERE id = ?",
            (cover_path, playlist_id),
        )


def update_playlist_description(playlist_id, description):
    with get_connection() as conn:
        conn.execute(
            "UPDATE playlists SET description = ? WHERE id = ?",
            (description, playlist_id),
        )


def delete_playlist(playlist_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))


# ---------------------------------------------------------------------------
#  Playlist <-> Tracks
# ---------------------------------------------------------------------------

def add_track_to_playlist(playlist_id, track_id):
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO playlist_tracks (playlist_id, track_id) VALUES (?, ?)",
                (playlist_id, track_id),
            )
            return True
    except sqlite3.IntegrityError:
        return False


def get_first_track_in_playlist(playlist_id):
    with get_connection() as conn:
        return conn.execute("""
            SELECT t.id, t.file_path
            FROM tracks t
            JOIN playlist_tracks pt ON pt.track_id = t.id
            WHERE pt.playlist_id = ?
            ORDER BY pt.added_at, t.id
            LIMIT 1
        """, (playlist_id,)).fetchone()


def get_tracks_in_playlist(playlist_id):
    with get_connection() as conn:
        return conn.execute("""
            SELECT t.id, t.file_path, t.title, t.artist, t.album, t.duration, t.loudness,
                   pt.added_at
            FROM tracks t
            JOIN playlist_tracks pt ON pt.track_id = t.id
            WHERE pt.playlist_id = ?
            ORDER BY t.id
        """, (playlist_id,)).fetchall()


def remove_track_from_playlist(playlist_id, track_id):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM playlist_tracks WHERE playlist_id = ? AND track_id = ?",
            (playlist_id, track_id),
        )


# ---------------------------------------------------------------------------
#  Profile & statistics
# ---------------------------------------------------------------------------

def _ensure_profile_row(conn):
    """Гарантирует единственную строку профиля (id = 1)."""
    conn.execute("INSERT OR IGNORE INTO profile (id) VALUES (1)")


def get_profile():
    with get_connection() as conn:
        _ensure_profile_row(conn)
        return conn.execute(
            "SELECT id, nickname, avatar_path, banner_path, description, "
            "favorite_track_id FROM profile WHERE id = 1"
        ).fetchone()


def update_profile(nickname=None, avatar_path=None, banner_path=None,
                   description=None):
    with get_connection() as conn:
        _ensure_profile_row(conn)
        conn.execute(
            """UPDATE profile SET
                   nickname    = COALESCE(?, nickname),
                   avatar_path = COALESCE(?, avatar_path),
                   banner_path = COALESCE(?, banner_path),
                   description = COALESCE(?, description)
               WHERE id = 1""",
            (nickname, avatar_path, banner_path, description),
        )


def set_favorite_track(track_id):
    with get_connection() as conn:
        _ensure_profile_row(conn)
        conn.execute(
            "UPDATE profile SET favorite_track_id = ? WHERE id = 1",
            (track_id,),
        )


def log_play(track_id):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO play_history (track_id) VALUES (?)",
            (track_id,),
        )


def add_listening_time(seconds):
    """Добавляет фактически прослушанные секунды к статистике профиля."""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return
    if seconds <= 0:
        return
    with get_connection() as conn:
        _ensure_profile_row(conn)
        conn.execute(
            """UPDATE profile
               SET listening_seconds = COALESCE(listening_seconds, 0) + ?
               WHERE id = 1""",
            (seconds,),
        )


def get_total_play_time():
    """Суммарное время прослушивания в секундах."""
    with get_connection() as conn:
        _ensure_profile_row(conn)
        row = conn.execute(
            "SELECT COALESCE(listening_seconds, 0) AS total "
            "FROM profile WHERE id = 1"
        ).fetchone()
        return int(row["total"] or 0)


def get_tracks_count():
    """Количество треков в библиотеке."""
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM tracks").fetchone()
        return int(row["count"] or 0)


def get_playlists_count():
    """Количество плейлистов."""
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM playlists").fetchone()
        return int(row["count"] or 0)


def get_app_age_days():
    """Сколько дней прошло с добавления первого трека в библиотеку."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MIN(created_at) AS first_added FROM tracks"
        ).fetchone()
        if not row or not row["first_added"]:
            return 0
        days = conn.execute(
            "SELECT CAST(julianday('now') - julianday(?) AS INTEGER) AS days",
            (row["first_added"],),
        ).fetchone()
        return max(0, int(days["days"] or 0))


def get_top_tracks(limit=5):
    with get_connection() as conn:
        return conn.execute(
            """SELECT t.id, t.file_path, t.title, t.artist, t.album, t.duration,
                      COUNT(ph.id) AS play_count
               FROM play_history ph
               JOIN tracks t ON t.id = ph.track_id
               GROUP BY t.id
               ORDER BY play_count DESC, MAX(ph.played_at) DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()


def get_top_artists(limit=5):
    with get_connection() as conn:
        return conn.execute(
            """SELECT COALESCE(t.artist, '') AS artist,
                      COUNT(ph.id) AS play_count
               FROM play_history ph
               JOIN tracks t ON t.id = ph.track_id
               GROUP BY artist
               ORDER BY play_count DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()


# ---------------------------------------------------------------------------
#  Playlist visibility (задел под сервер: какие плейлисты видны другим)
# ---------------------------------------------------------------------------

def set_playlist_visibility(playlist_id, is_public):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO playlist_visibility (playlist_id, is_public) "
            "VALUES (?, ?)",
            (playlist_id, 1 if is_public else 0),
        )


def get_playlist_visibility(playlist_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_public FROM playlist_visibility WHERE playlist_id = ?",
            (playlist_id,),
        ).fetchone()
        return bool(row["is_public"]) if row else False


def get_all_playlist_visibility():
    """Словарь {playlist_id: is_public} для быстрой отрисовки списка."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT playlist_id, is_public FROM playlist_visibility"
        ).fetchall()
        return {row["playlist_id"]: bool(row["is_public"]) for row in rows}
