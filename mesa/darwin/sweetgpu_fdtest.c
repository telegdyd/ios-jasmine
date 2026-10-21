/*
 * Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 *
 * sweetgpu_fdtest: the first tests of Mesa freedreno on ios-jasmine's
 * SweetGPU kernel driver (G2). Gallium only, no GL: creates the freedreno
 * screen on the darwin backend and renders into a 64x64 RGBA8 target:
 *
 *  1. clear: clears it to a color on the GPU (a5xx: GMEM tiles, then a
 *     resolve to memory), waits for the fence and reads the pixels back;
 *  2. triangle: clears again and draws one triangle with a red, a green and
 *     a blue corner (TGSI pass-through shaders, compiled by ir3), then checks
 *     every pixel against the interpolated color or the clear color.
 *
 * Prints PASS or FAIL and exits 0 or 1.
 */

#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#include "pipe/p_context.h"
#include "pipe/p_defines.h"
#include "pipe/p_screen.h"
#include "pipe/p_shader_tokens.h"
#include "pipe/p_state.h"
#include "compiler/glsl_types.h"
#include "frontend/drm_driver.h"
#include "util/os_time.h"
#include "util/driconf.h"
#include "util/u_draw.h"
#include "util/u_inlines.h"
#include "util/u_simple_shaders.h"
#include "util/xmlconfig.h"

#include "freedreno_screen.h"

/* the options the pipe-loader would give freedreno: gallium's, then its own */
static const driOptionDescription fd_driconf[] = {
#include "pipe-loader/driinfo_gallium.h"
#include "driinfo_freedreno.h"
};

#define W 64
#define H 64

/* the clear color, RGBA (0.25, 0.5, 0.75, 1.0) */
static const uint8_t clear_px[4] = { 0x40, 0x80, 0xbf, 0xff };

/* flush the context and wait for its fence; prints the time since t0 */
static bool
flush_and_wait(struct pipe_screen *screen, struct pipe_context *pipe, const char *what, int64_t t0)
{
   struct pipe_fence_handle *fence = NULL;
   printf("step: flush\n");
   pipe->flush(pipe, &fence, 0);
   printf("step: fence\n");
   bool done = fence && screen->fence_finish(screen, NULL, fence, 5ull * 1000 * 1000 * 1000);
   screen->fence_reference(screen, &fence, NULL);
   printf("%s + flush + fence: %s after %.3f ms\n", what, done ? "done" : "TIMEOUT",
          (os_time_get_nano() - t0) / 1e6);
   return done;
}

/* triangle (0,0) red, (W,0) green, (0,H) blue in window coordinates: the
 * expected color at pixel (x, y), or the clear color outside it. Pixels whose
 * centers are within a pixel of the hypotenuse are skipped (fill rules). */
static bool
tri_expected(unsigned x, unsigned y, uint8_t out[4])
{
   float px = x + 0.5f, py = y + 0.5f;
   float edge = px + py - (float)W;
   if (fabsf(edge) < 1.0f)
      return false;
   if (edge > 0) {
      for (int i = 0; i < 4; i++)
         out[i] = clear_px[i];
      return true;
   }
   float b = px / W, c = py / H, a = 1.0f - b - c;
   out[0] = (uint8_t)lrintf(a * 255.0f);
   out[1] = (uint8_t)lrintf(b * 255.0f);
   out[2] = (uint8_t)lrintf(c * 255.0f);
   out[3] = 0xff;
   return true;
}

/* read the target back and compare: each channel within tol of the expected
 * value (expect(x, y) == false skips the pixel); returns the wrong count */
