/*
 * Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 *
 * sweetgpu_gltest: OpenGL ES on the Adreno 512 through sweetgl (Mesa's GL on
 * freedreno, ios-jasmine G2). Plain GL ES 2.0 calls into a 64x64 offscreen
 * surface, each step checked with glReadPixels:
 *
 *  1. clear: glClearColor + glClear;
 *  2. triangle: GLSL ES vertex and fragment shaders, a vertex buffer, varyings
 *     and a uniform (red, green and blue corners, scaled by the uniform);
 *  3. texture: a 2x2 texture (nearest) on a full-surface quad, blended at
 *     alpha 0.5 over the clear color (what CoreAnimation does all day);
 *  4. depth: two overlapping quads drawn far-after-near with GL_LESS.
 *
 * Then, on iOS, IOSurfaces shared with the GPU (kernel j0032):
 *
 *  5. iosurface target: the triangle of step 2 rendered into a BGRA IOSurface
 *     the CPU filled with junk first, checked with glReadPixels and then in
 *     the surface's own memory through IOSurface.framework (top row first);
 *  6. iosurface texture: a BGRA IOSurface the CPU filled with four colored
 *     quadrants, sampled as a GL texture (texImageIOSurface).
 *
 * Prints PASS or FAIL per step and exits 0 when all pass.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <GLES2/gl2.h>

#include "util/os_time.h"
#include "sweetgl.h"

#ifdef __APPLE__
#include <CoreFoundation/CoreFoundation.h>

/* IOSurface.framework: the library is in the iPhoneOS SDK; declared here like IOKit in darwin/ */
typedef struct __IOSurface *IOSurfaceRef;
extern const CFStringRef kIOSurfaceWidth;
extern const CFStringRef kIOSurfaceHeight;
extern const CFStringRef kIOSurfaceBytesPerElement;
extern const CFStringRef kIOSurfacePixelFormat;
IOSurfaceRef IOSurfaceCreate(CFDictionaryRef properties);
uint32_t IOSurfaceGetID(IOSurfaceRef surface);
size_t IOSurfaceGetBytesPerRow(IOSurfaceRef surface);
void *IOSurfaceGetBaseAddress(IOSurfaceRef surface);
int IOSurfaceLock(IOSurfaceRef surface, uint32_t options, uint32_t *seed);
int IOSurfaceUnlock(IOSurfaceRef surface, uint32_t options, uint32_t *seed);
#define kIOSurfaceLockReadOnly 1
#endif

#define W 64
#define H 64

static uint8_t px[W * H * 4];

static const uint8_t clear_px[4] = { 0x40, 0x80, 0xbf, 0xff };

static void
gl_errors(const char *where)
{
   GLenum e;
   while ((e = glGetError()) != GL_NO_ERROR)
      printf("%s: GL error 0x%04x\n", where, e);
}

/* glReadPixels the surface into px (row 0 = bottom, GL window coordinates) */
static void
read_back(void)
{
   memset(px, 0x5a, sizeof(px));
   glReadPixels(0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE, px);
   gl_errors("glReadPixels");
}

/* compare px against expect(x, y) (false = skip), each channel within tol */
static bool
check(const char *what, bool (*expect)(unsigned x, unsigned y, uint8_t out[4]), int tol)
{
   unsigned bad = 0, checked = 0;
   for (unsigned y = 0; y < H; y++) {
      for (unsigned x = 0; x < W; x++) {
         const uint8_t *p = px + 4 * (y * W + x);
         uint8_t e[4];
         if (!expect(x, y, e))
            continue;
         checked++;
         bool ok = true;
         for (int i = 0; i < 4; i++)
            ok &= abs((int)p[i] - (int)e[i]) <= tol;
         if (!ok && bad++ < 4)
            printf("%s: pixel (%u,%u) %02x %02x %02x %02x, expected %02x %02x %02x %02x\n", what,
                   x, y, p[0], p[1], p[2], p[3], e[0], e[1], e[2], e[3]);
      }
   }
   static const unsigned marks[][2] = { { 0, 0 }, { 63, 0 }, { 0, 63 }, { 63, 63 }, { 16, 16 }, { 48, 48 } };
   printf("%s:", what);
   for (unsigned i = 0; i < sizeof(marks) / sizeof(marks[0]); i++) {
      const uint8_t *p = px + 4 * (marks[i][1] * W + marks[i][0]);
      printf(" (%u,%u) %02x%02x%02x%02x", marks[i][0], marks[i][1], p[0], p[1], p[2], p[3]);
   }
   printf("; %u of %u checked wrong\n", bad, checked);
   printf("%s %s\n", bad == 0 && checked ? "PASS:" : "FAIL:", what);
   return bad == 0 && checked;
}

