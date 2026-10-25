/*
 * Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 *
 * libsweetca: CoreAnimation's own OpenGL ES renderer (CA::OGL::GLESContext and
 * OGL::Renderer) on Mesa freedreno, through sweetgl.
 *
 * QuartzCore never calls an exported gl* function. It asks an EAGLContext for
 * -getMacroContextPrivate, which returns {rctx; dispatch[1036]} (the layout
 * of GLEngine's GLI dispatch table), and calls dispatch[n](rctx, args...).
 * For the contexts it makes, this library replaces the EAGLContext methods CA
 * uses (found by reading QuartzCore, see jasmine/GPU.md "G2 step A") with ones
 * that hand out such a table of its own: the ~60 entries CA calls are
 * wrappers around Mesa's GL ES, all others log their slot name once and
 * return 0. Contexts that were not made here go to Apple's original methods.
 *
 * What CA expects beyond plain GL ES 2/3 is emulated here. The list was found
 * by the ios-sailfish project on a Pixel 1 (Adreno 530, same Mesa driver
 * family); the code below is our own:
 *  - GL_TEXTURE_RECTANGLE textures are 2D textures, with separate 2D and
 *    rectangle bindings per unit, and sampler2DRect shaders are rewritten to
 *    sample a 2D texture with texel coordinates scaled by 1/size;
 *  - GL_EXT_shader_framebuffer_fetch (gl_LastFragData) is a texture read of
 *    the render target's own texture through a nearest-filtering sampler of
 *    our own on a reserved unit, with a texture barrier before the draw;
 *  - IOSurfaces become texture storage with no copy, one Mesa resource per
 *    surface (sweetgl), or a copy when the GPU cannot use their rows in place.
 *
 * Environment: SWEETCA_TRACE=1 logs GL errors after each call (and eats them),
 * the first call of each slot and every shader that fails to compile.
 */

#include <objc/NSObjCRuntime.h>
#include <objc/message.h>
#include <objc/objc.h>
#include <objc/runtime.h>
#include <ctype.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <mach/mach.h>
#include <mach/mach_time.h>
#include <mach/vm_page_size.h>
#include <CoreFoundation/CoreFoundation.h>
#include <IOSurface/IOSurfaceRef.h>

#include <GLES3/gl31.h>
#include <GLES2/gl2ext.h>

#include "sweetgl.h"
#include "sweetca_slots.inc"
#include "util/sweet_profile.h"

#define GL_TEXTURE_RECTANGLE_ARB 0x84F5
#define GL_TEXTURE_BINDING_RECTANGLE_ARB 0x84F6
#define GL_MAX_RECTANGLE_TEXTURE_SIZE_ARB 0x84F8
#define GL_UNPACK_CLIENT_STORAGE_APPLE 0x85B2
#define GL_BGRA_EXT_ 0x80E1
#define GL_HALF_FLOAT_OES_ 0x8D61

#define UNITS 32
#define OBJMAX 8192 /* shader and program names with emulation state (they share one namespace) */
#define TEXMAX 16384
#define FBOMAX 1024
#define MAX_CTX 32

static int trace_on;
static bool active_barriers = true; /* SWEETCA_ACTIVE_BARRIERS=0: comparison only */

static void
sca_log(const char *fmt, ...)
{
   char line[1024];
   va_list ap;
   va_start(ap, fmt);
   int n = vsnprintf(line, sizeof(line) - 2, fmt, ap);
   va_end(ap);
   if (n < 0)
      return;
   if (n > (int)sizeof(line) - 2)
      n = sizeof(line) - 2;
   line[n++] = '\n';
   (void)!fwrite(line, 1, n, stderr);
   fflush(stderr);
}

/* ---- contexts ---- */

#define OBJ_RECT 1   /* fragment shader with a sampler2DRect */
#define OBJ_FBFETCH 2 /* fragment shader reading gl_LastFragData */

struct sca_obj {
   uint8_t flags;
   char rect_sampler[32];
   /* programs: uniform locations of the emulation's uniforms, -1 for none */
   GLint rect_sampler_loc, rect_scale_loc, fb_sampler_loc, fb_scale_loc;
};

/* CA reads {rctx, disp[]} from getMacroContextPrivate: rctx first, then the table */
struct sca_ctx {
   void *rctx;
   void *disp[SCA_SLOTS];
   id eagl;
   unsigned api;
   struct sgl_context *gl;

   int active;                         /* active texture unit as CA set it */
   GLuint bind2d[UNITS], bindrect[UNITS], held[UNITS];
   int fbfetch_unit;
   GLuint fb_sampler;                  /* on fbfetch_unit: nearest, level 0 only */
   GLuint readback_fbo;                /* ours, for writing shadow targets back */
   unsigned frame;                     /* glFlush count: CA flushes once per frame */
   GLuint shadows[64];                 /* textures standing in for render-target surfaces */
   GLuint program, fbo;
   bool followed;                      /* Mesa's driver thread has this one's priority */
   GLuint fbo_tex[FBOMAX];             /* color attachment 0 texture of each framebuffer */
   uint16_t tex_w[TEXMAX], tex_h[TEXMAX]; /* level 0 sizes, as given to us */
   uint8_t tex_swizzled[TEXMAX];
   struct sca_copy *copies[TEXMAX];     /* textures holding a copy of an IOSurface */
   struct sca_obj obj[OBJMAX];
};

static void copy_forget(struct sca_ctx *c, GLuint tex);
static void copy_refresh(struct sca_ctx *c, int u, GLuint tex);
static void copy_mipped(struct sca_ctx *c, GLuint tex);
static void shadow_drawn(struct sca_ctx *c);
static void shadow_write_back(struct sca_ctx *c);

static struct sca_ctx *ctxs[MAX_CTX];
static pthread_mutex_t ctx_lock = PTHREAD_MUTEX_INITIALIZER;
static __thread struct sca_ctx *cur;    /* bound to this thread's Mesa context */
static __thread id cur_eagl;

static struct sca_ctx *
lookup(id eagl)
{
   struct sca_ctx *found = NULL;
   if (!eagl)
      return NULL;
   pthread_mutex_lock(&ctx_lock);
   for (int i = 0; i < MAX_CTX && !found; i++) {
      if (ctxs[i] && ctxs[i]->eagl == eagl)
         found = ctxs[i];
   }
   pthread_mutex_unlock(&ctx_lock);
   return found;
}

static void
bind_ctx(struct sca_ctx *c)
{
   sgl_make_current(c ? c->gl : NULL, NULL);
   cur = c;
}

/*
 * Where backboardd's frame time goes: every wrapper's time and the kernel
 * submits made inside it (darwin_pipe.c counts them), summed per wrapper and
 * logged with the 100-flush statistics. Outermost calls only add to the total.
 */
extern uint64_t darwin_submits, darwin_submit_ticks, darwin_wait_ticks, darwin_waits;
/* the darwin backend's buffer, cache and fence counters (PERF-TASKS task 4) */
void darwin_prof_report(void (*log)(const char *fmt, ...));

struct prof_mark {
   const char *fn;
   uint64_t t0, s0;
};
struct prof_slot {
   const char *fn;
   uint64_t calls, ticks, submits;
};
#define PROF_SLOTS 128
static struct prof_slot prof[PROF_SLOTS];
static uint64_t prof_gl_ticks;
static __thread unsigned prof_depth;

static void
prof_end(struct prof_mark *m)
{
   uint64_t dt = mach_absolute_time() - m->t0, ds = darwin_submits - m->s0;
   if (--prof_depth == 0)
      prof_gl_ticks += dt;
   unsigned h = (unsigned)(((uintptr_t)m->fn >> 3) % PROF_SLOTS);
   for (unsigned i = 0; i < PROF_SLOTS; i++, h = (h + 1) % PROF_SLOTS) {
      if (prof[h].fn == m->fn || (prof[h].fn == NULL && __sync_bool_compare_and_swap(&prof[h].fn, NULL, m->fn)) ||
          prof[h].fn == m->fn) {
         prof[h].calls++;
         prof[h].ticks += dt;
         prof[h].submits += ds;
         return;
      }
   }
}

/* the wrappers' first lines: rctx is ours, and its Mesa context must be this thread's */
#define CUR(r)                                                                   \
   struct prof_mark __attribute__((cleanup(prof_end), unused)) sca_pm =          \
      {__func__, mach_absolute_time(), darwin_submits};                           \
   prof_depth++;                                                                  \
   struct sca_ctx *c = (struct sca_ctx *)(r);                                     \
   if (__builtin_expect(cur != c, 0))                                             \
      bind_ctx(c)

static void
post(int slot)
{
   static uint8_t logged[SCA_SLOTS][8];
   static uint8_t used[SCA_SLOTS];
   if (!used[slot]) {
      used[slot] = 1;
      sca_log("sweetca: first call of slot %d %s", slot, sca_slot_names[slot] ? sca_slot_names[slot] : "?");
   }
   GLenum e = glGetError();
   unsigned k = e - GL_INVALID_ENUM;
   if (e != GL_NO_ERROR && (k >= 8 || logged[slot][k] < 3)) {
      if (k < 8)
         logged[slot][k]++;
      sca_log("sweetca: GL error %#x after slot %d %s", e, slot,
              sca_slot_names[slot] ? sca_slot_names[slot] : "?");
      if (e == GL_INVALID_FRAMEBUFFER_OPERATION) {
         GLint fb = -1;
         glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fb);
         sca_log("sweetca:   framebuffer %d status %#x", fb, glCheckFramebufferStatus(GL_FRAMEBUFFER));
      }
   }
}
#define POST(slot)                                                               \
   do {                                                                          \
      if (__builtin_expect(trace_on, 0))                                         \
         post(slot);                                                             \
   } while (0)

static intptr_t
trap(int slot)
{
   static uint8_t seen[SCA_SLOTS];
   if (!seen[slot]) {
      seen[slot] = 1;
      sca_log("sweetca: unsupported GLI slot %d (%s)", slot,
              sca_slot_names[slot] ? sca_slot_names[slot] : "unnamed");
   }
   return 0;
}

/* ---- wrappers: plain pass-through ---- */

#define UNP(...) __VA_ARGS__
#define WV(slot, name, params, args)                                             \
   static void w_##name(void *rctx, UNP params)                                  \
   {                                                                             \
      CUR(rctx);                                                                 \
      (void)c;                                                                   \
      gl##name args;                                                             \
      POST(slot);                                                                \
   }
#define WR(slot, ret, name, params, args)                                        \
   static ret w_##name(void *rctx, UNP params)                                   \
   {                                                                             \
      CUR(rctx);                                                                 \
      (void)c;                                                                   \
      ret r = gl##name args;                                                     \
      POST(slot);                                                                \
      return r;                                                                  \
   }