static unsigned
check(struct pipe_context *pipe, struct pipe_resource *rt, const char *what,
      bool (*expect)(unsigned x, unsigned y, uint8_t out[4]), int tol)
{
   struct pipe_box box = { .width = W, .height = H, .depth = 1 };
   struct pipe_transfer *xfer = NULL;
   const uint8_t *px = pipe->texture_map(pipe, rt, 0, PIPE_MAP_READ, &box, &xfer);
   if (!px) {
      printf("%s: render target not mappable\n", what);
      return W * H;
   }
   unsigned bad = 0, checked = 0;
   for (unsigned y = 0; y < H; y++) {
      const uint8_t *row = px + y * xfer->stride;
      for (unsigned x = 0; x < W; x++) {
         const uint8_t *p = row + 4 * x;
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
   /* a few landmarks: corners and the triangle's inside */
   static const unsigned marks[][2] = { { 0, 0 }, { 63, 0 }, { 0, 63 }, { 63, 63 }, { 16, 16 } };
   printf("%s:", what);
   for (unsigned i = 0; i < ARRAY_SIZE(marks); i++) {
      const uint8_t *p = px + marks[i][1] * xfer->stride + 4 * marks[i][0];
      printf(" (%u,%u) %02x%02x%02x%02x", marks[i][0], marks[i][1], p[0], p[1], p[2], p[3]);
   }
   printf("; stride %u; %u of %u checked wrong\n", xfer->stride, bad, checked);
   pipe->texture_unmap(pipe, xfer);
   return bad;
}

static bool
clear_expected(unsigned x, unsigned y, uint8_t out[4])
{
   for (int i = 0; i < 4; i++)
      out[i] = clear_px[i];
   return true;
}

/* test 2: one triangle with per-vertex colors over the clear color */
static bool
triangle(struct pipe_screen *screen, struct pipe_context *pipe, struct pipe_resource *rt)
{
   const union pipe_color_union color = { .f = { 0.25f, 0.5f, 0.75f, 1.0f } };

   printf("step: shaders\n");
   const enum tgsi_semantic names[] = { TGSI_SEMANTIC_POSITION, TGSI_SEMANTIC_GENERIC };
   const unsigned indexes[] = { 0, 0 };
   void *vs = util_make_vertex_passthrough_shader(pipe, 2, names, indexes, false);
   void *fs = util_make_fragment_passthrough_shader(pipe, TGSI_SEMANTIC_GENERIC,
                                                    TGSI_INTERPOLATE_PERSPECTIVE, false);
   if (!vs || !fs) {
      printf("triangle: shader creation failed (vs %p fs %p)\n", vs, fs);
      return false;
   }

   printf("step: state\n");
   struct pipe_blend_state blend = { 0 };
   blend.rt[0].colormask = PIPE_MASK_RGBA;
   void *blend_cso = pipe->create_blend_state(pipe, &blend);
   struct pipe_depth_stencil_alpha_state dsa = { 0 };
   void *dsa_cso = pipe->create_depth_stencil_alpha_state(pipe, &dsa);
   struct pipe_rasterizer_state rast = {
      .cull_face = PIPE_FACE_NONE,
      .half_pixel_center = 1,
      .bottom_edge_rule = 1,
      .depth_clip_near = 1,
      .depth_clip_far = 1,
   };
   void *rast_cso = pipe->create_rasterizer_state(pipe, &rast);

   /* position (NDC), then color: the corners land on window (0,0), (W,0), (0,H) */
   static const float verts[3][8] = {
      { -1.0f, -1.0f, 0.0f, 1.0f, 1.0f, 0.0f, 0.0f, 1.0f },
      { 1.0f, -1.0f, 0.0f, 1.0f, 0.0f, 1.0f, 0.0f, 1.0f },
      { -1.0f, 1.0f, 0.0f, 1.0f, 0.0f, 0.0f, 1.0f, 1.0f },
   };
   struct pipe_resource *vbuf = pipe_buffer_create_with_data(pipe, PIPE_BIND_VERTEX_BUFFER,
                                                             PIPE_USAGE_IMMUTABLE, sizeof(verts), verts);
   struct pipe_vertex_element ve[2] = {
      { .src_offset = 0, .src_format = PIPE_FORMAT_R32G32B32A32_FLOAT, .src_stride = 32 },
      { .src_offset = 16, .src_format = PIPE_FORMAT_R32G32B32A32_FLOAT, .src_stride = 32 },
   };
   void *ve_cso = pipe->create_vertex_elements_state(pipe, 2, ve);
   struct pipe_vertex_buffer vb = { .buffer.resource = vbuf };

   struct pipe_viewport_state vp = {
      .scale = { W / 2.0f, H / 2.0f, 0.5f },
      .translate = { W / 2.0f, H / 2.0f, 0.5f },
      .swizzle_x = PIPE_VIEWPORT_SWIZZLE_POSITIVE_X,
      .swizzle_y = PIPE_VIEWPORT_SWIZZLE_POSITIVE_Y,
      .swizzle_z = PIPE_VIEWPORT_SWIZZLE_POSITIVE_Z,
      .swizzle_w = PIPE_VIEWPORT_SWIZZLE_POSITIVE_W,
   };

   pipe->bind_blend_state(pipe, blend_cso);
   pipe->bind_depth_stencil_alpha_state(pipe, dsa_cso);
   pipe->bind_rasterizer_state(pipe, rast_cso);
   pipe->bind_vs_state(pipe, vs);
   pipe->bind_fs_state(pipe, fs);
   pipe->bind_vertex_elements_state(pipe, ve_cso);
   pipe->set_vertex_buffers(pipe, 1, &vb); /* takes the vbuf reference */
   pipe->set_viewport_states(pipe, 0, 1, &vp);
   pipe->set_sample_mask(pipe, ~0u);

   int64_t t0 = os_time_get_nano();
   printf("step: clear\n");
   pipe->clear(pipe, PIPE_CLEAR_COLOR0, 0xffffffff, 0, NULL, &color, 0.0, 0);
   printf("step: draw\n");
   util_draw_arrays(pipe, MESA_PRIM_TRIANGLES, 0, 3);
   bool done = flush_and_wait(screen, pipe, "triangle", t0);
   unsigned bad = done ? check(pipe, rt, "triangle", tri_expected, 3) : W * H;

   pipe->bind_vs_state(pipe, NULL);
   pipe->bind_fs_state(pipe, NULL);
   pipe->delete_vs_state(pipe, vs);
   pipe->delete_fs_state(pipe, fs);
   pipe->delete_blend_state(pipe, blend_cso);
   pipe->delete_depth_stencil_alpha_state(pipe, dsa_cso);
   pipe->delete_rasterizer_state(pipe, rast_cso);
   pipe->delete_vertex_elements_state(pipe, ve_cso);
   return done && bad == 0;
}

int
main(void)
{
   /* unbuffered: whatever happens, the last step printed is the last one reached */
   setvbuf(stdout, NULL, _IONBF, 0);
   /* what a GL frontend does first: ir3 builds GLSL types (tgsi_to_nir, UBO lowering) */
   glsl_type_singleton_init_or_ref();
   printf("step: options\n");
   driOptionCache options, options_info;
   driParseOptionInfo(&options_info, fd_driconf, ARRAY_SIZE(fd_driconf));
   driParseOptionInfo(&options, fd_driconf, ARRAY_SIZE(fd_driconf));
   struct pipe_screen_config config = {
      .options = &options,
      .options_info = &options_info,
   };

   /* the darwin backend ignores the fd; fd_screen_create dup()s it */
   int fd = open("/dev/null", O_RDWR);
   printf("step: screen\n");
   struct pipe_screen *screen = fd_screen_create(fd, &config, NULL);
   if (!screen) {
      printf("FAIL: no freedreno screen (is SweetGPU up? sweetgpu=4)\n");
      return 1;
   }
   printf("screen: %s (%s)\n", screen->get_name(screen), screen->get_vendor(screen));

   printf("step: context\n");
   struct pipe_context *pipe = screen->context_create(screen, NULL, 0);
   if (!pipe) {
      printf("FAIL: no context\n");
      return 1;
   }

   struct pipe_resource templ = {
      .target = PIPE_TEXTURE_2D,
      .format = PIPE_FORMAT_R8G8B8A8_UNORM,
      .width0 = W,
      .height0 = H,
      .depth0 = 1,
      .array_size = 1,
      .bind = PIPE_BIND_RENDER_TARGET | PIPE_BIND_SAMPLER_VIEW,
      .usage = PIPE_USAGE_DEFAULT,
   };
   printf("step: render target\n");
   struct pipe_resource *rt = screen->resource_create(screen, &templ);
   if (!rt) {
      printf("FAIL: no render target\n");
      return 1;
   }

   struct pipe_framebuffer_state fb = {
      .width = W,
      .height = H,
      .layers = 1,
      .nr_cbufs = 1,
   };
   fb.cbufs[0].format = templ.format;
   fb.cbufs[0].texture = rt;
   pipe->set_framebuffer_state(pipe, &fb);

   /* test 1: clear */
   union pipe_color_union color = { .f = { 0.25f, 0.5f, 0.75f, 1.0f } };
   int64_t t0 = os_time_get_nano();
   printf("step: clear\n");
   pipe->clear(pipe, PIPE_CLEAR_COLOR0, 0xffffffff, 0, NULL, &color, 0.0, 0);
   bool clear_ok = flush_and_wait(screen, pipe, "clear", t0);
   clear_ok = clear_ok && check(pipe, rt, "clear", clear_expected, 0) == 0;
   printf("%s\n", clear_ok ? "PASS: the GPU cleared the render target" : "FAIL: clear");

   /* test 2: triangle (only after a good clear: a hung GPU stays hung) */
   bool tri_ok = clear_ok && triangle(screen, pipe, rt);
   if (clear_ok)
      printf("%s\n", tri_ok ? "PASS: the GPU drew the triangle" : "FAIL: triangle");

   pipe_resource_reference(&rt, NULL);
   pipe->destroy(pipe);
   screen->destroy(screen);
   close(fd);
   glsl_type_singleton_decref();

   printf("%s\n", clear_ok && tri_ok ? "PASS: all" : "FAIL");
   return clear_ok && tri_ok ? 0 : 1;
}
