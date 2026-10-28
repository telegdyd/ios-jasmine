/* SPDX-License-Identifier: MIT
 * Task 24 stage 3: GMEM pixel and memory-safety checks on CoreAnimation-like
 * targets. Included after the IOSurface helpers and the feedback test.
 *
 * Each target (imported BGRA IOSurfaces of odd sizes, one with extra row
 * padding, and one GL allocation) runs three sequences, three times each, so
 * that the cost rule (SWEETCA_GMEM=1) has measured history from the second
 * round on:
 *
 *   A cleared batch: clear, 3 additive full-screen draws, an opaque rectangle;
 *   B restored batch (no clear): 4 additive full-screen draws, a rectangle;
 *   C cleared GMEM prefix followed by feedback: clear, 3 additive draws, a
 *     rectangle, then 2 barrier+self-sampling draws (with SWEETCA_SYS_BARRIER
 *     the prefix is split off and the feedback batch reads its resolve).
 *
 * All blending is additive (exact in 8 bits). A CPU model of the image gives
 * the expected pixels. For imported targets the surface memory is checked
 * directly (IOSurfaceLock), every pixel, and every byte the GPU must not
 * write is a canary filled before the first draw: row padding beyond the
 * width rounded to 16 pixels (must stay intact: FAIL otherwise), row padding
 * inside that rounding and the allocation's tail after the last row
 * (reported: they show whether a resolve writes past its window).
 */
extern const CFStringRef kIOSurfaceBytesPerRow;
size_t IOSurfaceGetAllocSize(IOSurfaceRef surface);

#define GM_CANARY 0xa5
#define GM_MIN(a, b) ((a) < (b) ? (a) : (b))
#define GM_ALIGN(v, a) (((v) + (a) - 1) / (a) * (a))

struct gm_target {
   unsigned w, h, pitch;
   IOSurfaceRef surface;             /* NULL: GL allocation */
   uint8_t *model;                   /* RGBA, row 0 = GL row 0 (bottom) */
   uint8_t *read;                    /* scratch for glReadPixels */
};

/* equal within 1 per channel (the feedback test's tolerance) */
static bool
gm_same(const uint8_t a[4], const uint8_t b[4])
{
   for (unsigned i = 0; i < 4; i++)
      if (abs((int)a[i] - (int)b[i]) > 1)
         return false;
   return true;
}

static void
gm_model_fill(struct gm_target *t, unsigned x0, unsigned y0, unsigned x1, unsigned y1,
              const uint8_t c[4], bool add)
{
   for (unsigned y = y0; y < y1; y++) {
      uint8_t *p = t->model + 4 * ((size_t)y * t->w + x0);
      for (unsigned x = x0; x < x1; x++, p += 4)
         for (unsigned i = 0; i < 4; i++)
            p[i] = add ? (uint8_t)GM_MIN(255, p[i] + c[i]) : c[i];
   }
}

static void
gm_draw(GLuint prog, const uint8_t c[4])
{
   glUseProgram(prog);
   glUniform4f(glGetUniformLocation(prog, "color"), c[0] / 255.0f, c[1] / 255.0f, c[2] / 255.0f,
               c[3] / 255.0f);
   glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
}

/* additive full-screen draws */
static void
gm_add(struct gm_target *t, GLuint solid, unsigned n, const uint8_t c[4])
{
   glDisable(GL_SCISSOR_TEST);
   glEnable(GL_BLEND);
   glBlendFunc(GL_ONE, GL_ONE);
   for (unsigned i = 0; i < n; i++) {
      gm_draw(solid, c);
      gm_model_fill(t, 0, 0, t->w, t->h, c, true);
   }
   glDisable(GL_BLEND);
}

/* opaque rectangle through the scissor (odd position and size) */
static void
gm_rect(struct gm_target *t, GLuint solid, unsigned x, unsigned y, unsigned w, unsigned h,
        const uint8_t c[4])
{
   x = GM_MIN(x, t->w - 1);
   y = GM_MIN(y, t->h - 1);
   w = GM_MIN(w, t->w - x);
   h = GM_MIN(h, t->h - y);
   glEnable(GL_SCISSOR_TEST);
   glScissor(x, y, w, h);
   gm_draw(solid, c);
   glDisable(GL_SCISSOR_TEST);
   gm_model_fill(t, x, y, x + w, y + h, c, false);
}