WV(7, BlendFunc, (GLenum s, GLenum d), (s, d))
WV(12, ClearColor, (GLfloat r, GLfloat g, GLfloat b, GLfloat a), (r, g, b, a))
WV(63, Disable, (GLenum cap), (cap))
WV(72, Enable, (GLenum cap), (cap))
WV(98, GenTextures, (GLsizei n, GLuint *t), (n, t))
WV(251, Scissor, (GLint x, GLint y, GLsizei w, GLsizei h), (x, y, w, h))
WV(335, Viewport, (GLint x, GLint y, GLsizei w, GLsizei h), (x, y, w, h))
WV(338, BlendEquation, (GLenum mode), (mode))
WV(511, VertexAttribPointer,
   (GLuint i, GLint size, GLenum type, GLboolean norm, GLsizei stride, const void *p),
   (i, size, type, norm, stride, p))
WV(512, EnableVertexAttribArray, (GLuint i), (i))
WV(513, DisableVertexAttribArray, (GLuint i), (i))
WV(598, AttachShader, (GLuint p, GLuint s), (p, s))
WV(602, Uniform1f, (GLint l, GLfloat a), (l, a))
WV(605, Uniform4f, (GLint l, GLfloat a, GLfloat b, GLfloat cc, GLfloat d), (l, a, b, cc, d))
WV(606, Uniform1i, (GLint l, GLint a), (l, a))
WV(603, Uniform2f, (GLint l, GLfloat a, GLfloat b), (l, a, b))
WV(604, Uniform3f, (GLint l, GLfloat a, GLfloat b, GLfloat cc), (l, a, b, cc))
WV(607, Uniform2i, (GLint l, GLint a, GLint b), (l, a, b))
WV(608, Uniform3i, (GLint l, GLint a, GLint b, GLint cc), (l, a, b, cc))
WV(609, Uniform4i, (GLint l, GLint a, GLint b, GLint cc, GLint d), (l, a, b, cc, d))
WV(610, Uniform1fv, (GLint l, GLsizei n, const GLfloat *v), (l, n, v))
WV(611, Uniform2fv, (GLint l, GLsizei n, const GLfloat *v), (l, n, v))
WV(614, Uniform1iv, (GLint l, GLsizei n, const GLint *v), (l, n, v))
WV(615, Uniform2iv, (GLint l, GLsizei n, const GLint *v), (l, n, v))
WV(616, Uniform3iv, (GLint l, GLsizei n, const GLint *v), (l, n, v))
WV(617, Uniform4iv, (GLint l, GLsizei n, const GLint *v), (l, n, v))
WV(618, UniformMatrix2fv, (GLint l, GLsizei n, GLboolean t, const GLfloat *v), (l, n, t, v))
WV(612, Uniform3fv, (GLint l, GLsizei n, const GLfloat *v), (l, n, v))
WV(613, Uniform4fv, (GLint l, GLsizei n, const GLfloat *v), (l, n, v))
WV(619, UniformMatrix3fv, (GLint l, GLsizei n, GLboolean t, const GLfloat *v), (l, n, t, v))
WV(620, UniformMatrix4fv, (GLint l, GLsizei n, GLboolean t, const GLfloat *v), (l, n, t, v))
WR(625, GLint, GetUniformLocation, (GLuint p, const GLchar *name), (p, name))
WV(630, BindAttribLocation, (GLuint p, GLuint i, const GLchar *name), (p, i, name))
WV(674, GenFramebuffers, (GLsizei n, GLuint *f), (n, f))
WR(779, GLsync, FenceSync, (GLenum cond, GLbitfield flags), (cond, flags))
WV(781, DeleteSync, (GLsync s), (s))
WR(782, GLenum, ClientWaitSync, (GLsync s, GLbitfield flags, GLuint64 timeout), (s, flags, timeout))

static GLenum
w_GetError(void *rctx)
{
   CUR(rctx);
   (void)c;
   return glGetError();
}

static void
w_UseProgram(void *rctx, GLuint p)
{
   CUR(rctx);
   c->program = p;
   glUseProgram(p);
   POST(600);
}

/* shader and program objects: Apple's ARB handles are the plain names here */
static uint64_t
w_CreateShader(void *rctx, GLenum type)
{
   CUR(rctx);
   (void)c;
   uint64_t r = glCreateShader(type);
   POST(594);
   return r;
}

static uint64_t
w_CreateProgram(void *rctx)
{
   CUR(rctx);
   (void)c;
   uint64_t r = glCreateProgram();
   POST(597);
   return r;
}

static void
w_DeleteObject(void *rctx, GLuint obj)
{
   CUR(rctx);
   if (glIsProgram(obj))
      glDeleteProgram(obj);
   else
      glDeleteShader(obj);
   if (obj < OBJMAX)
      memset(&c->obj[obj], 0, sizeof(c->obj[obj]));
   POST(591);
}

/* ---- markers, labels and fences that only need to exist ---- */

static void
w_Nop(void *rctx)
{
   (void)rctx;
}

static void
w_FramebufferParameteriAPPLE(void *rctx, GLenum target, GLenum pname, GLint value)
{
   (void)rctx;
   static int logged;
   if (logged++ < 4)
      sca_log("sweetca: glFramebufferParameteriAPPLE(%#x, %#x, %d) ignored", target, pname, value);
}

/* CA hands finished surfaces to the display without waiting for the GPU: flush means finish */
/* SWEETCA_TRACE: the current framebuffer's center pixel and a corner, and the draw counts */
static unsigned n_draws, n_clears;
static void
trace_fb(const char *when)
{
   GLint fb = -1, vp[4] = {0};
   glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fb);
   glGetIntegerv(GL_VIEWPORT, vp);
   uint8_t px[8] = {0};
   if (fb > 0) {
      glReadPixels(vp[0] + 4, vp[1] + 4, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
      glReadPixels(vp[0] + vp[2] / 2, vp[1] + vp[3] / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px + 4);
   }
   sca_log("sweetca: %s: fbo %d viewport %d,%d %dx%d, draws %u clears %u, GL reads rgba (4,4)=%02x%02x%02x%02x center=%02x%02x%02x%02x",
           when, fb, vp[0], vp[1], vp[2], vp[3], n_draws, n_clears, px[0], px[1], px[2], px[3], px[4], px[5],
           px[6], px[7]);
}

static double
now_ms(void)
{
   struct timespec t;
   clock_gettime(CLOCK_MONOTONIC, &t);
   return t.tv_sec * 1e3 + t.tv_nsec / 1e6;
}

/* the profile since the last report: GL time, the kernel's share, the wrappers by time and by submits */
static void
prof_report(double wall_ms)
{
   static double ms_per_tick;
   static uint64_t sub0, subt0, waitt0, waits0;
   if (ms_per_tick == 0) {
      mach_timebase_info_data_t tb;
      mach_timebase_info(&tb);
      ms_per_tick = (double)tb.numer / tb.denom / 1e6;
   }
   uint64_t sub = darwin_submits, subt = darwin_submit_ticks, waitt = darwin_wait_ticks, waits = darwin_waits;
   sca_log("sweetca: prof: GL %.0f of %.0f ms; %llu submits (%.0f ms in the call), %llu waits (%.0f ms)",
           prof_gl_ticks * ms_per_tick, wall_ms, (unsigned long long)(sub - sub0), (subt - subt0) * ms_per_tick,
           (unsigned long long)(waits - waits0), (waitt - waitt0) * ms_per_tick);
   sub0 = sub;
   subt0 = subt;
   waitt0 = waitt;
   waits0 = waits;
   darwin_prof_report(sca_log);
   sweet_profile_report(sca_log);
   prof_gl_ticks = 0;
   /* the 8 slowest wrappers, then every wrapper that submitted */
   uint8_t shown[PROF_SLOTS] = {0};
   for (int k = 0; k < 8; k++) {
      int best = -1;
      for (int i = 0; i < PROF_SLOTS; i++)
         if (prof[i].fn && !shown[i] && prof[i].ticks && (best < 0 || prof[i].ticks > prof[best].ticks))
            best = i;
      if (best < 0)
         break;
      shown[best] = 1;
   }
   for (int i = 0; i < PROF_SLOTS; i++) {
      if (prof[i].fn && (shown[i] || prof[i].submits))
         sca_log("sweetca: prof:   %-28s %7llu calls %7.1f ms %5llu submits", prof[i].fn,
                 (unsigned long long)prof[i].calls, prof[i].ticks * ms_per_tick, (unsigned long long)prof[i].submits);
      prof[i].calls = prof[i].ticks = prof[i].submits = 0;
   }
}

/* every 100 flushes (CA flushes once per frame): wall time, time in glFinish, draws */
static void
flush_stats(double wait_ms)
{
   static unsigned n, draws0;
   static double t0, waited;
   double t = now_ms();
   if (n == 0)
      t0 = t;
   waited += wait_ms;
   if (++n == 101) {
      sca_log("sweetca: 100 flushes in %.0f ms (%.1f ms each, %.1f in glFinish), %u draws", t - t0,
              (t - t0) / 100, waited / 100, n_draws - draws0);
      prof_report(t - t0);
      n = 1;
      t0 = t;
      waited = 0;
      draws0 = n_draws;
   }
}

static void
w_Flush(void *rctx)
{
   static unsigned traced;
   CUR(rctx);
   SWEET_SCOPE(sp_frame, SP_FRAME_FLUSH);
   (void)c;
   double t = now_ms();
   shadow_write_back(c);
   c->frame++;
   glFinish();
   flush_stats(now_ms() - t);
   if (trace_on && traced++ < 20)
      trace_fb("flush");
   POST(90);
}

static void
w_Finish(void *rctx)
{
   CUR(rctx);
   shadow_write_back(c);
   glFinish();
   POST(89);
}

static void
w_FinishObjectAPPLE(void *rctx, GLenum object, GLint name)
{
   (void)object;
   (void)name;
   w_Finish(rctx);
}

/* ---- strings and queries ---- */

static const GLubyte *
w_GetString(void *rctx, GLenum name)
{
   CUR(rctx);
   (void)c;
   const GLubyte *s = glGetString(name);
   /*
    * Without GL_EXT_shader_framebuffer_fetch CA drops every layer with a blend
    * mode filter. The extension is emulated (see draw_prep); say it is there.
    */
   if (name == GL_EXTENSIONS && s) {
      static char *ext;
      if (!ext && asprintf(&ext, "%s GL_EXT_shader_framebuffer_fetch", s) < 0)
         ext = NULL;
      return ext ? (const GLubyte *)ext : s;
   }
   if (!s)
      sca_log("sweetca: glGetString(%#x) = NULL (error %#x)", name, glGetError());
   return s;
}

static void
w_GetIntegerv(void *rctx, GLenum pname, GLint *v)
{
   CUR(rctx);
   switch (pname) {
   case GL_TEXTURE_BINDING_2D:
      *v = (GLint)c->bind2d[c->active];
      return;
   case GL_TEXTURE_BINDING_RECTANGLE_ARB:
      *v = (GLint)c->bindrect[c->active];
      return;
   case GL_MAX_RECTANGLE_TEXTURE_SIZE_ARB:
      glGetIntegerv(GL_MAX_TEXTURE_SIZE, v);
      return;
   default:
      glGetIntegerv(pname, v);
      POST(104);
   }
}

static void
w_PixelStorei(void *rctx, GLenum pname, GLint param)
{
   CUR(rctx);
   (void)c;
   if (pname == GL_UNPACK_CLIENT_STORAGE_APPLE)
      return;
   glPixelStorei(pname, param);
   POST(195);
}

