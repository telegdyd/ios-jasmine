/* SPDX-License-Identifier: MIT
 * Host test of the actual window/cap implementation, including concurrent
 * callers. Does not simulate GPU ordering or establish rendering correctness.
 * cc -std=gnu11 -Wall -Wextra -Werror -pthread test_batch_trace.c -o test-bt
 */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define __APPLE__ 1
#include "sweet_profile.h"
static uint64_t fake_ns = UINT64_C(1000000000);
static int
fake_clock(clockid_t id, struct timespec *ts)
{
   assert(id == CLOCK_MONOTONIC);
   ts->tv_sec = fake_ns / 1000000000;
   ts->tv_nsec = fake_ns % 1000000000;
   return 0;
}
#define clock_gettime fake_clock
#include "sweet_batch_trace.inc"

static void
reset(const char *delay, const char *seconds, const char *events)
{
   memset(&bt, 0, sizeof(bt));
   fake_ns = UINT64_C(1000000000);
   setenv("SWEETCA_BATCH_TRACE", "1", 1);
   setenv("SWEETCA_BATCH_TRACE_DELAY", delay, 1);
   setenv("SWEETCA_BATCH_TRACE_SECONDS", seconds, 1);
   setenv("SWEETCA_BATCH_TRACE_EVENTS", events, 1);
   bt_init();
}

static void *
worker(void *arg)
{
   const char *cause = arg;
   assert(!strcmp(sweet_batch_trace_cause(), "unclassified"));
   {
      SWEET_BATCH_TRACE_SCOPE(outer, cause);
      for (int i = 0; i < 500; i++)
         sweet_batch_trace("event=worker value=%d", i);
      {
         SWEET_BATCH_TRACE_SCOPE(inner, "nested");
         assert(!strcmp(sweet_batch_trace_cause(), "nested"));
      }
      assert(!strcmp(sweet_batch_trace_cause(), cause));
   }
   assert(!strcmp(sweet_batch_trace_cause(), "unclassified"));
   return NULL;
}

int
main(void)
{
   unsetenv("SWEETCA_BATCH_TRACE");
   bt_init();
   assert(!sweet_batch_trace_active());
   sweet_batch_trace("event=must-not-log");
   assert(!bt.records);

   reset("3", "2", "100");
   assert(!sweet_batch_trace_active());
   fake_ns += UINT64_C(2999999999);
   assert(!sweet_batch_trace_active());
   fake_ns++;
   assert(sweet_batch_trace_active());
   sweet_batch_trace("event=first");
   fake_ns += UINT64_C(1999999999);
   assert(sweet_batch_trace_active());
   sweet_batch_trace("event=last");
   fake_ns++;
   assert(!sweet_batch_trace_active());
   sweet_batch_trace("event=after-deadline");
   assert(bt.records == 2 && bt.stopped);

   reset("0", "20", "1000");
   pthread_t threads[4];
   for (int i = 0; i < 4; i++)
      assert(!pthread_create(&threads[i], NULL, worker, i & 1 ? "odd" : "even"));
   for (int i = 0; i < 4; i++)
      assert(!pthread_join(threads[i], NULL));
   assert(bt.records == 1000 && bt.stopped);
   assert(!strcmp(sweet_batch_trace_cause(), "unclassified"));

   reset("-1", "oops", "99999999");
   assert(bt.delay_ns == UINT64_C(300000000000));
   assert(bt.duration_ns == UINT64_C(25000000000) && bt.limit == 12000);
   reset("0", "0", "10");
   assert(!sweet_batch_trace_active());
   reset("0", "25", "0");
   assert(!sweet_batch_trace_active());
   reset("0", "25", "10");
   fake_ns = 0;
   assert(!sweet_batch_trace_active() && bt.stopped);
   puts("PASS: disabled, delay, deadline, concurrent cap, TLS scopes, invalid/zero options");
   return 0;
}