static void
gm_clear(struct gm_target *t, const uint8_t c[4])
{
   glDisable(GL_SCISSOR_TEST);
   glClearColor(c[0] / 255.0f, c[1] / 255.0f, c[2] / 255.0f, c[3] / 255.0f);
   glClear(GL_COLOR_BUFFER_BIT);
   gm_model_fill(t, 0, 0, t->w, t->h, c, false);
}

/* every pixel against the model; for imported targets also the canaries */
static void gm_map(struct gm_target *t, const char *what);

static bool
gm_check(struct gm_target *t, const char *what)
{
   glFinish();
   unsigned bad = 0, info_pad = 0, info_tail = 0, bad_pad = 0;
   size_t first_bad = 0;
   uint8_t got[4] = {0}, want[4] = {0};
   if (t->surface) {
      IOSurfaceLock(t->surface, kIOSurfaceLockReadOnly, NULL);
      const uint8_t *base = IOSurfaceGetBaseAddress(t->surface);
      size_t alloc = IOSurfaceGetAllocSize(t->surface);
      unsigned w16 = GM_ALIGN(t->w, 16);
      for (unsigned y = 0; y < t->h; y++) {
         const uint8_t *row = base + (size_t)t->pitch * y;   /* texture row y = memory row y */
         const uint8_t *m = t->model + 4 * (size_t)y * t->w;
         for (unsigned x = 0; x < t->w; x++) {
            const uint8_t *p = row + 4 * x;
            const uint8_t c[4] = {p[2], p[1], p[0], p[3]};
            if (!gm_same(c, m + 4 * x)) {
               if (!bad++) {
                  first_bad = (size_t)y * t->w + x;
                  memcpy(got, c, 4);
                  memcpy(want, m + 4 * x, 4);
               }
            }
         }
         for (unsigned b = 4 * t->w; b < t->pitch; b++) {
            if (row[b] == GM_CANARY)
               continue;
            if (b >= 4 * w16)
               bad_pad++;
            else
               info_pad++;
         }
      }
      if (bad) {
         unsigned flipped = 0;
         for (unsigned y = 0; y < t->h; y++) {
            const uint8_t *row = base + (size_t)t->pitch * (t->h - 1 - y);
            for (unsigned x = 0; x < t->w; x++) {
               const uint8_t c[4] = {row[4 * x + 2], row[4 * x + 1], row[4 * x], row[4 * x + 3]};
               flipped += !gm_same(c, t->model + 4 * ((size_t)y * t->w + x));
            }
         }
         printf("%s: diagnostic: %u pixels wrong if rows were flipped\n", what, flipped);
      }
      for (size_t b = (size_t)t->pitch * t->h; b < alloc; b++)
         info_tail += base[b] != GM_CANARY;
      if (bad)
         gm_map(t, what);
      IOSurfaceUnlock(t->surface, kIOSurfaceLockReadOnly, NULL);
   } else {
      glReadPixels(0, 0, t->w, t->h, GL_RGBA, GL_UNSIGNED_BYTE, t->read);
      for (size_t i = 0; i < (size_t)t->w * t->h; i++) {
         if (!gm_same(t->read + 4 * i, t->model + 4 * i) && !bad++) {
            first_bad = i;
            memcpy(got, t->read + 4 * i, 4);
            memcpy(want, t->model + 4 * i, 4);
         }
      }
   }
   if (bad && !t->surface)
      gm_map(t, what);
   GLenum e = glGetError();
   bool ok = !bad && !bad_pad && e == GL_NO_ERROR;
   printf("%s: %ux%u pitch %u: %u pixels wrong", what, t->w, t->h, t->pitch, bad);
   if (bad)
      printf(" (first (%zu,%zu) %02x%02x%02x%02x, expected %02x%02x%02x%02x)", first_bad % t->w,
             first_bad / t->w, got[0], got[1], got[2], got[3], want[0], want[1], want[2], want[3]);
   if (t->surface)
      printf("; row padding past 16-px rounding %u bytes changed (must be 0), inside it %u, "
             "tail after last row %u", bad_pad, info_pad, info_tail);
   if (e != GL_NO_ERROR)
      printf("; GL error %#x", e);
   printf("\n%s %s\n", ok ? "PASS:" : "FAIL:", what);
   return ok;
}