static GLuint
shader(GLenum type, const char *src)
{
   GLuint s = glCreateShader(type);
   glShaderSource(s, 1, &src, NULL);
   glCompileShader(s);
   GLint ok = 0;
   glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
   if (!ok) {
      char log[1024] = "";
      glGetShaderInfoLog(s, sizeof(log), NULL, log);
      printf("shader compile failed: %s\n", log);
   }
   return s;
}

static GLuint
program(const char *vs, const char *fs)
{
   GLuint p = glCreateProgram();
   glAttachShader(p, shader(GL_VERTEX_SHADER, vs));
   glAttachShader(p, shader(GL_FRAGMENT_SHADER, fs));
   glBindAttribLocation(p, 0, "pos");
   glBindAttribLocation(p, 1, "attr");
   glLinkProgram(p);
   GLint ok = 0;
   glGetProgramiv(p, GL_LINK_STATUS, &ok);
   if (!ok) {
      char log[1024] = "";
      glGetProgramInfoLog(p, sizeof(log), NULL, log);
      printf("program link failed: %s\n", log);
   }
   return p;
}

/* --- 1. clear */

static bool
clear_expected(unsigned x, unsigned y, uint8_t out[4])
{
   memcpy(out, clear_px, 4);
   return true;
}

static void
clear(void)
{
   glClearColor(0.25f, 0.5f, 0.75f, 1.0f);
   glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
}

/* --- 2. triangle: corners (0,0) red, (W,0) green, (0,H) blue, times 0.5..1 */

static const float tri_scale = 0.8f;

static bool
tri_expected(unsigned x, unsigned y, uint8_t out[4])
{
   float fx = x + 0.5f, fy = y + 0.5f;
   float edge = fx + fy - (float)W;
   if (fabsf(edge) < 1.0f)
      return false;
   if (edge > 0) {
      memcpy(out, clear_px, 4);
      return true;
   }
   float b = fx / W, c = fy / H, a = 1.0f - b - c;
   out[0] = (uint8_t)lrintf(a * tri_scale * 255.0f);
   out[1] = (uint8_t)lrintf(b * tri_scale * 255.0f);
   out[2] = (uint8_t)lrintf(c * tri_scale * 255.0f);
   out[3] = 0xff;
   return true;
}

static const char tri_vs[] =
   "attribute vec4 pos;\n"
   "attribute vec3 attr;\n"
   "varying mediump vec3 color;\n"
   "void main() {\n"
   "   color = attr;\n"
   "   gl_Position = pos;\n"
   "}\n";

static const char tri_fs[] =
   "precision mediump float;\n"
   "uniform float scale;\n"
   "varying vec3 color;\n"
   "void main() {\n"
   "   gl_FragColor = vec4(color * scale, 1.0);\n"
   "}\n";

