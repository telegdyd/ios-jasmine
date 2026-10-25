/* Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT */
#include "util/sweet_profile.h"
#include <mach/mach_time.h>
#include <stdlib.h>
#include <string.h>
#include "sweet_batch_trace.inc"

static bool enabled;
static __thread struct sweet_profile_scope *current;
static struct {
   uint64_t calls, inclusive, exclusive;
} totals[SP_COUNT];
static uint64_t events[SPE_COUNT];
static double ms_per_tick;

static const char *const names[SP_COUNT] = {
   "draw-wrapper", "draw-prep", "prep-uniform-query", "prep-copy-refresh", "prep-uniform-update",
   "prep-texture-barrier", "GL-draw-call", "periodic-kick", "frame-flush",
   "mesa-update-state", "st-prepare", "st-validate", "vertex-buffer-manager",
   "upload-alloc", "upload-data", "fd-draw", "draw-resource-tracking",
   "batch-select", "batch-create", "batch-flush", "fd-texture-barrier",
   "fd-context-flush", "program-lookup", "a5xx-emit-state", "a5xx-emit-program",
   "shader-get", "shader-new-variant", "resource-read", "resource-write",
   "batch-size-check", "submit-build-and-call", "kernel-fence-wait"
};
static const char *const event_names[SPE_COUNT] = {
   "program-hit", "program-miss", "upload-requested-bytes", "batch-draws",
   "batch-0", "batch-1", "batch-2-4", "batch-5+",
   "flush-barrier", "flush-kick", "flush-frame", "flush-resource-dependency",
   "flush-capacity", "flush-context", "flush-other",
   "barrier-needed", "barrier-skipped"
};

__attribute__((constructor)) static void
profile_init(void)
{
   const char *v = getenv("SWEETCA_DRAWPROF");
   enabled = v && strcmp(v, "0") != 0;
   mach_timebase_info_data_t tb;
   mach_timebase_info(&tb);
   ms_per_tick = (double)tb.numer / tb.denom / 1e6;
}

void
sweet_profile_enter(struct sweet_profile_scope *s, enum sweet_profile_id id)
{
   s->active = enabled;
   if (!s->active)
      return;
   s->id = id;
   s->children = 0;
   s->parent = current;
   current = s;
   s->start = mach_absolute_time();
}

void
sweet_profile_leave(struct sweet_profile_scope *s)
{
   if (!s->active)
      return;
   uint64_t ticks = mach_absolute_time() - s->start;
   current = s->parent;
   if (current)
      current->children += ticks;
   uint64_t self = ticks >= s->children ? ticks - s->children : 0;
   __atomic_fetch_add(&totals[s->id].calls, 1, __ATOMIC_RELAXED);
   __atomic_fetch_add(&totals[s->id].inclusive, ticks, __ATOMIC_RELAXED);
   __atomic_fetch_add(&totals[s->id].exclusive, self, __ATOMIC_RELAXED);
}

void
sweet_profile_event(enum sweet_profile_event event, uint64_t value)
{
   if (enabled)
      __atomic_fetch_add(&events[event], value, __ATOMIC_RELAXED);
}

void
sweet_profile_batch(unsigned draws)
{
   if (!enabled)
      return;
   enum sweet_profile_event reason = SPE_FLUSH_OTHER;
   /* Nearest instrumented cause wins, so a resource dependency nested in a
    * context flush is distinguishable from the requested context flush itself.
    * These are actual batch finalizations, after batch->flushed was checked.
    */
   for (struct sweet_profile_scope *s = current; s; s = s->parent) {
      if (s->id == SP_TEXTURE_BARRIER || s->id == SP_PREP_BARRIER)
         reason = SPE_FLUSH_BARRIER;
      else if (s->id == SP_KICK)
         reason = SPE_FLUSH_KICK;
      else if (s->id == SP_FRAME_FLUSH)
         reason = SPE_FLUSH_FRAME;
      else if (s->id == SP_RESOURCE_READ || s->id == SP_RESOURCE_WRITE)
         reason = SPE_FLUSH_DEPENDENCY;
      else if (s->id == SP_BATCH_SIZE)
         reason = SPE_FLUSH_CAPACITY;
      else
         continue;
      break;
   }
   if (reason == SPE_FLUSH_OTHER) {
      for (struct sweet_profile_scope *s = current; s; s = s->parent)
         if (s->id == SP_CONTEXT_FLUSH) {
            reason = SPE_FLUSH_CONTEXT;
            break;
         }
   }
   sweet_profile_event(reason, 1);
   sweet_profile_event(SPE_BATCH_DRAWS, draws);
   sweet_profile_event(draws == 0 ? SPE_BATCH_ZERO : draws == 1 ? SPE_BATCH_ONE :
                       draws <= 4 ? SPE_BATCH_TWO_FOUR : SPE_BATCH_FIVE_PLUS, 1);
}

void (*sweet_gpuprof_report)(void (*log)(const char *fmt, ...));
void (*sweet_gpuprof_draw_report)(void (*log)(const char *fmt, ...));

void
sweet_profile_report(void (*log)(const char *fmt, ...))
{
   if (sweet_gpuprof_report)
      sweet_gpuprof_report(log);
   if (sweet_gpuprof_draw_report)
      sweet_gpuprof_draw_report(log);
   log("sweetca: drawprof v1: enabled %u; elapsed incl/excl ms (not CPU); nested scopes overlap; per 100 flushes", enabled);
   if (!enabled)
      return;
   /* Each field is race-free. Worker scopes completing across the snapshot
    * boundary can land in adjacent windows: aggregate multiple windows.
    */
   for (unsigned i = 0; i < SP_COUNT; i++) {
      uint64_t calls = __atomic_exchange_n(&totals[i].calls, 0, __ATOMIC_RELAXED);
      uint64_t incl = __atomic_exchange_n(&totals[i].inclusive, 0, __ATOMIC_RELAXED);
      uint64_t excl = __atomic_exchange_n(&totals[i].exclusive, 0, __ATOMIC_RELAXED);
      if (calls || incl)
         log("sweetca: drawprof: %-24s %llu calls %.3f incl %.3f excl ms", names[i],
             (unsigned long long)calls, incl * ms_per_tick, excl * ms_per_tick);
   }
   for (unsigned i = 0; i < SPE_COUNT; i++) {
      uint64_t n = __atomic_exchange_n(&events[i], 0, __ATOMIC_RELAXED);
      if (n)
         log("sweetca: drawevent: %s %llu", event_names[i], (unsigned long long)n);
   }
}