/* ---- textures: 2D and rectangle bindings ---- */

static GLenum
tgt(struct sca_ctx *c, GLenum target)
{
   if (target != GL_TEXTURE_2D && target != GL_TEXTURE_RECTANGLE_ARB)
      return target;
   int u = c->active;
   GLuint want = target == GL_TEXTURE_2D ? c->bind2d[u] : c->bindrect[u];
   if (c->held[u] != want) {
      glBindTexture(GL_TEXTURE_2D, want);
      c->held[u] = want;
   }
   return GL_TEXTURE_2D;
}

static void
note_size(struct sca_ctx *c, GLuint tex, unsigned w, unsigned h)
{
   if (tex > 0 && tex < TEXMAX) {
      c->tex_w[tex] = w;
      c->tex_h[tex] = h;
   }
}

static void
w_ActiveTexture(void *rctx, GLenum unit)
{
   CUR(rctx);
   glActiveTexture(unit);
   unsigned u = unit - GL_TEXTURE0;
   c->active = u < UNITS ? u : UNITS - 1;
   POST(342);
}

static void
w_BindTexture(void *rctx, GLenum target, GLuint tex)
{
   CUR(rctx);
   if (target == GL_TEXTURE_2D || target == GL_TEXTURE_RECTANGLE_ARB) {
      int u = c->active;
      if (target == GL_TEXTURE_2D)
         c->bind2d[u] = tex;
      else
         c->bindrect[u] = tex;
      c->held[u] = tex;
      glBindTexture(GL_TEXTURE_2D, tex);
   } else {
      glBindTexture(target, tex);
   }
   POST(5);
}

/* GL unbinds deleted textures everywhere; so do the shadows */
static void
w_DeleteTextures(void *rctx, GLsizei n, const GLuint *tex)
{
   CUR(rctx);
   for (GLsizei i = 0; i < n; i++) {
      for (int u = 0; u < UNITS; u++) {
         if (c->bind2d[u] == tex[i])
            c->bind2d[u] = 0;
         if (c->bindrect[u] == tex[i])
            c->bindrect[u] = 0;
         if (c->held[u] == tex[i])
            c->held[u] = 0;
      }
      copy_forget(c, tex[i]);
      if (tex[i] < TEXMAX) {
         c->tex_w[tex[i]] = c->tex_h[tex[i]] = 0;
         c->tex_swizzled[tex[i]] = 0;
      }
      for (int f = 0; f < FBOMAX; f++) {
         if (c->fbo_tex[f] == tex[i])
            c->fbo_tex[f] = 0;
      }
   }
   glDeleteTextures(n, tex);
   POST(59);
}

static void
w_TexParameteri(void *rctx, GLenum target, GLenum pname, GLint param)
{
   CUR(rctx);
   glTexParameteri(tgt(c, target), pname, param);
   POST(304);
}

static void
w_TexParameterf(void *rctx, GLenum target, GLenum pname, GLfloat param)
{
   CUR(rctx);
   glTexParameterf(tgt(c, target), pname, param);
   POST(302);
}

static void
set_swizzle(struct sca_ctx *c, GLenum target, const GLint s[4], bool on)
{
   GLuint tex = c->held[c->active];
   if (tex >= TEXMAX || (!on && !c->tex_swizzled[tex]))
      return;
   c->tex_swizzled[tex] = on;
   static const GLint ident[4] = {GL_RED, GL_GREEN, GL_BLUE, GL_ALPHA};
   const GLint *m = on ? s : ident;
   glTexParameteri(target, GL_TEXTURE_SWIZZLE_R, m[0]);
   glTexParameteri(target, GL_TEXTURE_SWIZZLE_G, m[1]);
   glTexParameteri(target, GL_TEXTURE_SWIZZLE_B, m[2]);
   glTexParameteri(target, GL_TEXTURE_SWIZZLE_A, m[3]);
}

/* Apple's ES takes internalformat GL_RGBA with format GL_BGRA_EXT; Mesa wants BGRA for both */
static void
w_TexImage2D(void *rctx, GLenum target, GLint level, GLint ifmt, GLsizei w, GLsizei h,
             GLint border, GLenum format, GLenum type, const void *pixels)
{
   CUR(rctx);
   GLenum t = tgt(c, target);
   if (trace_on > 1)
      sca_log("sweetca: TexImage2D tex %u target %#x level %d ifmt %#x %dx%d fmt %#x type %#x data %p", c->held[c->active], target, level,
              ifmt, w, h, format, type, pixels);
   set_swizzle(c, t, NULL, false);
   if (format == GL_BGRA_EXT_ && (ifmt == GL_RGBA || ifmt == GL_RGBA8))
      ifmt = GL_BGRA_EXT_;
   glTexImage2D(t, level, ifmt, w, h, border, format, type, pixels);
   POST(301);
   if (level == 0) {
      note_size(c, c->held[c->active], w, h);
      copy_forget(c, c->held[c->active]);
   }
}

static void
w_TexSubImage2D(void *rctx, GLenum target, GLint level, GLint x, GLint y, GLsizei w, GLsizei h,
                GLenum format, GLenum type, const void *pixels)
{
   CUR(rctx);
   glTexSubImage2D(tgt(c, target), level, x, y, w, h, format, type, pixels);
   POST(307);
}

static void
w_CompressedTexImage2D(void *rctx, GLenum target, GLint level, GLenum ifmt, GLsizei w, GLsizei h,
                       GLint border, GLsizei size, const void *data)
{
   CUR(rctx);
   glCompressedTexImage2D(tgt(c, target), level, ifmt, w, h, border, size, data);
   POST(380);
   if (level == 0) {
      note_size(c, c->held[c->active], w, h);
      copy_forget(c, c->held[c->active]);
   }
}

static void
w_CopyTexSubImage2D(void *rctx, GLenum target, GLint level, GLint xo, GLint yo, GLint x, GLint y,
                    GLsizei w, GLsizei h)
{
   CUR(rctx);
   if (trace_on > 1)
      sca_log("sweetca: CopyTexSubImage2D tex %u (%ux%u) level %d at %d,%d from %d,%d size %dx%d, fbo %u", c->held[c->active],
              c->tex_w[c->held[c->active] % TEXMAX], c->tex_h[c->held[c->active] % TEXMAX], level, xo, yo, x, y, w, h,
              c->fbo);
   glCopyTexSubImage2D(tgt(c, target), level, xo, yo, x, y, w, h);
   if (trace_on > 1) {
      /* what the copy holds, and what it copied from */
      static int shown;
      GLuint dst = c->held[c->active], tmp = 0;
      uint8_t src[4] = {0}, got[4] = {0};
      if (shown++ < 8 && dst) {
         glReadPixels(x + w / 2, y + h / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, src);
         glGenFramebuffers(1, &tmp);
         glBindFramebuffer(GL_READ_FRAMEBUFFER, tmp);
         glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, dst, 0);
         glReadPixels(xo + w / 2, yo + h / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, got);
         glBindFramebuffer(GL_READ_FRAMEBUFFER, c->fbo);
         glDeleteFramebuffers(1, &tmp);
         sca_log("sweetca:   source center %02x%02x%02x%02x, copy center %02x%02x%02x%02x", src[0], src[1], src[2], src[3],
                 got[0], got[1], got[2], got[3]);
      }
   }
   POST(56);
}

static void
w_GenerateMipmap(void *rctx, GLenum target)
{
   CUR(rctx);
   glGenerateMipmap(tgt(c, target));
   copy_mipped(c, c->held[c->active]);
   POST(681);
}

/* ---- framebuffers ---- */

static void
w_BindFramebuffer(void *rctx, GLenum target, GLuint fb)
{
   CUR(rctx);
   if (target == GL_FRAMEBUFFER || target == GL_DRAW_FRAMEBUFFER)
      c->fbo = fb < FBOMAX ? fb : 0;
   glBindFramebuffer(target, fb);
   POST(672);
}

static void
w_DeleteFramebuffers(void *rctx, GLsizei n, const GLuint *fb)
{
   CUR(rctx);
   for (GLsizei i = 0; i < n; i++) {
      if (fb[i] < FBOMAX)
         c->fbo_tex[fb[i]] = 0;
      if (c->fbo == fb[i])
         c->fbo = 0;
   }
   glDeleteFramebuffers(n, fb);
   POST(673);
}

static void
w_FramebufferTexture2D(void *rctx, GLenum target, GLenum attachment, GLenum textarget, GLuint tex,
                       GLint level)
{
   CUR(rctx);
   if (attachment == GL_COLOR_ATTACHMENT0 && c->fbo > 0 && c->fbo < FBOMAX &&
       (target == GL_FRAMEBUFFER || target == GL_DRAW_FRAMEBUFFER))
      c->fbo_tex[c->fbo] = tex;
   glFramebufferTexture2D(target, attachment,
                          textarget == GL_TEXTURE_RECTANGLE_ARB ? GL_TEXTURE_2D : textarget, tex,
                          level);
   POST(677);
}

/* ---- shaders ---- */

/*
 * Apple's shader compiler takes what Mesa's does not, and sees extensions Mesa
 * lacks. Rewritten sources:
 *  - sampler2DRect: a sampler2D, texture2DRect scaling the texel coordinate by
 *    sca_rect_scale (1/size, set before each draw);
 *  - gl_LastFragData[0]: a read of sca_fb, the render target's texture;
 *  - coord_arg, which CA's inverted-mask shader uses without declaring.
 * New declarations go after the leading preprocessor lines (extension
 * directives must precede all other tokens).
 */
static const char rect_prelude[] =
   "#define sampler2DRect sampler2D\n"
   "#define texture2DRect(s, c) texture2D(s, (c) * sca_rect_scale)\n"
   "uniform highp vec2 sca_rect_scale;\n";
static const char fb_decl[] =
   "uniform lowp sampler2D sca_fb;\n"
   "uniform highp vec2 sca_fb_scale;\n";
static const char fb_read[] = "texture2D(sca_fb, gl_FragCoord.xy * sca_fb_scale)";
static const char coord_arg_decl[] = "uniform highp vec4 coord_arg;\n";

/* offset after the leading lines that are blank or start with '#' */
static size_t
after_directives(const char *src)
{
   size_t at = 0;
   for (;;) {
      size_t i = at;
      while (src[i] == ' ' || src[i] == '\t' || src[i] == '\r')
         i++;
      if (src[i] == '\n') {
         at = i + 1;
      } else if (src[i] == '#') {
         const char *nl = strchr(src + i, '\n');
         if (!nl)
            return strlen(src);
         at = nl - src + 1;
      } else {
         return at;
      }
   }
}

static char *
insert_at(char *src, size_t at, const char *text)
{
   size_t n = strlen(src), t = strlen(text);
   char *out = malloc(n + t + 1);
   memcpy(out, src, at);
   memcpy(out + at, text, t);
   memcpy(out + at + t, src + at, n - at + 1);
   free(src);
   return out;
}

