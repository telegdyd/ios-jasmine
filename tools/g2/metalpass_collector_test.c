/* SPDX-License-Identifier: MIT
 * Host test: compile with -fsanitize=address,undefined and an include path to
 * the patched src/freedreno/drm/darwin directory. No phone access. */
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <assert.h>
static uint64_t now;
static int trigger;
#define clock_gettime_nsec_np test_clock
static uint64_t test_clock(int clock) { return now; }
static int test_access(const char *p,int mode) { return !trigger; }
static FILE *test_fopen(const char *p,const char *m) { return fopen("/tmp/metal-m5-test.csv",m); }
void sweet_m5_poll(void) {}
#define access test_access
#define fopen test_fopen

#include "sweet_pass_profile.inc"

int main(void) {
 unsetenv("BGMTL_PASS_PROFILE"); sweet_m5_begin(); assert(!sweet_m5_collecting());
 setenv("BGMTL_PASS_PROFILE","1",1); m5_enabled=0;
 sweet_m5_begin(); assert(!sweet_m5_collecting());
 trigger=1; sweet_m5_begin(); assert(sweet_m5_collecting());
 uint64_t v[20]={64,64,1,1,80}; sweet_m5_pass(v);
 sweet_m5_link(42,7); unsigned count=m5_count; sweet_m5_link(42,7); assert(m5_count==count);
 unsigned slot=sweet_m5_batch(42,7,64,64,1,1,9,0,1,2,1,1,1,0,0); assert(slot && m5_pending==1);
 sweet_m5_stamps(slot,19200,38400); sweet_m5_stamps(slot,19200,38400); assert(!m5_pending);
 sweet_m5_stamps(0,1,2); sweet_m5_stamps(M5_ROWS+1,1,2);
 uint64_t textures[7]={207,448,10};
 sweet_m5_shader("blur",textures);unsigned shader=m5_count;
 sweet_m5_shader("blur",textures);assert(m5_count==shader && m5_rows[shader-1].v[12]==2);
 sweet_m5_drop();assert(m5_lost==1);m5_lost=0;
 sweet_m5_end(); assert(!sweet_m5_collecting());
 for(unsigned i=1;i<120;i++) { sweet_m5_begin(); sweet_m5_end(); }
 assert(m5_state==3 && m5_cb==120); sweet_m5_begin();assert(!sweet_m5_collecting());
 /* Capacity pressure is explicit, cannot overwrite timestamp ownership. */
 m5_state=1; m5_inline=true; m5_count=0; m5_lost=0;
 for(unsigned i=0;i<M5_ROWS+100;i++) sweet_m5_work(4);
 assert(m5_count==M5_ROWS && m5_lost==100);
 /* Deadline ends collection even below the CB budget; pending stamps stay
  * represented and make the exported capture unsuitable for attribution. */
 m5_count=0; m5_cb=1; m5_pending=0; m5_lost=0; now=m5_deadline;
 slot=sweet_m5_batch(1,1,1,1,1,1,1,0,1,1,0,0,0,0,0);
 sweet_m5_end(); assert(m5_state==2 && m5_pending==1);
 now+=3000000000ull; sweet_m5_begin(); sweet_m5_end(); assert(m5_state==3);
 puts("M5 ASan/UBSan disabled/trigger/edges/stamps/120CB/capacity/deadline/pending PASS");
}