static bool
triangle(const char *what)
{
   static const float verts[] = {
      /* x, y, then r, g, b */
      -1.0f, -1.0f, 1.0f, 0.0f, 0.0f,
      1.0f, -1.0f, 0.0f, 1.0f, 0.0f,
      -1.0f, 1.0f, 0.0f, 0.0f, 1.0f,
   };
   GLuint p = program(tri_vs, tri_fs);
   glUseProgram(p);
   glUniform1f(glGetUniformLocation(p, "scale"), tri_scale);
   GLuint vbo;
   glGenBuffers(1, &vbo);
   glBindBuffer(GL_ARRAY_BUFFER, vbo);
   glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
   glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 20, (void *)0);
   glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 20, (void *)8);
   glEnableVertexAttribArray(0);
   glEnableVertexAttribArray(1);

   clear();
   glDrawArrays(GL_TRIANGLES, 0, 3);
   gl_errors("triangle");
   read_back();

   glDisableVertexAttribArray(0);
   glDisableVertexAttribArray(1);
   glBindBuffer(GL_ARRAY_BUFFER, 0);
   glDeleteBuffers(1, &vbo);
   glUseProgram(0);
   glDeleteProgram(p);
   return check(what, tri_expected, 3);
}

/* --- 3. texture: 2x2 texels, one per quadrant, blended at alpha 0.5 */

static const uint8_t texels[4][4] = {
   { 0xff, 0x00, 0x00, 0x80 }, /* bottom left: red */
   { 0x00, 0xff, 0x00, 0x80 }, /* bottom right: green */
   { 0x00, 0x00, 0xff, 0x80 }, /* top left: blue */
   { 0xff, 0xff, 0xff, 0x80 }, /* top right: white */
};

static bool
tex_expected(unsigned x, unsigned y, uint8_t out[4])
{
   const uint8_t *t = texels[(y >= H / 2) * 2 + (x >= W / 2)];
   float a = t[3] / 255.0f;
   for (int i = 0; i < 3; i++)
      out[i] = (uint8_t)lrintf(t[i] * a + clear_px[i] * (1.0f - a));
   /* alpha blends too: a * a + 1 * (1 - a) */
   out[3] = (uint8_t)lrintf((a * a + (1.0f - a)) * 255.0f);
   return true;
}

static const char tex_vs[] =
   "attribute vec4 pos;\n"
   "attribute vec2 attr;\n"
   "varying vec2 uv;\n"
   "void main() {\n"
   "   uv = attr;\n"
   "   gl_Position = pos;\n"
   "}\n";

static const char tex_fs[] =
   "precision mediump float;\n"
   "uniform sampler2D tex;\n"
   "varying vec2 uv;\n"
   "void main() {\n"
   "   gl_FragColor = texture2D(tex, uv);\n"
   "}\n";

static bool
texture(void)
{
   static const float quad[] = {
      -1.0f, -1.0f, 0.0f, 0.0f,
      1.0f, -1.0f, 1.0f, 0.0f,
      -1.0f, 1.0f, 0.0f, 1.0f,
      1.0f, 1.0f, 1.0f, 1.0f,
   };
   GLuint tex;
   glGenTextures(1, &tex);
   glBindTexture(GL_TEXTURE_2D, tex);
   glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 2, 2, 0, GL_RGBA, GL_UNSIGNED_BYTE, texels);
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

   GLuint p = program(tex_vs, tex_fs);
   glUseProgram(p);
   glUniform1i(glGetUniformLocation(p, "tex"), 0);
   /* client-side arrays: GL ES 2 allows them, and CoreAnimation uses them */
   glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, quad);
   glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, quad + 2);
   glEnableVertexAttribArray(0);
   glEnableVertexAttribArray(1);
   glEnable(GL_BLEND);
   glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

   clear();
   glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
   gl_errors("texture");
   read_back();

   glDisable(GL_BLEND);
   glDisableVertexAttribArray(0);
   glDisableVertexAttribArray(1);
   glUseProgram(0);
   glDeleteProgram(p);
   glDeleteTextures(1, &tex);
   return check("texture", tex_expected, 2);
}

/* --- 4. depth: left quad at z -0.5 (near, red) drawn first, right quad at
 * z 0.5 (far, green) over it; the overlap x 24..39 must stay red */

static bool
depth_expected(unsigned x, unsigned y, uint8_t out[4])
{
   static const uint8_t red[4] = { 0xff, 0, 0, 0xff }, green[4] = { 0, 0xff, 0, 0xff };
   if (y == 15 || y == 16 || y == 47 || y == 48 || x == 39 || x == 40 || x == 23 || x == 24)
      return false; /* edges */
   if (y < 16 || y >= 48)
      memcpy(out, clear_px, 4);
   else if (x < 40)
      memcpy(out, red, 4);
   else
      memcpy(out, green, 4);
   return true;
}