static bool
has_word(const char *src, const char *word)
{
   size_t l = strlen(word);
   for (const char *p = strstr(src, word); p; p = strstr(p + 1, word)) {
      bool before = p == src || !(isalnum((unsigned char)p[-1]) || p[-1] == '_');
      bool after = !(isalnum((unsigned char)p[l]) || p[l] == '_');
      if (before && after)
         return true;
   }
   return false;
}

/*
 * Texture functions of CA's GL renderer that QuartzCore has no tex_fragment_shaders
 * entry for (create_shader then fails and the draw is dropped); install_texfns()
 * points those entries at the sca_ expressions below, and w_ShaderSource adds their
 * definitions to any shader that calls them. The first two read color_matrix[0..3]
 * (the input's r, g, b and a columns) and color_matrix[4] (bias).
 *  - sca_vcm (0x2d, render_vibrant_color_matrix: Control Center plates): the
 *    destination through the matrix, unpremultiplied, mixed in by the source's
 *    alpha (what CA's software renderer does);
 *  - sca_cm4 (0x14, a matrix filter without its premultiply flag, next to 0x13
 *    colorMatrix4x4Bias: lock screen clock): the matrix on the premultiplied
 *    colour as it is;
 *  - sca_nop / sca_vblur (0x26 / 0x27, variable blur, notification centre): CA
 *    blurs by sampling a mip chain of a copy of the source, which a GLES surface
 *    (level 0 only) cannot hold, so the mip passes draw nothing and the second
 *    blurs the source in one pass: a 24 tap golden angle disc, Gaussian weighted,
 *    radius = mask alpha (1 - alpha with minmax_dir.y) * minmax_dir.x / 2.
 */
static const char fn_vcm[] =
   "lowp vec4 sca_vcm(lowp vec4 s) {\n"
   "  lowp vec4 d = gl_LastFragData[0];\n"
   "  lowp vec4 u = vec4(d.rgb / max(d.a, .005), d.a);\n"
   "  u = clamp(u.r * color_matrix[0] + u.g * color_matrix[1] + u.b * color_matrix[2]\n"
   "    + u.a * color_matrix[3] + color_matrix[4], 0., 1.);\n"
   "  u.rgb *= u.a;\n"
   "  return mix(d, d.a > 0. ? u : vec4(0.), s.a);\n"
   "}\n";
static const char fn_cm4[] =
   "lowp vec4 sca_cm4(lowp vec4 s) {\n"
   "  lowp vec4 u = clamp(s.r * color_matrix[0] + s.g * color_matrix[1] + s.b * color_matrix[2]\n"
   "    + s.a * color_matrix[3] + color_matrix[4], 0., 1.);\n"
   "  return vec4(min(u.rgb, u.a), u.a);\n"
   "}\n";
static const char fn_nop[] =
   "lowp vec4 sca_nop() {\n"
   "  discard;\n"
   "  return vec4(0.);\n"
   "}\n";
static const char fn_vblur[] =
   "lowp vec4 sca_vblur(lowp vec4 m) {\n"
   "  highp vec2 tc = texcoord0_0;\n"
   "  highp vec2 px = vec2(length(vec2(dFdx(tc.x), dFdy(tc.x))), length(vec2(dFdx(tc.y), dFdy(tc.y))));\n"
   "  mediump float r = (minmax_dir.y > .5 ? 1. - m.a : m.a) * minmax_dir.x * .5;\n"
   "  mediump vec4 acc = texture2D(texture0, tc);\n"
   "  if (r < .5)\n"
   "    return acc;\n"
   "  mediump float wsum = 1.;\n"
   "  for (int i = 1; i <= 24; i++) {\n"
   "    mediump float f = float(i) / 24.;\n"
   "    mediump float ang = float(i) * 2.3999632;\n"
   "    mediump float w = exp(-2. * f);\n"
   "    acc += w * texture2D(texture0, tc + vec2(cos(ang), sin(ang)) * (sqrt(f) * r) * px);\n"
   "    wsum += w;\n"
   "  }\n"
   "  return acc / wsum;\n"
   "}\n";
static const char fn_cm_decl[] = "uniform lowp vec4 color_matrix[5];\n";
static const char fn_vblur_decl[] = "uniform highp vec4 minmax_dir;\n";
static const char fn_derivatives[] = "#extension GL_OES_standard_derivatives : enable\n";

/* the sca_ texture functions the source calls, defined before main(); the source is freed */
static char *
add_texfns(char *src)
{
   bool vcm = strstr(src, "sca_vcm(") != NULL, cm4 = strstr(src, "sca_cm4(") != NULL;
   bool nop = strstr(src, "sca_nop(") != NULL, vblur = strstr(src, "sca_vblur(") != NULL;
   if (!strstr(src, "void main") || !(vcm || cm4 || nop || vblur))
      return src;
   if (vblur)
      src = insert_at(src, after_directives(src), fn_derivatives);
   if ((vcm || cm4) && !strstr(src, "color_matrix["))
      src = insert_at(src, strstr(src, "void main") - src, fn_cm_decl);
   if (vblur && !strstr(src, "minmax_dir"))
      src = insert_at(src, strstr(src, "void main") - src, fn_vblur_decl);
   if (vcm)
      src = insert_at(src, strstr(src, "void main") - src, fn_vcm);
   if (cm4)
      src = insert_at(src, strstr(src, "void main") - src, fn_cm4);
   if (nop)
      src = insert_at(src, strstr(src, "void main") - src, fn_nop);
   if (vblur)
      src = insert_at(src, strstr(src, "void main") - src, fn_vblur);
   return src;
}

