/* SPDX-License-Identifier: MIT
 * Task 23: opt-in GL snapshots, no rendering substitutions or glGetError.
 * SWEETCA_PASS_TRACE=1; _DELAY=180 seconds, _SECONDS=12, _DRAWS=1200.
 */
struct sca_pass_trace {
   uint32_t surface[TEXMAX], generation[TEXMAX];
   uint8_t program_seen[OBJMAX];
};
static bool pass_trace_enabled, pass_trace_started, pass_trace_ended;
static double pass_trace_epoch, pass_trace_delay, pass_trace_seconds;
static unsigned pass_trace_limit, pass_trace_draws, pass_trace_events;
static pthread_mutex_t pass_trace_lock = PTHREAD_MUTEX_INITIALIZER;

static double
pass_trace_time(void)
{
   struct timespec t;
   clock_gettime(CLOCK_MONOTONIC, &t);
   return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}

static unsigned
pass_trace_number(const char *key, unsigned fallback, unsigned maximum)
{
   const char *v = getenv(key);
   if (!v || !*v)
      return fallback;
   char *end;
   errno = 0;
   unsigned long n = strtoul(v, &end, 10);
   return errno || *end || v[0] == '-' || n > maximum ? fallback : (unsigned)n;
}

static void
pass_trace_init(void)
{
   const char *v = getenv("SWEETCA_PASS_TRACE");
   pass_trace_enabled = v && strcmp(v, "1") == 0;
   if (!pass_trace_enabled)
      return;
   pass_trace_delay = pass_trace_number("SWEETCA_PASS_TRACE_DELAY", 180, 3600);
   pass_trace_seconds = pass_trace_number("SWEETCA_PASS_TRACE_SECONDS", 12, 30);
   pass_trace_limit = pass_trace_number("SWEETCA_PASS_TRACE_DRAWS", 1200, 3000);
   pass_trace_epoch = pass_trace_time();
   sca_log("sweetca: passgraph armed delay=%.0f seconds=%.0f draws=%u; diagnostic timings invalid",
           pass_trace_delay, pass_trace_seconds, pass_trace_limit);
}

/* IDs are provenance hints, not retained ownership. Updates describe attempted
 * storage changes; dimensions/levels in draw records are queried from GL.
 * surface=0 means private/copied/unknown storage, never proof of an import.
 */
static void
pass_trace_storage(struct sca_ctx *c, GLuint tex, uint32_t surface, bool replace)
{
   if (!pass_trace_enabled || !tex || tex >= TEXMAX)
      return;
   if (!c->pass_trace)
      c->pass_trace = calloc(1, sizeof(*c->pass_trace));
   if (c->pass_trace && replace) {
      c->pass_trace->surface[tex] = surface;
      c->pass_trace->generation[tex]++;
   }
}

static void
pass_trace_event(struct sca_ctx *c, const char *fmt, ...)
{
   if (!pass_trace_enabled)
      return;
   pthread_mutex_lock(&pass_trace_lock);
   double age = pass_trace_time() - pass_trace_epoch;
   if (!pass_trace_ended && age >= pass_trace_delay &&
       age < pass_trace_delay + pass_trace_seconds && pass_trace_events < 8000) {
      char line[500];
      va_list ap;
      va_start(ap, fmt);
      vsnprintf(line, sizeof(line), fmt, ap);
      va_end(ap);
      sca_log("sweetca: passgraph event ctx=%p after=%u age=%.3f %s", (void *)c,
              pass_trace_draws, age, line);
      if (++pass_trace_events == 8000)
         sca_log("sweetca: passgraph event-limit; graph incomplete");
   }
   pthread_mutex_unlock(&pass_trace_lock);
}

static void
pass_trace_program(struct sca_ctx *c, unsigned seq)
{
   GLuint p = c->program;
   if (!c->pass_trace || !p || p >= OBJMAX || c->pass_trace->program_seen[p])
      return;
   c->pass_trace->program_seen[p] = 1;
   GLuint shaders[8];
   GLsizei n = 0;
   glGetAttachedShaders(p, 8, &n, shaders);
   for (GLsizei i = 0; i < n; i++) {
      GLint type = 0;
      glGetShaderiv(shaders[i], GL_SHADER_TYPE, &type);
      if (type != GL_FRAGMENT_SHADER)
         continue;
      char src[8192] = {0};
      GLsizei len = 0;
      glGetShaderSource(shaders[i], sizeof(src), &len, src);
      const char *kind = strstr(src, "sca_vblur(") ? "variable-source-disc" :
                         strstr(src, "sca_nop(") ? "variable-discard" :
                         strstr(src, "weight") ? "weighted-candidate" : "other";
      sca_log("sweetca: passgraph shader ctx=%p seq=%u program=%u shader=%u kind=%s bytes=%d truncated=%d",
              (void *)c, seq, p, shaders[i], kind, len, len == (GLsizei)sizeof(src) - 1);
      for (GLsizei j = 0; j < len; j += 600)
         sca_log("sweetca: passgraph source ctx=%p shader=%u offset=%d | %.600s",
                 (void *)c, shaders[i], j, src + j);
   }
}

