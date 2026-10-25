/* Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 *
 * Task 5 diagnostics. Timings are elapsed host time, INCLUDING blocking and
 * descheduling, not CPU or GPU execution time. Use sampling alongside them.
 * Opt in with SWEETCA_DRAWPROF=1; unset or 0 disables collection.
 */
#ifndef SWEET_PROFILE_H
#define SWEET_PROFILE_H

#include <stdbool.h>
#include <stdint.h>

enum sweet_profile_id {
   SP_DRAW, SP_PREP, SP_PREP_QUERY, SP_PREP_REFRESH, SP_PREP_UNIFORM,
   SP_PREP_BARRIER, SP_DRAW_CALL, SP_KICK, SP_FRAME_FLUSH,
   SP_MESA_STATE, SP_ST_PREP, SP_ST_VALIDATE, SP_VBUF,
   SP_UPLOAD_ALLOC, SP_UPLOAD_DATA, SP_FD_DRAW, SP_DRAW_TRACKING,
   SP_BATCH_SELECT, SP_BATCH_CREATE, SP_BATCH_FLUSH, SP_TEXTURE_BARRIER,
   SP_CONTEXT_FLUSH, SP_PROGRAM_LOOKUP, SP_EMIT_STATE, SP_EMIT_PROGRAM,
   SP_SHADER_GET, SP_SHADER_VARIANT, SP_RESOURCE_READ, SP_RESOURCE_WRITE,
   SP_BATCH_SIZE, SP_SUBMIT, SP_WAIT, SP_COUNT
};

enum sweet_profile_event {
   SPE_PROGRAM_HIT, SPE_PROGRAM_MISS, SPE_UPLOAD_BYTES, SPE_BATCH_DRAWS,
   SPE_BATCH_ZERO, SPE_BATCH_ONE, SPE_BATCH_TWO_FOUR, SPE_BATCH_FIVE_PLUS,
   SPE_FLUSH_BARRIER, SPE_FLUSH_KICK, SPE_FLUSH_FRAME, SPE_FLUSH_DEPENDENCY,
   SPE_FLUSH_CAPACITY, SPE_FLUSH_CONTEXT, SPE_FLUSH_OTHER,
   SPE_BARRIER_NEEDED, SPE_BARRIER_SKIPPED, SPE_COUNT
};

#ifdef __APPLE__
struct sweet_profile_scope {
   struct sweet_profile_scope *parent;
   uint64_t start, children;
   enum sweet_profile_id id;
   bool active;
};

#ifdef __cplusplus
extern "C" {
#endif
void sweet_profile_enter(struct sweet_profile_scope *s, enum sweet_profile_id id);
void sweet_profile_leave(struct sweet_profile_scope *s);
void sweet_profile_event(enum sweet_profile_event event, uint64_t value);
void sweet_profile_batch(unsigned draws);
void sweet_profile_report(void (*log)(const char *fmt, ...));
/* Task 24: bounded driver batch graph, independent of DRAWPROF. */
extern bool sweet_batch_trace_enabled;
bool sweet_batch_trace_active(void);
void sweet_batch_trace(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
struct sweet_batch_trace_scope { const char *previous; bool active; };
struct sweet_batch_trace_scope sweet_batch_trace_enter(const char *cause);
void sweet_batch_trace_leave(struct sweet_batch_trace_scope *scope);
const char *sweet_batch_trace_cause(void);
/* freedreno_gmem.c's GPU time per batch (SWEETCA_GPUPROF=1), reported with the profile */
extern void (*sweet_gpuprof_report)(void (*log)(const char *fmt, ...));
/* fd5_draw.c's GPU time per draw (SWEETCA_GPUPROF=2) */
extern void (*sweet_gpuprof_draw_report)(void (*log)(const char *fmt, ...));
#ifdef __cplusplus
}
#endif

#define SWEET_SCOPE(name, id) \
   struct sweet_profile_scope name __attribute__((cleanup(sweet_profile_leave))) = {0}; \
   sweet_profile_enter(&(name), (id))
#define SWEET_EVENT(event, value) sweet_profile_event((event), (value))
#define SWEET_BATCH(draws) sweet_profile_batch(draws)
#define SWEET_BATCH_TRACE_SCOPE(name, cause) \
   struct sweet_batch_trace_scope name __attribute__((cleanup(sweet_batch_trace_leave))) = \
      sweet_batch_trace_enter(cause)
#else
#define SWEET_SCOPE(name, id) ((void)0)
#define SWEET_EVENT(event, value) ((void)0)
#define SWEET_BATCH(draws) ((void)0)
#define SWEET_BATCH_TRACE_SCOPE(name, cause) ((void)0)
#endif
#endif