static void
w_ShaderSource(void *rctx, GLuint shader, GLsizei count, const GLchar *const *string,
               const GLint *length)
{
   CUR(rctx);
   size_t n = 0;
   for (GLsizei i = 0; i < count; i++)
      n += length && length[i] >= 0 ? (size_t)length[i] : strlen(string[i]);
   char *src = malloc(n + 1), *p = src;
   for (GLsizei i = 0; i < count; i++) {
      size_t l = length && length[i] >= 0 ? (size_t)length[i] : strlen(string[i]);
      memcpy(p, string[i], l);
      p += l;
   }
   *p = 0;

   uint8_t flags = 0;
   char rect_sampler[32] = "";
   const char *rect = strstr(src, "sampler2DRect");
   if (rect) {
      const char *name = rect + strlen("sampler2DRect");
      while (*name == ' ' || *name == '\t')
         name++;
      size_t l = strspn(name, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_");
      snprintf(rect_sampler, sizeof(rect_sampler), "%.*s", (int)l, name);
      flags |= OBJ_RECT;
      src = insert_at(src, after_directives(src), rect_prelude);
   }
   if (has_word(src, "coord_arg") && !strstr(src, "vec4 coord_arg"))
      src = insert_at(src, after_directives(src), coord_arg_decl);
   src = add_texfns(src);
   if (strstr(src, "gl_LastFragData")) {
      flags |= OBJ_FBFETCH;
      /* blank the extension directive */
      char *ext = strstr(src, "#extension GL_EXT_shader_framebuffer_fetch");
      for (char *e = ext; e && *e && *e != '\n'; e++)
         *e = ' ';
      src = insert_at(src, after_directives(src), fb_decl);
      /* each read becomes a texture read */
      size_t reads = 0;
      for (char *r = strstr(src, "gl_LastFragData[0]"); r; r = strstr(r + 1, "gl_LastFragData[0]"))
         reads++;
      char *out = malloc(strlen(src) + reads * sizeof(fb_read) + 1), *o = out;
      for (const char *q = src; *q;) {
         if (strncmp(q, "gl_LastFragData[0]", 18) == 0) {
            memcpy(o, fb_read, sizeof(fb_read) - 1);
            o += sizeof(fb_read) - 1;
            q += 18;
         } else {
            *o++ = *q++;
         }
      }
      *o = 0;
      free(src);
      src = out;
   }
   if (shader < OBJMAX) {
      c->obj[shader].flags = flags;
      snprintf(c->obj[shader].rect_sampler, sizeof(c->obj[shader].rect_sampler), "%s", rect_sampler);
   }
   const GLchar *one = src;
   glShaderSource(shader, 1, &one, NULL);
   if (trace_on > 1) {
      sca_log("sweetca: shader %u source (%zu bytes):", shader, strlen(src));
      for (size_t i = 0, n2 = strlen(src); i < n2; i += 700)
         sca_log("sweetca: | %.700s", src + i);
   }
   free(src);
   POST(595);
}

/* after a failed compile: the info log and the source, once per failure up to a limit */
static void
log_compile_failure(GLuint shader)
{
   static int logged;
   GLint ok = 0;
   glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
   if (ok || logged++ >= 12)
      return;
   char log[1024] = "", src[3000] = "";
   glGetShaderInfoLog(shader, sizeof(log), NULL, log);
   glGetShaderSource(shader, sizeof(src), NULL, src);
   sca_log("sweetca: shader %u failed to compile: %.600s", shader, log);
   sca_log("sweetca: source:\n%s", src);
}

static void
w_CompileShader2(void *rctx, GLuint shader)
{
   CUR(rctx);
   (void)c;
   glCompileShader(shader);
   log_compile_failure(shader);
   POST(596);
}

static void
w_LinkProgram(void *rctx, GLuint program)
{
   CUR(rctx);
   glLinkProgram(program);
   GLint ok = 0;
   glGetProgramiv(program, GL_LINK_STATUS, &ok);
   if (!ok) {
      static int logged;
      if (logged++ < 12) {
         char log[1024] = "";
         glGetProgramInfoLog(program, sizeof(log), NULL, log);
         sca_log("sweetca: program %u failed to link: %.600s", program, log);
      }
   } else if (program < OBJMAX) {
      struct sca_obj *p = &c->obj[program];
      GLuint shaders[8];
      GLsizei n = 0;
      glGetAttachedShaders(program, 8, &n, shaders);
      p->flags = 0;
      p->rect_sampler_loc = p->rect_scale_loc = p->fb_sampler_loc = p->fb_scale_loc = -1;
      for (GLsizei i = 0; i < n; i++) {
         if (shaders[i] >= OBJMAX)
            continue;
         struct sca_obj *s = &c->obj[shaders[i]];
         if (s->flags & OBJ_RECT) {
            p->flags |= OBJ_RECT;
            p->rect_sampler_loc = glGetUniformLocation(program, s->rect_sampler);
            p->rect_scale_loc = glGetUniformLocation(program, "sca_rect_scale");
         }
         if (s->flags & OBJ_FBFETCH) {
            p->flags |= OBJ_FBFETCH;
            p->fb_sampler_loc = glGetUniformLocation(program, "sca_fb");
            p->fb_scale_loc = glGetUniformLocation(program, "sca_fb_scale");
         }
      }
   }
   POST(599);
}

/* ---- draws ---- */

static void
set_unit(struct sca_ctx *c, int u, GLuint want)
{
   if (c->held[u] == want)
      return;
   glActiveTexture(GL_TEXTURE0 + u);
   glBindTexture(GL_TEXTURE_2D, want);
   glActiveTexture(GL_TEXTURE0 + c->active);
   c->held[u] = want;
}

static void
texel_scale(struct sca_ctx *c, GLuint tex, GLint loc)
{
   SWEET_SCOPE(sp_uniform, SP_PREP_UNIFORM);
   unsigned w = tex < TEXMAX ? c->tex_w[tex] : 0, h = tex < TEXMAX ? c->tex_h[tex] : 0;
   glUniform2f(loc, w ? 1.0f / w : 1.0f, h ? 1.0f / h : 1.0f);
}

/*
 * Before a draw: each unit holds what the program samples there (the
 * rectangle texture on the unit of its sampler2DRect, the 2D texture
 * elsewhere), the rectangle scale is set, the framebuffer-fetch texture is
 * bound, and a texture barrier is issued when the draw samples the texture it
 * renders into (CA reads the destination that way; Apple's GPUs return what
 * memory held when the pass began).
 */
static void
draw_prep(struct sca_ctx *c)
{
   SWEET_SCOPE(sp_prep, SP_PREP);
   struct sca_obj *p = c->program && c->program < OBJMAX ? &c->obj[c->program] : NULL;
   int runit = -1;
   if (p && (p->flags & OBJ_RECT)) {
      GLint unit = 0;
      if (p->rect_sampler_loc >= 0) {
         SWEET_SCOPE(sp_query, SP_PREP_QUERY);
         glGetUniformiv(c->program, p->rect_sampler_loc, &unit);
      }
      runit = unit;
   }
   for (int u = 0; u < UNITS; u++) {
      if (u == c->fbfetch_unit)
         continue;
      GLuint want = u == runit ? c->bindrect[u] : c->bind2d[u];
      if (c->held[u] != want)
         set_unit(c, u, want);
      if (want && want < TEXMAX && c->copies[want]) {
         SWEET_SCOPE(sp_refresh, SP_PREP_REFRESH);
         copy_refresh(c, u, want);
      }
   }
   if (runit >= 0 && runit < UNITS && p->rect_scale_loc >= 0)
      texel_scale(c, c->bindrect[runit], p->rect_scale_loc);

   GLuint fbtex = c->fbo < FBOMAX ? c->fbo_tex[c->fbo] : 0;
   if (p && (p->flags & OBJ_FBFETCH) && fbtex) {
      set_unit(c, c->fbfetch_unit, fbtex);
      if (!c->fb_sampler) {
         glActiveTexture(GL_TEXTURE0 + c->fbfetch_unit);
         glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
         glActiveTexture(GL_TEXTURE0 + c->active);
      }
      if (p->fb_sampler_loc >= 0) {
         SWEET_SCOPE(sp_sampler, SP_PREP_UNIFORM);
         glUniform1i(p->fb_sampler_loc, c->fbfetch_unit);
      }
      if (p->fb_scale_loc >= 0)
         texel_scale(c, fbtex, p->fb_scale_loc);
   }
   if (fbtex) {
      uint32_t bound_feedback = 0;
      for (int u = 0; u < UNITS; u++) {
         if (c->held[u] == fbtex)
            bound_feedback |= UINT32_C(1) << u;
      }
      if (bound_feedback) {
         /* The reserved fetch unit stays bound between programs. A binding
          * alone does not mean this draw reads it. Mesa tracks active samplers
          * across program switches, relinks, arrays and uniform-unit changes.
          * Keep the barrier for any active feedback, including non-fetch reads.
          */
         bool needed = (bound_feedback & sgl_sampled_2d_units(c->gl)) != 0;
         SWEET_EVENT(needed ? SPE_BARRIER_NEEDED : SPE_BARRIER_SKIPPED, 1);
         if (needed || !active_barriers) {
            SWEET_SCOPE(sp_barrier, SP_PREP_BARRIER);
            sgl_texture_barrier();
         }
      }
   }
}

/* SWEETCA_TRACE=2: what each of the first draws draws with and into */
static void
trace_draw(struct sca_ctx *c, GLenum mode, GLsizei count)
{
   static unsigned shown;
   if (trace_on < 2 || shown >= 60)
      return;
   shown++;
   GLint vp[4] = {0}, sc[4] = {0}, blend = glIsEnabled(GL_BLEND), scen = glIsEnabled(GL_SCISSOR_TEST);
   glGetIntegerv(GL_VIEWPORT, vp);
   glGetIntegerv(GL_SCISSOR_BOX, sc);
   GLuint fbtex = c->fbo < FBOMAX ? c->fbo_tex[c->fbo] : 0;
   char tex[200] = "";
   size_t l = 0;
   for (int u = 0; u < UNITS && l < sizeof(tex) - 40; u++) {
      GLuint t = c->held[u];
      if (t)
         l += snprintf(tex + l, sizeof(tex) - l, " u%d=%u(%ux%u%s)", u, t, t < TEXMAX ? c->tex_w[t] : 0,
                       t < TEXMAX ? c->tex_h[t] : 0, u == c->fbfetch_unit ? ",fb" : "");
   }
   sca_log("sweetca: draw %u: prog %u mode %#x n %d fbo %u (tex %u %ux%u) vp %d,%d %dx%d scissor %d %d,%d %dx%d blend %d%s",
           shown, c->program, mode, count, c->fbo, fbtex, fbtex < TEXMAX ? c->tex_w[fbtex] : 0,
           fbtex < TEXMAX ? c->tex_h[fbtex] : 0, vp[0], vp[1], vp[2], vp[3], scen, sc[0], sc[1], sc[2], sc[3],
           blend, tex);
}

/*
 * Merged submits (Mesa darwin: no implicit sync) reach the GPU only when a fence
 * is needed, at CA's per-frame finish: the GPU then idles while the CPU builds the
 * frame and the CPU waits while the GPU draws it. Every kick_every draws, a fence
 * checked without waiting sends what is queued, so both work at once. With Mesa's
 * threaded context that check would only queue a flush, so sgl_kick has the
 * driver thread send it. SWEETCA_KICK=N (default 32, 0: off).
 *
 * The driver thread does most of each draw's CPU work, so it gets the priority
 * of the thread CA draws from (its display thread), once per context.
 */
static unsigned kick_every = 32;
static __thread unsigned kick_draws;

static void
kick_after_draw(struct sca_ctx *c)
{
   if (!c->followed) {
      c->followed = true;
      sgl_follow_thread(c->gl);
   }
   if (kick_every == 0 || ++kick_draws < kick_every)
      return;
   kick_draws = 0;
   SWEET_SCOPE(sp_kick, SP_KICK);
   if (sgl_kick(c->gl))
      return;
   GLsync s = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);
   if (s) {
      (void)glClientWaitSync(s, GL_SYNC_FLUSH_COMMANDS_BIT, 0);
      glDeleteSync(s);
   }
}

static void
w_DrawArrays(void *rctx, GLenum mode, GLint first, GLsizei count)
{
   CUR(rctx);
   SWEET_SCOPE(sp_draw, SP_DRAW);
   draw_prep(c);
   n_draws++;
   trace_draw(c, mode, count);
   {
      SWEET_SCOPE(sp_call, SP_DRAW_CALL);
      glDrawArrays(mode, first, count);
   }
   shadow_drawn(c);
   kick_after_draw(c);
   POST(65);
}

static void
w_DrawElements(void *rctx, GLenum mode, GLsizei count, GLenum type, const void *indices)
{
   CUR(rctx);
   SWEET_SCOPE(sp_draw, SP_DRAW);
   draw_prep(c);
   n_draws++;
   trace_draw(c, mode, count);
   {
      SWEET_SCOPE(sp_call, SP_DRAW_CALL);
      glDrawElements(mode, count, type, indices);
   }
   shadow_drawn(c);
   kick_after_draw(c);
   POST(67);
}

static void
w_Clear(void *rctx, GLbitfield mask)
{
   CUR(rctx);
   (void)c;
   n_clears++;
   glClear(mask);
   shadow_drawn(c);
   POST(10);
}

/* ---- IOSurfaces as texture storage ---- */

static void
fourcc_str(uint32_t f, char out[5])
{
   for (int i = 0; i < 4; i++) {
      unsigned ch = (f >> (24 - 8 * i)) & 0xff;
      out[i] = ch >= 0x20 && ch < 0x7f ? (char)ch : '.';
   }
   out[4] = 0;
}

/* how a surface's bytes are read: the sweetgl format and the texture swizzle that makes them right */
struct surf_fmt {
   enum sgl_format f;
   GLint swz[4];
   bool swizzled;
   GLenum gl_format, gl_type, gl_internal; /* for the copy path */
};

static const GLint SWZ_A8[4] = {GL_ZERO, GL_ZERO, GL_ZERO, GL_RED};
static const GLint SWZ_L8[4] = {GL_RED, GL_RED, GL_RED, GL_ONE};
static const GLint SWZ_LA8[4] = {GL_RED, GL_RED, GL_RED, GL_GREEN};

static bool
fmt_from_gl(GLenum format, GLenum type, struct surf_fmt *o)
{
   bool half = type == GL_HALF_FLOAT || type == GL_HALF_FLOAT_OES_;
   memset(o, 0, sizeof(*o));
   o->gl_format = format;
   o->gl_type = type ? type : GL_UNSIGNED_BYTE;
   switch (format) {
   case GL_BGRA_EXT_:
      o->f = SGL_FMT_BGRA8;
      o->gl_internal = GL_BGRA_EXT_;
      return true;
   case GL_RGBA:
      o->f = half ? SGL_FMT_RGBA16F : SGL_FMT_RGBA8;
      o->gl_internal = half ? GL_RGBA16F : GL_RGBA8;
      return true;
   case GL_RED:
      o->f = SGL_FMT_R8;
      o->gl_internal = GL_R8;
      return !half;
   case GL_RG:
      o->f = SGL_FMT_RG8;
      o->gl_internal = GL_RG8;
      return !half;
   case GL_ALPHA:
      o->f = SGL_FMT_R8;
      memcpy(o->swz, SWZ_A8, sizeof(o->swz));
      o->swizzled = true;
      o->gl_internal = GL_ALPHA;
      return !half;
   case GL_LUMINANCE:
      o->f = SGL_FMT_R8;
      memcpy(o->swz, SWZ_L8, sizeof(o->swz));
      o->swizzled = true;
      o->gl_internal = GL_LUMINANCE;
      return !half;
   case GL_LUMINANCE_ALPHA:
      o->f = SGL_FMT_RG8;
      memcpy(o->swz, SWZ_LA8, sizeof(o->swz));
      o->swizzled = true;
      o->gl_internal = GL_LUMINANCE_ALPHA;
      return !half;
   default:
      return false;
   }
}

