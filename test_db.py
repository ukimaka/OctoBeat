"""Ручной тест db.py. Запускается из терминала: python test_db.py"""

import db

# Чистим старую базу, если есть (полезно для повторных запусков)
import os
if os.path.exists(db.DB_FILE):
    os.remove(db.DB_FILE)

db.init_db()
print("БД создана")

# --- Треки ---
id1 = db.add_track("/home/baka/Music/song1.mp3")
id2 = db.add_track("/home/baka/Music/song2.mp3")
id3 = db.add_track("/home/baka/Music/song3.mp3")
dup = db.add_track("/home/baka/Music/song1.mp3")   # дубликат

print(f"Добавлены треки: {id1}, {id2}, {id3}")
print(f"Дубликат вернул: {dup} (должно быть None)")

tracks = db.get_all_tracks()
print(f"\nВсе треки ({len(tracks)}):")
for t in tracks:
    print(f"  id={t['id']}, path={t['file_path']}")

# --- Плейлисты ---
p1 = db.create_playlist("Rock")
p2 = db.create_playlist("Jazz")
pdup = db.create_playlist("Rock")   # дубликат имени

print(f"\nСозданы плейлисты: {p1}, {p2}")
print(f"Дубликат имени вернул: {pdup} (должно быть None)")

# --- Добавление треков в плейлист ---
db.add_track_to_playlist(p1, id1)
db.add_track_to_playlist(p1, id2)
db.add_track_to_playlist(p1, id1)   # дубликат — не должен добавиться
db.add_track_to_playlist(p2, id3)

rock_tracks = db.get_tracks_in_playlist(p1)
print(f"\nТреки в Rock ({len(rock_tracks)}, должно быть 2):")
for t in rock_tracks:
    print(f"  {t['file_path']}")

# --- Каскадное удаление ---
print("\nУдаляем трек id=1...")
db.delete_track(id1)

rock_after = db.get_tracks_in_playlist(p1)
print(f"Треки в Rock после удаления ({len(rock_after)}, должно быть 1):")
for t in rock_after:
    print(f"  {t['file_path']}")

print("\nВсё ок!")