static const char depth_vs[] =
   "attribute vec4 pos;\n"
   "void main() {\n"
   "   gl_Position = pos;\n"
   "}\n";

static const char depth_fs[] =
   "precision mediump float;\n"
   "uniform vec4 color;\n"
   "void main() {\n"
   "   gl_FragColor = color;\n"
   "}\n";

static bool
depth(void)
{
   /* x -1..0.25 (pixels 0..39) near, x -0.25..1 (pixels 24..63) far; y 16..47 */
   static const float near_quad[] = {
      -1.0f, -0.5f, -0.5f, 0.25f, -0.5f, -0.5f, -1.0f, 0.5f, -0.5f, 0.25f, 0.5f, -0.5f,
   };
   static const float far_quad[] = {
      -0.25f, -0.5f, 0.5f, 1.0f, -0.5f, 0.5f, -0.25f, 0.5f, 0.5f, 1.0f, 0.5f, 0.5f,
   };
   GLuint p = program(depth_vs, depth_fs);
   glUseProgram(p);
   GLint color = glGetUniformLocation(p, "color");
   glEnableVertexAttribArray(0);
   glEnable(GL_DEPTH_TEST);
   glDepthFunc(GL_LESS);

   clear();
   glUniform4f(color, 1.0f, 0.0f, 0.0f, 1.0f);
   glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, near_quad);
   glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
   glUniform4f(color, 0.0f, 1.0f, 0.0f, 1.0f);
   glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, far_quad);
   glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
   gl_errors("depth");
   read_back();

   glDisable(GL_DEPTH_TEST);
   glDisableVertexAttribArray(0);
   glUseProgram(0);
   glDeleteProgram(p);
   return check("depth", depth_expected, 1);
}

#ifdef __APPLE__
/* --- 5 and 6: IOSurfaces */

static void
dict_set_u32(CFMutableDictionaryRef dict, CFStringRef key, uint32_t value)
{
   CFNumberRef n = CFNumberCreate(NULL, kCFNumberSInt32Type, &value);
   CFDictionarySetValue(dict, key, n);
   CFRelease(n);
}

/* a W x H BGRA IOSurface; *bpr = its bytes per row */
static IOSurfaceRef
iosurface_new(uint32_t *bpr)
{
   CFMutableDictionaryRef props = CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks,
                                                            &kCFTypeDictionaryValueCallBacks);
   dict_set_u32(props, kIOSurfaceWidth, W);
   dict_set_u32(props, kIOSurfaceHeight, H);
   dict_set_u32(props, kIOSurfaceBytesPerElement, 4);
   dict_set_u32(props, kIOSurfacePixelFormat, SGL_IOSURFACE_BGRA);
   IOSurfaceRef s = IOSurfaceCreate(props);
   CFRelease(props);
   if (!s) {
      printf("IOSurfaceCreate failed\n");
      return NULL;
   }
   *bpr = (uint32_t)IOSurfaceGetBytesPerRow(s);
   printf("IOSurface %u: %ux%u BGRA, %u bytes per row\n", IOSurfaceGetID(s), W, H, *bpr);
   return s;
}

/* the surface's memory (BGRA, top row first) into px (RGBA, row 0 = bottom); flip = false keeps the rows */
static void
iosurface_read(IOSurfaceRef s, uint32_t bpr, bool flip)
{
   IOSurfaceLock(s, kIOSurfaceLockReadOnly, NULL);
   const uint8_t *base = IOSurfaceGetBaseAddress(s);
   for (unsigned y = 0; y < H; y++) {
      const uint8_t *row = base + (size_t)bpr * (flip ? H - 1 - y : y);
      for (unsigned x = 0; x < W; x++) {
         uint8_t *p = px + 4 * (y * W + x);
         p[0] = row[4 * x + 2];
         p[1] = row[4 * x + 1];
         p[2] = row[4 * x + 0];
         p[3] = row[4 * x + 3];
      }
   }
   IOSurfaceUnlock(s, kIOSurfaceLockReadOnly, NULL);
}