/* CA's surfaces that carry no GL format: by IOSurface pixel format, else bytes per element */
static bool
fmt_from_surface(uint32_t fourcc, size_t bpe, struct surf_fmt *o)
{
   switch (fourcc) {
   case 'BGRA':
      return fmt_from_gl(GL_BGRA_EXT_, GL_UNSIGNED_BYTE, o);
   case 'RGBA':
      return fmt_from_gl(GL_RGBA, GL_UNSIGNED_BYTE, o);
   case 'RGhA':
      return fmt_from_gl(GL_RGBA, GL_HALF_FLOAT, o);
   case 'L008':
      return fmt_from_gl(GL_RED, GL_UNSIGNED_BYTE, o);
   case 'L016':
      return fmt_from_gl(GL_RG, GL_UNSIGNED_BYTE, o);
   case 'A008':
      return fmt_from_gl(GL_ALPHA, GL_UNSIGNED_BYTE, o);
   case 'LA08':
      return fmt_from_gl(GL_LUMINANCE_ALPHA, GL_UNSIGNED_BYTE, o);
   case 0:
      return bpe == 4   ? fmt_from_gl(GL_BGRA_EXT_, GL_UNSIGNED_BYTE, o)
             : bpe == 8 ? fmt_from_gl(GL_RGBA, GL_HALF_FLOAT, o)
             : bpe == 1 ? fmt_from_gl(GL_RED, GL_UNSIGNED_BYTE, o)
                        : false;
   default:
      return false;
   }
}

/*
 * A surface whose rows the GPU cannot take in place (CA's own bitmaps are not
 * 64-byte aligned): its pixels are uploaded as a snapshot.
 */
static bool
copy_surface(struct sca_ctx *c, IOSurfaceRef s, GLenum target, const struct surf_fmt *f, size_t w,
             size_t h, size_t pitch, size_t bpe, bool invert)
{
   if (bpe == 0 || pitch % bpe != 0)
      return false;
   if (IOSurfaceLock(s, kIOSurfaceLockReadOnly, NULL) != 0)
      return false;
   const void *base = IOSurfaceGetBaseAddress(s);
   GLint row = 0, align = 4;
   glGetIntegerv(GL_UNPACK_ROW_LENGTH, &row);
   glGetIntegerv(GL_UNPACK_ALIGNMENT, &align);
   glPixelStorei(GL_UNPACK_ROW_LENGTH, (GLint)(pitch / bpe));
   glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
   GLenum e;
   if (invert) {
      /* rows bottom first: the texture is the surface flipped vertically */
      uint8_t *flipped = malloc(pitch * h);
      for (size_t y = 0; flipped && y < h; y++)
         memcpy(flipped + y * pitch, (const uint8_t *)base + (h - 1 - y) * pitch, pitch);
      glTexImage2D(target, 0, f->gl_internal, (GLsizei)w, (GLsizei)h, 0, f->gl_format, f->gl_type,
                   flipped ? flipped : base);
      free(flipped);
   } else {
      glTexImage2D(target, 0, f->gl_internal, (GLsizei)w, (GLsizei)h, 0, f->gl_format, f->gl_type, base);
   }
   e = glGetError();
   glPixelStorei(GL_UNPACK_ROW_LENGTH, row);
   glPixelStorei(GL_UNPACK_ALIGNMENT, align);
   IOSurfaceUnlock(s, kIOSurfaceLockReadOnly, NULL);
   if (e != GL_NO_ERROR)
      sca_log("sweetca: copy of surface %u (%zux%zu, pitch %zu) failed: GL error %#x",
              IOSurfaceGetID(s), w, h, pitch, e);
   note_size(c, c->held[c->active], w, h);
   return e == GL_NO_ERROR;
}

/*
 * A copied surface is a snapshot, but its owner may draw into it again later (CA
 * binds each surface once).
 * Copy it again before a draw that samples it once the surface's seed (moved by
 * every write unlock) has changed. (Round s3-d copied every sampled copy once per
 * frame instead, on the guess that writers skip the lock; the missing labels were
 * the swizzle in bind_surface, so that is undone.)
 */
struct sca_copy {
   IOSurfaceRef s;
   uint32_t seed;
   struct surf_fmt f;
   size_t w, h, pitch, bpe;
   bool flip, mipped;
   bool target, dirty; /* a shadow render target: written back to the surface after draws */
   unsigned frame;     /* c->frame when last copied */
};

static unsigned n_refreshes;

static void
copy_forget(struct sca_ctx *c, GLuint tex)
{
   if (tex == 0 || tex >= TEXMAX || !c->copies[tex])
      return;
   CFRelease(c->copies[tex]->s);
   free(c->copies[tex]);
   c->copies[tex] = NULL;
}

static void
copy_note(struct sca_ctx *c, GLuint tex, IOSurfaceRef s, uint32_t seed, const struct surf_fmt *f, size_t w,
          size_t h, size_t pitch, size_t bpe, bool flip)
{
   copy_forget(c, tex);
   struct sca_copy *k = tex && tex < TEXMAX ? calloc(1, sizeof(*k)) : NULL;
   if (!k)
      return;
   CFRetain(s);
   *k = (struct sca_copy){s, seed, *f, w, h, pitch, bpe, flip, false, false, false, c->frame};
   c->copies[tex] = k;
}

static void
copy_mipped(struct sca_ctx *c, GLuint tex)
{
   if (tex && tex < TEXMAX && c->copies[tex])
      c->copies[tex]->mipped = true;
}

static void
copy_refresh(struct sca_ctx *c, int u, GLuint tex)
{
   struct sca_copy *k = c->copies[tex];
   uint32_t seed = IOSurfaceGetSeed(k->s);
   if (k->dirty || seed == k->seed)
      return;
   k->seed = seed;
   k->frame = c->frame;
   int active = c->active;
   glActiveTexture(GL_TEXTURE0 + u);
   c->active = u;
   copy_surface(c, k->s, GL_TEXTURE_2D, &k->f, k->w, k->h, k->pitch, k->bpe, k->flip);
   if (k->mipped)
      glGenerateMipmap(GL_TEXTURE_2D);
   c->active = active;
   glActiveTexture(GL_TEXTURE0 + active);
   if (n_refreshes++ < 5 || n_refreshes % 1000 == 0)
      sca_log("sweetca: surface %u (%zux%zu) copied again in frame %u, %u copies so far", IOSurfaceGetID(k->s),
              k->w, k->h, c->frame, n_refreshes);
}

/*
 * Render targets the GPU cannot use in place (CA's offscreen surfaces come with rows
 * of 92 or 4512 bytes, the a5xx wants multiples of 64): a texture of the same size
 * stands in for the surface, filled from it, and the draws are written back into the
 * surface before CA flushes or finishes, so other processes and the display see them.
 */
static void
shadow_drawn(struct sca_ctx *c)
{
   GLuint t = c->fbo && c->fbo < FBOMAX ? c->fbo_tex[c->fbo] : 0;
   if (t && t < TEXMAX && c->copies[t] && c->copies[t]->target)
      c->copies[t]->dirty = true;
}

static void
shadow_write_back(struct sca_ctx *c)
{
   static unsigned told;
   GLint prev = -1;
   for (int i = 0; i < 64; i++) {
      GLuint tex = c->shadows[i];
      struct sca_copy *k = tex ? c->copies[tex] : NULL;
      if (tex && (!k || !k->target)) {
         c->shadows[i] = 0; /* forgotten meanwhile */
         continue;
      }
      if (!k || !k->dirty)
         continue;
      k->dirty = false;
      if (k->bpe != 4 || k->pitch % 4 != 0 || IOSurfaceLock(k->s, 0, NULL) != 0)
         continue;
      if (prev < 0)
         glGetIntegerv(GL_FRAMEBUFFER_BINDING, &prev);
      if (!c->readback_fbo)
         glGenFramebuffers(1, &c->readback_fbo);
      glBindFramebuffer(GL_FRAMEBUFFER, c->readback_fbo);
      glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
      GLint row = 0, align = 4;
      glGetIntegerv(GL_PACK_ROW_LENGTH, &row);
      glGetIntegerv(GL_PACK_ALIGNMENT, &align);
      glPixelStorei(GL_PACK_ROW_LENGTH, (GLint)(k->pitch / 4));
      glPixelStorei(GL_PACK_ALIGNMENT, 1);
      glReadPixels(0, 0, (GLsizei)k->w, (GLsizei)k->h, k->f.gl_format, k->f.gl_type, IOSurfaceGetBaseAddress(k->s));
      GLenum e = glGetError();
      glPixelStorei(GL_PACK_ROW_LENGTH, row);
      glPixelStorei(GL_PACK_ALIGNMENT, align);
      glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, 0, 0);
      IOSurfaceUnlock(k->s, 0, NULL);
      k->seed = IOSurfaceGetSeed(k->s);
      if (told++ < 20 || e != GL_NO_ERROR)
         sca_log("sweetca: shadow target tex %u written back to surface %u (%zux%zu pitch %zu): GL error %#x", tex,
                 IOSurfaceGetID(k->s), k->w, k->h, k->pitch, e);
   }
   if (prev >= 0)
      glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)prev);
}

static bool
shadow_target(struct sca_ctx *c, IOSurfaceRef s, GLenum target)
{
   size_t w = IOSurfaceGetWidth(s), h = IOSurfaceGetHeight(s), pitch = IOSurfaceGetBytesPerRow(s),
          bpe = IOSurfaceGetBytesPerElement(s);
   struct surf_fmt f;
   if (IOSurfaceGetPlaneCount(s) > 1 || bpe != 4 || !fmt_from_surface(IOSurfaceGetPixelFormat(s), bpe, &f))
      return false;
   GLenum t = tgt(c, target);
   set_swizzle(c, t, f.swz, f.swizzled);
   uint32_t seed = IOSurfaceGetSeed(s);
   if (!copy_surface(c, s, t, &f, w, h, pitch, bpe, false))
      return false;
   GLuint tex = c->held[c->active];
   copy_note(c, tex, s, seed, &f, w, h, pitch, bpe, false);
   if (!tex || tex >= TEXMAX || !c->copies[tex])
      return false;
   c->copies[tex]->target = true;
   int slot = -1;
   for (int i = 0; i < 64; i++) {
      if (c->shadows[i] == tex) {
         slot = i;
         break;
      }
      if (slot < 0 && c->shadows[i] == 0)
         slot = i;
   }
   if (slot < 0) {
      sca_log("sweetca: too many shadow targets, surface %u not written back", IOSurfaceGetID(s));
      return true;
   }
   c->shadows[slot] = tex;
   sca_log("sweetca: attachImage: surface %u %zux%zu pitch %zu: shadow target tex %u", IOSurfaceGetID(s), w, h,
           pitch, tex);
   return true;
}