/* on failure: which 128x128 blocks hold wrong pixels ('#'), top row of the image first */
static void
gm_map(struct gm_target *t, const char *what)
{
   unsigned bw = (t->w + 127) / 128, bh = (t->h + 127) / 128;
   printf("%s: wrong-pixel map, %ux%u blocks of 128x128, GL row 0 at the bottom:\n", what, bw, bh);
   for (unsigned by = bh; by-- > 0;) {
      char line[64] = "";
      for (unsigned bx = 0; bx < bw && bx < 63; bx++) {
         unsigned bad = 0;
         for (unsigned y = by * 128; y < GM_MIN(t->h, by * 128 + 128); y++)
            for (unsigned x = bx * 128; x < GM_MIN(t->w, bx * 128 + 128); x++) {
               const uint8_t *m = t->model + 4 * ((size_t)y * t->w + x);
               uint8_t c[4];
               if (t->surface) {
                  const uint8_t *p = (const uint8_t *)IOSurfaceGetBaseAddress(t->surface) +
                                     (size_t)t->pitch * y + 4 * x;
                  c[0] = p[2], c[1] = p[1], c[2] = p[0], c[3] = p[3];
               } else {
                  memcpy(c, t->read + 4 * ((size_t)y * t->w + x), 4);
               }
               bad += !gm_same(c, m);
            }
         line[bx] = bad ? '#' : '.';
         line[bx + 1] = 0;
      }
      printf("  %s\n", line);
   }
}

static bool
gm_run(struct gm_target *t, GLuint solid, GLuint sample, GLuint tex, const char *kind)
{
   static const uint8_t c0[4] = {10, 20, 30, 255}, add[4] = {5, 3, 1, 0};
   static const uint8_t r0[4] = {1, 2, 3, 255}, r1[4] = {200, 7, 90, 255};
   static const uint8_t c1[4] = {40, 24, 8, 255}, fb[4] = {4, 2, 1, 0};
   char name[160];
   bool ok = true;
   glViewport(0, 0, t->w, t->h);
   for (unsigned round = 1; round <= 3; round++) {
      gm_clear(t, c0);
      gm_add(t, solid, 3, add);
      gm_rect(t, solid, t->w / 3 + 1, t->h / 4 + 3, t->w / 2 + 5, t->h / 3 + 7, r0);
      snprintf(name, sizeof(name), "gmem %s cleared batch round %u", kind, round);
      ok &= gm_check(t, name);

      gm_add(t, solid, 4, add);
      gm_rect(t, solid, 7, t->h / 2 + 1, t->w / 4 + 3, t->h / 5 + 1, r1);
      snprintf(name, sizeof(name), "gmem %s restored batch round %u", kind, round);
      ok &= gm_check(t, name);

      gm_clear(t, c1);
      gm_add(t, solid, 3, add);
      gm_rect(t, solid, t->w / 5, t->h / 3, t->w / 3, t->h / 4, r0);
      glUseProgram(sample);
      glBindTexture(GL_TEXTURE_2D, tex);
      glUniform1i(glGetUniformLocation(sample, "tex"), 0);
      glUniform2f(glGetUniformLocation(sample, "size"), (float)t->w, (float)t->h);
      for (unsigned i = 0; i < 2; i++) {
         sgl_texture_barrier();
         glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
         gm_model_fill(t, 0, 0, t->w, t->h, fb, true);
      }
      snprintf(name, sizeof(name), "gmem %s prefix then feedback round %u", kind, round);
      ok &= gm_check(t, name);
   }
   return ok;
}

