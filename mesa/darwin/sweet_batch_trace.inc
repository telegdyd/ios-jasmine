/* Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 * Bounded CPU-side batch graph. No GPU waits, timestamps or GL queries.
 */
#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <time.h>

bool sweet_batch_trace_enabled;
static pthread_mutex_t bt_lock = PTHREAD_MUTEX_INITIALIZER;
static __thread const char *bt_cause;
static struct {
   uint64_t start_ns, delay_ns, duration_ns;
   unsigned records, limit;
   bool stopped, started;
} bt;

static uint64_t
bt_now(void)
{
   struct timespec ts;
   if (clock_gettime(CLOCK_MONOTONIC, &ts))
      return 0;
   return (uint64_t)ts.tv_sec * UINT64_C(1000000000) + ts.tv_nsec;
}

static unsigned
bt_option(const char *name, unsigned fallback, unsigned maximum)
{
   const char *s = getenv(name);
   if (!s || !*s)
      return fallback;
   char *end;
   errno = 0;
   unsigned long value = strtoul(s, &end, 10);
   return errno || *end || *s == '-' || value > maximum ? fallback : (unsigned)value;
}

__attribute__((constructor)) static void
bt_init(void)
{
   const char *v = getenv("SWEETCA_BATCH_TRACE");
   sweet_batch_trace_enabled = v && !strcmp(v, "1");
   if (!sweet_batch_trace_enabled)
      return;
   bt.delay_ns = (uint64_t)bt_option("SWEETCA_BATCH_TRACE_DELAY", 300, 3600) * 1000000000;
   bt.duration_ns = (uint64_t)bt_option("SWEETCA_BATCH_TRACE_SECONDS", 25, 120) * 1000000000;
   bt.limit = bt_option("SWEETCA_BATCH_TRACE_EVENTS", 12000, 30000);
   bt.start_ns = bt_now();
   bt.stopped = !bt.start_ns || !bt.duration_ns || !bt.limit;
   fprintf(stderr, "sweetca: batchtrace armed delay=%llu seconds=%llu events=%u disabled=%u\n",
           (unsigned long long)(bt.delay_ns / 1000000000),
           (unsigned long long)(bt.duration_ns / 1000000000), bt.limit, bt.stopped);
}

/* bt_lock held; the first and last records make incomplete windows explicit. */
static bool
bt_active_locked(uint64_t now)
{
   if (bt.stopped)
      return false;
   if (!now || now < bt.start_ns) {
      bt.stopped = true;
      fprintf(stderr, "sweetca: batchtrace stop records=%u reason=clock-error\n", bt.records);
      return false;
   }
   uint64_t elapsed = now >= bt.start_ns ? now - bt.start_ns : 0;
   if (elapsed < bt.delay_ns)
      return false;
   if (elapsed - bt.delay_ns >= bt.duration_ns || bt.records >= bt.limit) {
      bt.stopped = true;
      fprintf(stderr, "sweetca: batchtrace stop records=%u reason=%s\n", bt.records,
              bt.records >= bt.limit ? "event-cap" : "deadline");
      return false;
   }
   if (!bt.started) {
      bt.started = true;
      fprintf(stderr, "sweetca: batchtrace start late_ms=%llu\n",
              (unsigned long long)((elapsed - bt.delay_ns) / 1000000));
   }
   return true;
}

bool
sweet_batch_trace_active(void)
{
   if (!sweet_batch_trace_enabled)
      return false;
   pthread_mutex_lock(&bt_lock);
   bool active = bt_active_locked(bt_now());
   pthread_mutex_unlock(&bt_lock);
   return active;
}

void
sweet_batch_trace(const char *fmt, ...)
{
   if (!sweet_batch_trace_enabled)
      return;
   pthread_mutex_lock(&bt_lock);
   uint64_t now = bt_now();
   if (bt_active_locked(now)) {
      char record[1400] = {0};
      va_list ap;
      va_start(ap, fmt);
      int n = vsnprintf(record, sizeof(record), fmt, ap);
      va_end(ap);
      fprintf(stderr, "sweetca: batchtrace e=%u us=%llu cause=%s %s%s\n", ++bt.records,
              (unsigned long long)((now - bt.start_ns) / 1000), sweet_batch_trace_cause(),
              record, n < 0 || n >= (int)sizeof(record) ? " truncated=1" : "");
      if (bt.records == bt.limit)
         (void)bt_active_locked(now);
   }
   pthread_mutex_unlock(&bt_lock);
}

struct sweet_batch_trace_scope
sweet_batch_trace_enter(const char *cause)
{
   struct sweet_batch_trace_scope scope = {bt_cause, sweet_batch_trace_enabled};
   if (scope.active)
      bt_cause = cause;
   return scope;
}

void
sweet_batch_trace_leave(struct sweet_batch_trace_scope *scope)
{
   if (scope->active)
      bt_cause = scope->previous;
}

const char *
sweet_batch_trace_cause(void)
{
   return bt_cause ? bt_cause : "unclassified";
}