static bool
iosurface_target(struct sgl_display *dpy, struct sgl_context *ctx, struct sgl_surface *back)
{
   uint32_t bpr;
   IOSurfaceRef s = iosurface_new(&bpr);
   if (!s)
      return false;
   /* junk first, so pixels the GPU did not write show */
   IOSurfaceLock(s, 0, NULL);
   memset(IOSurfaceGetBaseAddress(s), 0x5a, (size_t)bpr * H);
   IOSurfaceUnlock(s, 0, NULL);

   bool ok = false;
   struct sgl_surface *surf =
      sgl_surface_create_iosurface(dpy, IOSurfaceGetID(s), W, H, bpr, SGL_IOSURFACE_BGRA, true);
   if (!surf || !sgl_make_current(ctx, surf)) {
      printf("FAIL: no IOSurface surface or make-current failed\n");
   } else {
      glViewport(0, 0, W, H);
      ok = triangle("iosurface target (glReadPixels)");
      glFinish();
      iosurface_read(s, bpr, true);
      bool mem = check("iosurface target (IOSurface memory)", tri_expected, 3);
      if (!mem) {
         iosurface_read(s, bpr, false);
         printf("iosurface target: the memory %s with the rows not flipped\n",
                check("iosurface target (unflipped)", tri_expected, 3) ? "matches" : "does not match either");
      }
      ok &= mem;
   }
   sgl_make_current(ctx, back);
   sgl_surface_destroy(surf);
   CFRelease(s);
   return ok;
}

static bool
iosurface_tex_expected(unsigned x, unsigned y, uint8_t out[4])
{
   memcpy(out, texels[(y >= H / 2) * 2 + (x >= W / 2)], 4);
   out[3] = 0xff;
   return true;
}

static bool
iosurface_texture(struct sgl_context *ctx)
{
   uint32_t bpr;
   IOSurfaceRef s = iosurface_new(&bpr);
   if (!s)
      return false;
   /* the texels of step 3, opaque, a quadrant each; memory row 0 is texture row 0 */
   IOSurfaceLock(s, 0, NULL);
   uint8_t *base = IOSurfaceGetBaseAddress(s);
   for (unsigned r = 0; r < H; r++) {
      for (unsigned x = 0; x < W; x++) {
         const uint8_t *t = texels[(r >= H / 2) * 2 + (x >= W / 2)];
         uint8_t *p = base + (size_t)bpr * r + 4 * x;
         p[0] = t[2];
         p[1] = t[1];
         p[2] = t[0];
         p[3] = 0xff;
      }
   }
   IOSurfaceUnlock(s, 0, NULL);

   static const float quad[] = {
      -1.0f, -1.0f, 0.0f, 0.0f,
      1.0f, -1.0f, 1.0f, 0.0f,
      -1.0f, 1.0f, 0.0f, 1.0f,
      1.0f, 1.0f, 1.0f, 1.0f,
   };
   GLuint tex;
   glGenTextures(1, &tex);
   glBindTexture(GL_TEXTURE_2D, tex);
   if (!sgl_tex_image_iosurface(ctx, GL_TEXTURE_2D, IOSurfaceGetID(s), W, H, bpr, SGL_IOSURFACE_BGRA)) {
      printf("FAIL: sgl_tex_image_iosurface\n");
      glDeleteTextures(1, &tex);
      CFRelease(s);
      return false;
   }
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

   GLuint p = program(tex_vs, tex_fs);
   glUseProgram(p);
   glUniform1i(glGetUniformLocation(p, "tex"), 0);
   glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, quad);
   glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, quad + 2);
   glEnableVertexAttribArray(0);
   glEnableVertexAttribArray(1);

   clear();
   glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
   gl_errors("iosurface texture");
   read_back();

   glDisableVertexAttribArray(0);
   glDisableVertexAttribArray(1);
   glUseProgram(0);
   glDeleteProgram(p);
   glDeleteTextures(1, &tex);
   CFRelease(s);
   return check("iosurface texture", iosurface_tex_expected, 0);
}
#include "sweetgpu_feedback_test.inc"
#include "sweetgpu_gmem_test.inc"
#endif

