#ifndef OCTOBEAT_CORE_H
#define OCTOBEAT_CORE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct Core OctoCore;

OctoCore *octobeat_core_new(const char *data_dir,
                            const char *db_path,
                            const char *music_dir,
                            const char *cache_dir);
void octobeat_core_free(OctoCore *core);

char *octobeat_core_tracks_json(OctoCore *core);
char *octobeat_core_playlists_json(OctoCore *core);
char *octobeat_core_track_path(OctoCore *core, int64_t track_id);
char *octobeat_core_playlist_tracks_json(OctoCore *core, int64_t playlist_id);
int64_t octobeat_core_create_playlist(OctoCore *core, const char *name);
int octobeat_core_update_playlist_description(OctoCore *core,
                                              int64_t playlist_id,
                                              const char *description);
int octobeat_core_update_playlist_cover(OctoCore *core,
                                        int64_t playlist_id,
                                        const char *cover_path);
int octobeat_core_delete_playlist(OctoCore *core, int64_t playlist_id);
int octobeat_core_add_track_to_playlist(OctoCore *core,
                                        int64_t playlist_id,
                                        int64_t track_id);
int octobeat_core_remove_track_from_playlist(OctoCore *core,
                                             int64_t playlist_id,
                                             int64_t track_id);

typedef void (*OctoScanProgress)(int done, int total, void *user_data);
int octobeat_core_scan(OctoCore *core,
                       OctoScanProgress progress,
                       void *user_data);

int octobeat_core_set_music_dir(OctoCore *core, const char *music_dir);
char *octobeat_core_folders_json(OctoCore *core);
int64_t octobeat_core_create_folder(OctoCore *core, const char *name);
int octobeat_core_move_track_to_folder(OctoCore *core,
                                       int64_t track_id,
                                       int64_t folder_id);
char *octobeat_core_track_lyrics_json(OctoCore *core, int64_t track_id);
int octobeat_core_update_track_lyrics(OctoCore *core,
                                      int64_t track_id,
                                      const char *synced,
                                      const char *plain,
                                      int manual);
char *octobeat_core_profile_json(OctoCore *core);
int octobeat_core_set_profile_field(OctoCore *core,
                                   const char *field,
                                   const char *value);
int octobeat_core_log_play(OctoCore *core, int64_t track_id);
int octobeat_core_add_listening_time(OctoCore *core, int64_t seconds);
int octobeat_core_delete_track(OctoCore *core, int64_t track_id);
int octobeat_core_update_track_metadata(OctoCore *core,
                                        int64_t track_id,
                                        const char *title,
                                        const char *artist);
int octobeat_core_set_track_cover(OctoCore *core,
                                  int64_t track_id,
                                  const char *source_path);
int octobeat_core_set_lyrics_offset(OctoCore *core,
                                    int64_t track_id,
                                    int64_t offset_ms);
int octobeat_core_clear_covers(OctoCore *core);
int octobeat_core_clear_all_cache(OctoCore *core);
char *octobeat_core_last_error(OctoCore *core);
void octobeat_string_free(char *value);

#ifdef __cplusplus
}
#endif

#endif