/* the surface's memory as the storage of the texture bound to target */
static bool
bind_surface(struct sca_ctx *c, IOSurfaceRef s, GLenum target, GLenum format, GLenum type,
             uint32_t plane, bool flip, const char *why)
{
   static int logged;
   uint32_t fourcc = IOSurfaceGetPixelFormat(s);
   bool planar = IOSurfaceGetPlaneCount(s) > 1;
   size_t w = planar ? IOSurfaceGetWidthOfPlane(s, plane) : IOSurfaceGetWidth(s);
   size_t h = planar ? IOSurfaceGetHeightOfPlane(s, plane) : IOSurfaceGetHeight(s);
   size_t pitch = planar ? IOSurfaceGetBytesPerRowOfPlane(s, plane) : IOSurfaceGetBytesPerRow(s);
   size_t bpe = planar ? IOSurfaceGetBytesPerElementOfPlane(s, plane) : IOSurfaceGetBytesPerElement(s);
   char cc[5];
   fourcc_str(fourcc, cc);

   struct surf_fmt f;
   bool ok = !planar && ((format && fmt_from_gl(format, type, &f)) || fmt_from_surface(fourcc, bpe, &f));
   if (!ok) {
      if (logged++ < 40)
         sca_log("sweetca: %s: surface %u '%s' %zux%zu pitch %zu plane %u: no format (gl %#x/%#x)", why,
                 IOSurfaceGetID(s), cc, w, h, pitch, plane, format, type);
      return false;
   }
   GLenum t = tgt(c, target);
   set_swizzle(c, t, f.swz, f.swizzled);
   uint32_t seed = IOSurfaceGetSeed(s);
   bool done = false;
   const char *how = "in place";
   /* client memory may start inside its page (64, 4096... bytes in, round s3-c): the
    * GPU takes it in place there when the start is 64-byte aligned (texture bases
    * need 32, render targets more); our mapping of it begins at the page */
   size_t offset = (uintptr_t)IOSurfaceGetBaseAddress(s) & vm_page_mask;
   if (pitch % 64 == 0 && offset % 64 == 0 && !flip)
      done = sgl_tex_image_iosurface_fmt(c->gl, t, IOSurfaceGetID(s), w, h, pitch, (unsigned)offset, f.f);
   if (!done && format) {
      /* the copy is uploaded as GL_ALPHA / GL_LUMINANCE(_ALPHA) itself: the swizzle
       * above is for R8/RG8 storage in place, and on an ALPHA texture (0,0,0,R)
       * samples as fully transparent (round s3-d: every copied label invisible) */
      how = "copied";
      set_swizzle(c, t, NULL, false);
      done = copy_surface(c, s, t, &f, w, h, pitch, bpe, flip);
   }
   if (!done) {
      if (logged++ < 40)
         sca_log("sweetca: %s: surface %u '%s' %zux%zu pitch %zu: GPU import failed, no copy", why,
                 IOSurfaceGetID(s), cc, w, h, pitch);
      return false;
   }
   if (strcmp(how, "in place") == 0) {
      note_size(c, c->held[c->active], w, h);
      copy_forget(c, c->held[c->active]);
   } else {
      copy_note(c, c->held[c->active], s, seed, &f, w, h, pitch, bpe, flip);
   }
   /* An IOSurface texture has one level. With GL's default MIN_FILTER (a mipmap
    * filter) it is incomplete and samples as (0,0,0,1) unless CA sets a filter,
    * which it does not always do (Apple's are complete as they are; the same cause
    * as step 2's black corners). CA's own TexParameter calls come later and win. */
   GLint minf = 0;
   glGetTexParameteriv(t, GL_TEXTURE_MIN_FILTER, &minf);
   if (minf != GL_NEAREST && minf != GL_LINEAR)
      glTexParameteri(t, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
   if (trace_on && logged++ < 80)
      sca_log("sweetca: %s: surface %u '%s' %zux%zu pitch %zu bound %s (gl %#x/%#x, flip %d)", why,
              IOSurfaceGetID(s), cc, w, h, pitch, how, format, type, flip);
   return true;
}

/* ---- the EAGLContext methods ---- */

static IMP orig_init, orig_init_api, orig_init_share, orig_dealloc, orig_api, orig_set_param,
   orig_macro, orig_tex_iosurface, orig_attach, orig_set_current, orig_current;

static struct sgl_display *dpy;
static pthread_mutex_t dpy_lock = PTHREAD_MUTEX_INITIALIZER;

/* IOKit, declared by hand like the darwin backend does (the SDK has no IOKit headers) */
typedef mach_port_t sca_io_object_t;
extern const mach_port_t kIOMainPortDefault;
CFMutableDictionaryRef IOServiceMatching(const char *name);
sca_io_object_t IOServiceGetMatchingService(mach_port_t main, CFMutableDictionaryRef matching);
kern_return_t IOObjectRelease(sca_io_object_t object);

/*
 * The kernel publishes SweetGPU only once the GPU is up and has passed its
 * self-test, which can be after backboardd asks for its first context (step 3
 * round a: backboardd gave up on the GPU 25 s before it was there). Wait for
 * it, as CA itself waits for an IOAcceleratorES service before trying Metal:
 * at most 90 s (the GPU has taken over 30 s after backboardd started), once per process.
 */
static void
wait_for_gpu(void)
{
   static bool waited;
   if (waited)
      return;
   waited = true;
   for (int i = 0; i < 900; i++) {
      sca_io_object_t s = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("SweetGPU"));
      if (s) {
         IOObjectRelease(s);
         if (i > 0)
            sca_log("sweetca: SweetGPU appeared after %d ms", i * 100);
         return;
      }
      usleep(100000);
   }
   sca_log("sweetca: no SweetGPU service after 90 s");
}

static struct sgl_display *
display(void)
{
   pthread_mutex_lock(&dpy_lock);
   if (!dpy) {
      wait_for_gpu();
      /* before the screen: render straight to memory, no GMEM tiles (their restore and
       * resolve overran unpadded IOSurfaces on the Pixel), and no fp16 lowering of mediump */
      setenv("FD_MESA_DEBUG", "sysmem,nofp16", 0);
      setenv("IR3_SHADER_DEBUG", "nofp16", 0);
      dpy = sgl_display_create();
   }
   pthread_mutex_unlock(&dpy_lock);
   return dpy;
}

#define TABLE_ENTRY(n) (void *)trap_##n,
#define TRAP_FN(n)                                                               \
   static intptr_t trap_##n(void *rctx)                                          \
   {                                                                             \
      (void)rctx;                                                                \
      return trap(n);                                                            \
   }
SCA_FOR_EACH_SLOT(TRAP_FN)

static void
fill_dispatch(void **d)
{
   static void *const traps[SCA_SLOTS] = {SCA_FOR_EACH_SLOT(TABLE_ENTRY)};
   memcpy(d, traps, sizeof(traps));
#define S(i, fn) d[i] = (void *)fn
   S(5, w_BindTexture);
   S(7, w_BlendFunc);
   S(10, w_Clear);
   S(12, w_ClearColor);
   S(56, w_CopyTexSubImage2D);
   S(59, w_DeleteTextures);
   S(63, w_Disable);
   S(65, w_DrawArrays);
   S(67, w_DrawElements);
   S(72, w_Enable);
   S(89, w_Finish);
   S(90, w_Flush);
   S(98, w_GenTextures);
   S(102, w_GetError);
   S(104, w_GetIntegerv);
   S(117, w_GetString);
   S(195, w_PixelStorei);
   S(251, w_Scissor);
   S(301, w_TexImage2D);
   S(302, w_TexParameterf);
   S(304, w_TexParameteri);
   S(307, w_TexSubImage2D);
   S(335, w_Viewport);
   S(338, w_BlendEquation);
   S(342, w_ActiveTexture);
   S(380, w_CompressedTexImage2D);
   S(470, w_FinishObjectAPPLE);
   S(511, w_VertexAttribPointer);
   S(512, w_EnableVertexAttribArray);
   S(513, w_DisableVertexAttribArray);
   S(591, w_DeleteObject);
   S(594, w_CreateShader);
   S(595, w_ShaderSource);
   S(596, w_CompileShader2);
   S(597, w_CreateProgram);
   S(598, w_AttachShader);
   S(599, w_LinkProgram);
   S(600, w_UseProgram);
   S(602, w_Uniform1f);
   S(605, w_Uniform4f);
   S(603, w_Uniform2f);
   S(604, w_Uniform3f);
   S(606, w_Uniform1i);
   S(607, w_Uniform2i);
   S(608, w_Uniform3i);
   S(609, w_Uniform4i);
   S(610, w_Uniform1fv);
   S(611, w_Uniform2fv);
   S(612, w_Uniform3fv);
   S(613, w_Uniform4fv);
   S(614, w_Uniform1iv);
   S(615, w_Uniform2iv);
   S(616, w_Uniform3iv);
   S(617, w_Uniform4iv);
   S(618, w_UniformMatrix2fv);
   S(619, w_UniformMatrix3fv);
   S(620, w_UniformMatrix4fv);
   S(625, w_GetUniformLocation);
   S(630, w_BindAttribLocation);
   S(672, w_BindFramebuffer);
   S(673, w_DeleteFramebuffers);
   S(674, w_GenFramebuffers);
   S(677, w_FramebufferTexture2D);
   S(681, w_GenerateMipmap);
   S(779, w_FenceSync);
   S(781, w_DeleteSync);
   S(782, w_ClientWaitSync);
   S(814, w_Nop);
   S(816, w_Nop);
   S(817, w_Nop);
   S(818, w_Nop);
   S(1024, w_FramebufferParameteriAPPLE);
#undef S
}

