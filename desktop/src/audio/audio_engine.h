#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct OctoAudioEngine OctoAudioEngine;

OctoAudioEngine *octobeat_audio_new(void);
void octobeat_audio_free(OctoAudioEngine *engine);

int octobeat_audio_play(OctoAudioEngine *engine,
                        const char *path,
                        int64_t start_ms);
int octobeat_audio_crossfade(OctoAudioEngine *engine, const char *path);
void octobeat_audio_finish_crossfade(OctoAudioEngine *engine);
void octobeat_audio_cancel_crossfade(OctoAudioEngine *engine);
void octobeat_audio_stop(OctoAudioEngine *engine);
void octobeat_audio_pause(OctoAudioEngine *engine);
void octobeat_audio_resume(OctoAudioEngine *engine);
void octobeat_audio_seek(OctoAudioEngine *engine, int64_t position_ms);
void octobeat_audio_set_volume(OctoAudioEngine *engine, int volume);
void octobeat_audio_set_slot_volume(OctoAudioEngine *engine,
                                    int slot,
                                    int volume);
void octobeat_audio_set_duration_hint(OctoAudioEngine *engine,
                                      int64_t duration_ms);

int64_t octobeat_audio_position(OctoAudioEngine *engine);
int64_t octobeat_audio_duration(OctoAudioEngine *engine);
int octobeat_audio_is_playing(OctoAudioEngine *engine);
int octobeat_audio_active_slot(OctoAudioEngine *engine);
int octobeat_audio_has_ended(OctoAudioEngine *engine);
uint64_t octobeat_audio_underruns(OctoAudioEngine *engine);

// Copies the last error into buffer (NUL-terminated) and clears it.
// Returns the number of bytes copied, 0 if there is no error, -1 on bad args.
int octobeat_audio_take_error(OctoAudioEngine *engine,
                              char *buffer,
                              int buffer_len);

#ifdef __cplusplus
}
#endif