/* Active sampler state must describe the next draw, even before validation.
 * An unused bound texture must not turn a non-feedback draw into a barrier.
 */
static bool
sampled_units_are(struct sgl_context *ctx, const char *phase, uint32_t expected)
{
   uint32_t got = sgl_sampled_2d_units(ctx);
   GLenum error = glGetError();
   bool ok = got == expected && error == GL_NO_ERROR;
   printf("%s sampler units %s: 0x%x expected 0x%x, GL error 0x%x\n",
          ok ? "PASS:" : "FAIL:", phase, got, expected, error);
   return ok;
}

static bool
sampler_units(struct sgl_context *ctx)
{
   const char *vs = "attribute vec2 pos; void main() { gl_Position=vec4(pos,0.,1.); }";
   const char *fs = "precision mediump float; uniform sampler2D tex[2];"
                    "void main() { gl_FragColor=texture2D(tex[0],vec2(.5))"
                    "+texture2D(tex[1],vec2(.5)); }";
   GLuint p = program(vs, fs);
   glUseProgram(p);
   bool ok = sampled_units_are(ctx, "link defaults", 1);
   GLint loc = glGetUniformLocation(p, "tex[0]");
   GLint units[] = {1, 3};
   glUniform1iv(loc, 2, units);
   ok &= sampled_units_are(ctx, "array remap", (1u << 1) | (1u << 3));
   glUniform1i(glGetUniformLocation(p, "tex[1]"), 5);
   ok &= sampled_units_are(ctx, "element remap", (1u << 1) | (1u << 5));
   GLuint stale;
   glGenTextures(1, &stale);
   glActiveTexture(GL_TEXTURE7);
   glBindTexture(GL_TEXTURE_2D, stale);
   ok &= sampled_units_are(ctx, "unused binding", (1u << 1) | (1u << 5));
   GLuint plain = program(vs, "precision mediump float; void main() { gl_FragColor=vec4(1.); }");
   glUseProgram(plain);
   ok &= sampled_units_are(ctx, "no samplers", 0);
   glUseProgram(p);
   ok &= sampled_units_are(ctx, "program switch", (1u << 1) | (1u << 5));
   glLinkProgram(p);
   ok &= sampled_units_are(ctx, "relink resets units", 1);
   GLuint vertex = program("attribute vec2 pos; uniform sampler2D vtex;"
                           "void main() { gl_Position=vec4(pos,texture2DLod(vtex,vec2(.5),0.).r,1.); }",
                           fs);
   glUseProgram(vertex);
   glUniform1i(glGetUniformLocation(vertex, "vtex"), 2);
   ok &= sampled_units_are(ctx, "vertex and fragment", 1u | (1u << 2));
   glUseProgram(0);
   ok &= sampled_units_are(ctx, "unbound program", 0);
   glDeleteProgram(p);
   glDeleteProgram(plain);
   glDeleteProgram(vertex);
   glDeleteTextures(1, &stale);
   glActiveTexture(GL_TEXTURE0);
   return ok;
}