/* an imported BGRA IOSurface (extra: bytes per row beyond 64-byte rounding) or a GL allocation */
static bool
gm_target(struct sgl_context *ctx, unsigned w, unsigned h, int extra, GLuint solid, GLuint sample)
{
   struct gm_target t = {.w = w, .h = h};
   char kind[64];
   bool ok = true;
   t.model = malloc((size_t)w * h * 4);
   if (!t.model)
      return false;
   GLuint tex, fbo;
   glGenTextures(1, &tex);
   glGenFramebuffers(1, &fbo);
   glBindTexture(GL_TEXTURE_2D, tex);
   if (extra >= 0) {
      CFMutableDictionaryRef props = CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks,
                                                               &kCFTypeDictionaryValueCallBacks);
      dict_set_u32(props, kIOSurfaceWidth, w);
      dict_set_u32(props, kIOSurfaceHeight, h);
      dict_set_u32(props, kIOSurfaceBytesPerElement, 4);
      dict_set_u32(props, kIOSurfacePixelFormat, SGL_IOSURFACE_BGRA);
      if (extra > 0)
         dict_set_u32(props, kIOSurfaceBytesPerRow, GM_ALIGN(w * 4, 64) + extra);
      t.surface = IOSurfaceCreate(props);
      CFRelease(props);
      if (!t.surface) {
         printf("FAIL: gmem IOSurfaceCreate %ux%u\n", w, h);
         free(t.model);
         return false;
      }
      t.pitch = IOSurfaceGetBytesPerRow(t.surface);
      size_t alloc = IOSurfaceGetAllocSize(t.surface);
      IOSurfaceLock(t.surface, 0, NULL);
      memset(IOSurfaceGetBaseAddress(t.surface), GM_CANARY, alloc);
      IOSurfaceUnlock(t.surface, 0, NULL);
      snprintf(kind, sizeof(kind), "imported %ux%u%s", w, h, extra > 0 ? " padded rows" : "");
      printf("gmem target %s: IOSurface %u, %u bytes per row, alloc %zu (rows to 32: %zu)\n", kind,
             IOSurfaceGetID(t.surface), t.pitch, alloc, (size_t)t.pitch * GM_ALIGN(h, 32));
      ok &= sgl_tex_image_iosurface(ctx, GL_TEXTURE_2D, IOSurfaceGetID(t.surface), w, h, t.pitch,
                                    SGL_IOSURFACE_BGRA);
   } else {
      t.pitch = w * 4;
      t.read = malloc((size_t)w * h * 4);
      glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
      snprintf(kind, sizeof(kind), "GL allocation %ux%u", w, h);
   }
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
   glBindFramebuffer(GL_FRAMEBUFFER, fbo);
   glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
   if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
      printf("FAIL: gmem %s framebuffer incomplete\n", kind);
      ok = false;
   } else if (extra < 0 && !t.read) {
      ok = false;
   } else {
      ok &= gm_run(&t, solid, sample, tex, kind);
   }
   glBindFramebuffer(GL_FRAMEBUFFER, 0);
   glDeleteFramebuffers(1, &fbo);
   glDeleteTextures(1, &tex);
   glFinish();
   if (t.surface)
      CFRelease(t.surface);
   free(t.model);
   free(t.read);
   return ok;
}

static bool
gmem_targets(struct sgl_context *ctx)
{
   const char *vs = "attribute vec2 pos; void main() {gl_Position=vec4(pos,0.,1.);}";
   GLuint solid = program(vs, "precision highp float; uniform vec4 color; void main(){gl_FragColor=color;}");
   GLuint sample = program(vs, "precision highp float; uniform sampler2D tex; uniform vec2 size; void main(){"
                              "gl_FragColor=texture2D(tex,gl_FragCoord.xy/size)"
                              "+vec4(4./255.,2./255.,1./255.,0.);}");
   const float quad[] = {-1, -1, 1, -1, -1, 1, 1, 1};
   glBindBuffer(GL_ARRAY_BUFFER, 0);
   glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, quad);
   glEnableVertexAttribArray(0);
   glDisableVertexAttribArray(1);
   glDisable(GL_BLEND);
   glDisable(GL_DEPTH_TEST);
   glDisable(GL_STENCIL_TEST);
   glDisable(GL_SCISSOR_TEST);
   glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
   glActiveTexture(GL_TEXTURE0);
   bool ok = true;
   ok &= gm_target(ctx, 1127, 2438, 0, solid, sample);   /* CC backdrop size */
   ok &= gm_target(ctx, 1131, 2442, 0, solid, sample);   /* CC blur size */
   ok &= gm_target(ctx, 1125, 2436, 0, solid, sample);   /* the frame */
   ok &= gm_target(ctx, 1125, 2436, 256, solid, sample); /* rows with visible padding */
   ok &= gm_target(ctx, 67, 45, 64, solid, sample);      /* small, odd */
   ok &= gm_target(ctx, 1127, 2438, -1, solid, sample);  /* GL allocation */
   glDisableVertexAttribArray(0);
   glUseProgram(0);
   glDeleteProgram(solid);
   glDeleteProgram(sample);
   return ok;
}