/* a context for self, or NULL (the caller then uses Apple's init) */
static struct sca_ctx *
make_ctx(id self, NSUInteger api)
{
   struct sgl_display *d = api >= 2 && api <= 3 ? display() : NULL;
   struct sgl_context *gl = d ? sgl_context_create(d, (int)api, NULL) : NULL;
   struct sca_ctx *c = gl ? calloc(1, sizeof(*c)) : NULL;
   if (!c) {
      if (gl)
         sgl_context_destroy(gl);
      return NULL;
   }
   c->rctx = c;
   fill_dispatch(c->disp);
   c->eagl = self;
   c->api = (unsigned)api;
   c->gl = gl;
   c->fbfetch_unit = UNITS - 1;
   for (int i = 0; i < OBJMAX; i++)
      c->obj[i].rect_sampler_loc = c->obj[i].rect_scale_loc = c->obj[i].fb_sampler_loc =
         c->obj[i].fb_scale_loc = -1;
   int slot = -1;
   pthread_mutex_lock(&ctx_lock);
   for (int i = 0; i < MAX_CTX && slot < 0; i++) {
      if (!ctxs[i]) {
         ctxs[i] = c;
         slot = i;
      }
   }
   pthread_mutex_unlock(&ctx_lock);
   if (slot < 0) {
      sgl_context_destroy(gl);
      free(c);
      return NULL;
   }
   /* the unit for framebuffer fetch: the last one the GPU has */
   bind_ctx(c);
   GLint units = 16;
   glGetIntegerv(GL_MAX_TEXTURE_IMAGE_UNITS, &units);
   c->fbfetch_unit = units - 1 < UNITS ? units - 1 : UNITS - 1;
   /* The render target's texture is sampled with a sampler of our own: CA (and
    * EAGL's callers) never set its filters, and the default MIN_FILTER
    * NEAREST_MIPMAP_LINEAR on a texture with one level makes it incomplete, which
    * samples as (0,0,0,1). That was the black band at rounded corners (round s).
    * ES 2 has no sampler objects: draw_prep sets the texture's own filter there. */
   if (api >= 3) {
      glGenSamplers(1, &c->fb_sampler);
      glSamplerParameteri(c->fb_sampler, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
      glSamplerParameteri(c->fb_sampler, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
      glSamplerParameteri(c->fb_sampler, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
      glSamplerParameteri(c->fb_sampler, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
      glBindSampler(c->fbfetch_unit, c->fb_sampler);
   }
   sca_log("sweetca: EAGLContext %p API %lu on Mesa: %s, %s (GLI %p)", self, (unsigned long)api,
           glGetString(GL_VERSION), glGetString(GL_RENDERER), c);
   bind_ctx(NULL);
   return c;
}

static id
m_init(id self, SEL cmd, NSUInteger api, id props)
{
   if (make_ctx(self, api))
      return self;
   sca_log("sweetca: EAGLContext API %lu: no Mesa context, Apple's EAGL instead", (unsigned long)api);
   return ((id (*)(id, SEL, NSUInteger, id))orig_init)(self, cmd, api, props);
}

static id
m_init_api(id self, SEL cmd, NSUInteger api)
{
   if (make_ctx(self, api))
      return self;
   return ((id (*)(id, SEL, NSUInteger))orig_init_api)(self, cmd, api);
}

static id
m_init_share(id self, SEL cmd, NSUInteger api, id share)
{
   if (make_ctx(self, api))
      return self;
   return ((id (*)(id, SEL, NSUInteger, id))orig_init_share)(self, cmd, api, share);
}

static void
m_dealloc(id self, SEL cmd)
{
   struct sca_ctx *c = lookup(self);
   if (!c) {
      ((void (*)(id, SEL))orig_dealloc)(self, cmd);
      return;
   }
   pthread_mutex_lock(&ctx_lock);
   for (int i = 0; i < MAX_CTX; i++) {
      if (ctxs[i] == c)
         ctxs[i] = NULL;
   }
   pthread_mutex_unlock(&ctx_lock);
   if (cur == c)
      bind_ctx(NULL);
   sgl_context_destroy(c->gl);
   free(c);
   /* EAGLContext's own init never ran: skip its dealloc, run NSObject's */
   struct objc_super sup = {self, class_getSuperclass(objc_getClass("EAGLContext"))};
   ((void (*)(struct objc_super *, SEL))objc_msgSendSuper)(&sup, cmd);
}

static NSUInteger
m_api(id self, SEL cmd)
{
   struct sca_ctx *c = lookup(self);
   return c ? c->api : ((NSUInteger(*)(id, SEL))orig_api)(self, cmd);
}

static BOOL
m_set_param(id self, SEL cmd, uint32_t pname, const int32_t *value)
{
   if (!lookup(self))
      return ((BOOL(*)(id, SEL, uint32_t, const int32_t *))orig_set_param)(self, cmd, pname, value);
   sca_log("sweetca: setParameter %#x to %d (ignored)", pname, value ? *value : 0);
   return YES;
}

static void *
m_macro(id self, SEL cmd)
{
   struct sca_ctx *c = lookup(self);
   return c ? (void *)c : ((void *(*)(id, SEL))orig_macro)(self, cmd);
}

static BOOL
m_tex_iosurface(id self, SEL cmd, IOSurfaceRef s, NSUInteger target, NSUInteger internalformat,
                uint32_t width, uint32_t height, NSUInteger format, NSUInteger type, uint32_t plane,
                BOOL invert)
{
   struct sca_ctx *c = lookup(self);
   if (!c) {
      return ((BOOL(*)(id, SEL, IOSurfaceRef, NSUInteger, NSUInteger, uint32_t, uint32_t, NSUInteger,
                       NSUInteger, uint32_t, BOOL))orig_tex_iosurface)(self, cmd, s, target,
                                                                       internalformat, width, height,
                                                                       format, type, plane, invert);
   }
   if (cur != c)
      bind_ctx(c);
   /* invert:YES asks for the rows turned over; NO is the surface as it is (step 3: flipping
    * on NO, as step 2's test suggested, put every icon in backboardd upside down) */
   return bind_surface(c, s, (GLenum)target, (GLenum)format, (GLenum)type, plane, invert, "texImageIOSurface");
}

static BOOL
m_attach(id self, SEL cmd, NSUInteger target, IOSurfaceRef s, BOOL inverted)
{
   struct sca_ctx *c = lookup(self);
   if (!c)
      return ((BOOL(*)(id, SEL, NSUInteger, IOSurfaceRef, BOOL))orig_attach)(self, cmd, target, s, inverted);
   if (cur != c)
      bind_ctx(c);
   static int told;
   if (told++ < 4)
      sca_log("sweetca: attachImage surface %u invertedRender %d", IOSurfaceGetID(s), inverted);
   return bind_surface(c, s, (GLenum)target, 0, 0, 0, false, "attachImage") ||
          shadow_target(c, s, (GLenum)target);
}

static BOOL
m_set_current(id cls, SEL cmd, id eagl)
{
   struct sca_ctx *c = lookup(eagl);
   if (c) {
      bind_ctx(c);
      cur_eagl = eagl;
      return YES;
   }
   if (cur)
      bind_ctx(NULL);
   cur_eagl = nil;
   return ((BOOL(*)(id, SEL, id))orig_set_current)(cls, cmd, eagl);
}

static id
m_current(id cls, SEL cmd)
{
   return cur_eagl ? cur_eagl : ((id(*)(id, SEL))orig_current)(cls, cmd);
}

static IMP
swap(Class cls, const char *sel, void *imp)
{
   Method m = class_getInstanceMethod(cls, sel_registerName(sel));
   if (!m) {
      sca_log("sweetca: EAGLContext has no %s", sel);
      return NULL;
   }
   return method_setImplementation(m, (IMP)imp);
}

/*
 * QuartzCore (iOS 16.7.16 20H392, iPhone X shared cache; the iPhone 8 cache has the
 * same code 0x4000 lower): CA::OGL::GLContext's tex_fragment_shaders, one GLSL
 * expression per texture function (entry 0x13 is "colorMatrix4x4Bias(s0)", the
 * ones without a GL expression are NULL), and the byte table of create_shader's
 * switch over the function (index function - 0x11) that picks which uniforms a
 * shader declares and looks up: 0 is color_matrix[5], 0x95 the blur's minmax_dir
 * and friends, 0xde none. Nothing is written unless all of it is as expected.
 */
#define QC_TEXFN_TABLE 0x1d5b48a10ull
#define QC_TEXFN_CASES 0x18855e1e4ull /* entry of function 0x11 */
#define QC_CACHE_BASE 0x180000000ull

extern const void *_dyld_get_shared_cache_range(size_t *length);

static const struct {
   uint8_t fn;
   const char *expr;
   uint8_t uniforms;
} texfns[] = {
   {0x2d, "sca_vcm(s0)", 0},
   {0x14, "sca_cm4(s0)", 0},
   {0x26, "sca_nop()", 0xde},
   {0x27, "sca_vblur(s1)", 0x95},
};

static bool
write_const(void *at, const void *val, size_t len, vm_prot_t back)
{
   vm_address_t page = (vm_address_t)at & ~(vm_address_t)vm_page_mask;
   if (vm_protect(mach_task_self(), page, vm_page_size * 2, FALSE,
                  VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY) != KERN_SUCCESS)
      return false;
   memcpy(at, val, len);
   vm_protect(mach_task_self(), page, vm_page_size * 2, FALSE, back);
   return true;
}

static void
install_texfns(void)
{
   size_t len = 0;
   const uint8_t *cache = _dyld_get_shared_cache_range(&len);
   if (!cache) {
      sca_log("sweetca: texture functions: no shared cache range");
      return;
   }
   uint64_t slide = (uint64_t)(uintptr_t)cache - QC_CACHE_BASE;
   const char **table = (const char **)(uintptr_t)(QC_TEXFN_TABLE + slide);
   const uint8_t *cases = (const uint8_t *)(uintptr_t)(QC_TEXFN_CASES - 0x11 + slide);
   if (!table[0x13] || strcmp(table[0x13], "colorMatrix4x4Bias(s0)") != 0 || cases[0x13] != 0 ||
       cases[0x2b] != 0x95) {
      sca_log("sweetca: texture functions: unexpected QuartzCore, not patched");
      return;
   }
   for (size_t i = 0; i < sizeof(texfns) / sizeof(texfns[0]); i++) {
      uint8_t fn = texfns[i].fn;
      if (table[fn] || cases[fn] != 0xde) {
         sca_log("sweetca: texture function %#x: unexpected (%p, case %#x), not patched", fn,
                 (void *)table[fn], cases[fn]);
         return;
      }
   }
   for (size_t i = 0; i < sizeof(texfns) / sizeof(texfns[0]); i++) {
      uint8_t fn = texfns[i].fn, u = texfns[i].uniforms;
      bool ok = write_const((void *)&table[fn], &texfns[i].expr, sizeof(char *), VM_PROT_READ) &&
                (u == 0xde || write_const((void *)&cases[fn], &u, 1, VM_PROT_READ | VM_PROT_EXECUTE));
      sca_log("sweetca: texture function %#x = %s: %s", fn, texfns[i].expr, ok ? "installed" : "FAILED");
   }
}

/* nonzero once the EAGL methods are replaced; the test calls it to make sure the library is linked in */
int sweetca_installed(void);
void sweetca_set_trace(int level);

__attribute__((visibility("default"))) void
sweetca_set_trace(int level)
{
   trace_on = level;
}

__attribute__((visibility("default"))) int
sweetca_installed(void)
{
   return orig_init != NULL;
}

__attribute__((constructor)) static void
sweetca_init(void)
{
   const char *t = getenv("SWEETCA_TRACE");
   const char *b = getenv("SWEETCA_ACTIVE_BARRIERS");
   active_barriers = !b || strcmp(b, "0") != 0;
   sca_log("sweetca: active sampler barriers %s", active_barriers ? "enabled" : "legacy");
   trace_on = t && t[0] == '1' ? 1 : t && t[0] == '2' ? 2 : 0;
   const char *k = getenv("SWEETCA_KICK");
   if (k)
      kick_every = (unsigned)strtoul(k, NULL, 10);
   if (!getenv("SWEETCA_NO_TEXFNS"))
      install_texfns();
   Class cls = objc_getClass("EAGLContext");
   if (cls == Nil) {
      sca_log("sweetca: no EAGLContext class");
      return;
   }
   Class meta = object_getClass((id)cls);
   orig_init = swap(cls, "initWithAPI:properties:", m_init);
   orig_init_api = swap(cls, "initWithAPI:", m_init_api);
   orig_init_share = swap(cls, "initWithAPI:sharegroup:", m_init_share);
   orig_dealloc = swap(cls, "dealloc", m_dealloc);
   orig_api = swap(cls, "API", m_api);
   orig_set_param = swap(cls, "setParameter:to:", m_set_param);
   orig_macro = swap(cls, "getMacroContextPrivate", m_macro);
   orig_tex_iosurface =
      swap(cls, "texImageIOSurface:target:internalFormat:width:height:format:type:plane:invert:",
           m_tex_iosurface);
   orig_attach = swap(cls, "attachImage:toCoreSurface:invertedRender:", m_attach);
   orig_set_current = swap(meta, "setCurrentContext:", m_set_current);
   orig_current = swap(meta, "currentContext", m_current);
   sca_log("sweetca: EAGL methods replaced%s", trace_on ? " (GL error checks on)" : "");
}