int
main(int argc, char **argv)
{
   bool feedback_diagnostics = false;
   for (int i = 1; i < argc; i++) {
      if (!strcmp(argv[i], "--sysbarrier-on") || !strcmp(argv[i], "--sysbarrier-off") ||
          !strcmp(argv[i], "--sysbarrier-wide")) {
         /* 1 = patch 0008's narrow eligibility, 2 = task 24 stage 2's widened one */
         setenv("SWEETCA_SYS_BARRIER", !strcmp(argv[i], "--sysbarrier-on") ? "1" :
                !strcmp(argv[i], "--sysbarrier-wide") ? "2" : "0", 1);
         setenv("FD_MESA_DEBUG", "sysmem,nofp16", 1);
      } else if (!strcmp(argv[i], "--gmem") || !strcmp(argv[i], "--gmem-force")) {
         /* task 24 stage 3: 1 = per-batch cost rule, 2 = every eligible batch through GMEM */
         setenv("SWEETCA_GMEM", !strcmp(argv[i], "--gmem") ? "1" : "2", 1);
         setenv("FD_MESA_DEBUG", "sysmem,nofp16", 1);
      } else if (!strcmp(argv[i], "--no-tc")) {
         setenv("GALLIUM_THREAD", "0", 1);
      } else if (!strcmp(argv[i], "--feedback-diagnostics")) {
         feedback_diagnostics = true;
      } else {
         fprintf(stderr, "usage: sweetgpu_gltest [--sysbarrier-on|--sysbarrier-wide|--sysbarrier-off] [--gmem|--gmem-force] [--no-tc] [--feedback-diagnostics]\n");
         return 2;
      }
   }
   if (feedback_diagnostics) {
      /* Diagnostics isolate the disabled baseline, never enable retention. */
      setenv("SWEETCA_SYS_BARRIER", "0", 1);
      setenv("FD_MESA_DEBUG", "sysmem,nofp16", 1);
   }
   setvbuf(stdout, NULL, _IONBF, 0);
   printf("step: display\n");
   struct sgl_display *dpy = sgl_display_create();
   if (!dpy) {
      printf("FAIL: no display (is SweetGPU up? sweetgpu=4)\n");
      return 1;
   }
   printf("step: context\n");
   struct sgl_context *ctx = sgl_context_create(dpy, 2, NULL);
   if (!ctx) {
      printf("FAIL: no GL ES context\n");
      return 1;
   }
   printf("step: surface\n");
   struct sgl_surface *surf = sgl_surface_create(dpy, W, H, true);
   if (!surf || !sgl_make_current(ctx, surf)) {
      printf("FAIL: no surface or make-current failed\n");
      return 1;
   }
   printf("GL_VERSION: %s\n", glGetString(GL_VERSION));
   printf("GL_RENDERER: %s\n", glGetString(GL_RENDERER));
   printf("GL_SHADING_LANGUAGE_VERSION: %s\n", glGetString(GL_SHADING_LANGUAGE_VERSION));
   const char *ext = (const char *)glGetString(GL_EXTENSIONS);
   unsigned n = 0;
   for (const char *e = ext; e && *e; e++)
      n += *e == ' ';
   printf("GL_EXTENSIONS: %u\n", n + (ext && *ext));
   glViewport(0, 0, W, H);

   bool ok = true;
   int64_t t0 = os_time_get_nano();
   printf("step: clear\n");
   clear();
   read_back();
   ok &= check("clear", clear_expected, 0);
   printf("step: triangle\n");
   ok &= triangle("triangle");
   printf("step: texture\n");
   ok &= texture();
   printf("step: depth\n");
   ok &= depth();
   unsigned steps = 4;
   printf("step: active sampler units\n");
   ok &= sampler_units(ctx);
   steps++;
#ifdef __APPLE__
   printf("step: iosurface target\n");
   ok &= iosurface_target(dpy, ctx, surf);
   printf("step: iosurface texture\n");
   ok &= iosurface_texture(ctx);
   printf("step: %s\n", feedback_diagnostics ? "feedback diagnostic controls (barrier off)" : "ordered framebuffer feedback");
   ok &= feedback(ctx, feedback_diagnostics);
   steps += 3;
   if (!feedback_diagnostics) {
      printf("step: gmem targets (odd sizes, imported and GL-allocated)\n");
      ok &= gmem_targets(ctx);
      steps++;
   }
#endif
   printf("%u steps in %.1f ms\n", steps, (os_time_get_nano() - t0) / 1e6);

   sgl_make_current(NULL, NULL);
   sgl_surface_destroy(surf);
   sgl_context_destroy(ctx);
   sgl_display_destroy(dpy);
   printf("%s\n", ok ? "PASS: all" : "FAIL");
   return ok ? 0 : 1;
}