static void
pass_trace_draw(struct sca_ctx *c, GLenum mode, GLsizei count)
{
   if (!pass_trace_enabled || c->api < 3)
      return;
   pthread_mutex_lock(&pass_trace_lock);
   double age = pass_trace_time() - pass_trace_epoch;
   if (age < pass_trace_delay || pass_trace_ended) {
      pthread_mutex_unlock(&pass_trace_lock);
      return;
   }
   if (age >= pass_trace_delay + pass_trace_seconds || pass_trace_draws >= pass_trace_limit) {
      pass_trace_ended = true;
      sca_log("sweetca: passgraph end age=%.3f draws=%u reason=%s", age, pass_trace_draws,
              pass_trace_draws >= pass_trace_limit ? "draw-limit" : "time-limit");
      pthread_mutex_unlock(&pass_trace_lock);
      return;
   }
   if (!pass_trace_started) {
      pass_trace_started = true;
      sca_log("sweetca: passgraph begin age=%.3f", age);
   }
   unsigned seq = ++pass_trace_draws;
   GLint vp[4], sc[4], fb = 0, tex = 0, level = -1, type = 0;
   glGetIntegerv(GL_VIEWPORT, vp);
   glGetIntegerv(GL_SCISSOR_BOX, sc);
   glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &fb);
   if (fb) {
      glGetFramebufferAttachmentParameteriv(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                            GL_FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE, &type);
      if (type == GL_TEXTURE) {
         glGetFramebufferAttachmentParameteriv(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                               GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME, &tex);
         glGetFramebufferAttachmentParameteriv(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                               GL_FRAMEBUFFER_ATTACHMENT_TEXTURE_LEVEL, &level);
      }
   }
   sca_log("sweetca: passgraph draw ctx=%p seq=%u age=%.3f frame=%u program=%u mode=%#x count=%d fbo=%d status=%#x target=%d level=%d size=%ux%u vp=%d,%d,%d,%d sc=%d:%d,%d,%d,%d blend=%d",
           (void *)c, seq, age, c->frame, c->program, mode, count, fb,
           glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER), tex, level,
           tex > 0 && tex < TEXMAX ? c->tex_w[tex] : 0,
           tex > 0 && tex < TEXMAX ? c->tex_h[tex] : 0,
           vp[0], vp[1], vp[2], vp[3], glIsEnabled(GL_SCISSOR_TEST),
           sc[0], sc[1], sc[2], sc[3], glIsEnabled(GL_BLEND));
   pass_trace_program(c, seq);
   GLint active = 0, units = 0;
   glGetIntegerv(GL_ACTIVE_TEXTURE, &active);
   glGetIntegerv(GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS, &units);
   for (int u = 0; u < UNITS && u < units; u++) {
      if (!c->held[u])
         continue;
      glActiveTexture(GL_TEXTURE0 + u);
      GLint bound = 0, base = 0, max = 0, min = 0, w[4], h[4];
      glGetIntegerv(GL_TEXTURE_BINDING_2D, &bound);
      if (!bound)
         continue;
      glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_BASE_LEVEL, &base);
      glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL, &max);
      glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, &min);
      for (int l = 0; l < 4; l++) {
         glGetTexLevelParameteriv(GL_TEXTURE_2D, l, GL_TEXTURE_WIDTH, &w[l]);
         glGetTexLevelParameteriv(GL_TEXTURE_2D, l, GL_TEXTURE_HEIGHT, &h[l]);
      }
      unsigned surface = c->pass_trace && bound < TEXMAX ? c->pass_trace->surface[bound] : 0;
      unsigned generation = c->pass_trace && bound < TEXMAX ? c->pass_trace->generation[bound] : 0;
      sca_log("sweetca: passgraph texture ctx=%p seq=%u unit=%d texture=%d expected=%u surface=%u generation=%u base=%d max=%d min=%#x levels=%dx%d,%dx%d,%dx%d,%dx%d",
              (void *)c, seq, u, bound, c->held[u], surface, generation, base, max, min,
              w[0], h[0], w[1], h[1], w[2], h[2], w[3], h[3]);
   }
   glActiveTexture((GLenum)active);
   pthread_mutex_unlock(&pass_trace_lock);
}
