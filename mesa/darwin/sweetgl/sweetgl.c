/*
 * Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 *
 * sweetgl: GL ES contexts on the freedreno screen, without EGL or DRI (see
 * sweetgl.h). The structure follows Haiku's hgl frontend: a
 * pipe_frontend_screen for st/mesa, and surfaces that are
 * pipe_frontend_drawables whose validate() hands st/mesa our textures.
 */

#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>

#include "pipe/p_screen.h"
#include "pipe/p_state.h"
#include "frontend/api.h"
#include "frontend/drm_driver.h"
#include "frontend/winsys_handle.h"
#include "drm-uapi/drm_fourcc.h"
#include "state_tracker/st_context.h"
#include "util/driconf.h"
#include "util/simple_mtx.h"
#include "util/format/u_format.h"
#include "util/u_atomic.h"
#include "util/u_inlines.h"
#include "util/u_memory.h"
#include "util/xmlconfig.h"
#include "compiler/glsl_types.h"

#include "sweetgl.h"

struct renderonly;
struct pipe_screen *fd_screen_create(int fd, const struct pipe_screen_config *config,
                                     struct renderonly *ro);

/* the options the pipe-loader would give freedreno: gallium's, then its own */
static const driOptionDescription fd_driconf[] = {
#include "pipe-loader/driinfo_gallium.h"
#include "driinfo_freedreno.h"
};

struct sgl_display {
   struct pipe_frontend_screen fscreen;
   driOptionCache options, options_info;
   int fd;
};

struct sgl_context {
   struct sgl_display *dpy;
   struct st_context *st;
};

struct sgl_surface {
   struct pipe_frontend_drawable base;
   struct st_visual visual;
   struct sgl_display *dpy;
   unsigned width, height;
   struct pipe_resource *textures[ST_ATTACHMENT_COUNT];
};

static uint32_t sgl_drawable_id;

static int
sgl_get_param(struct pipe_frontend_screen *fscreen, enum st_manager_param param)
{
   return 0;
}

struct sgl_display *
sgl_display_create(void)
{
   struct sgl_display *dpy = CALLOC_STRUCT(sgl_display);
   if (!dpy)
      return NULL;

   /* ir3 and the GLSL compiler build GLSL types */
   glsl_type_singleton_init_or_ref();

   driParseOptionInfo(&dpy->options_info, fd_driconf, ARRAY_SIZE(fd_driconf));
   driParseOptionInfo(&dpy->options, fd_driconf, ARRAY_SIZE(fd_driconf));
   struct pipe_screen_config config = {
      .options = &dpy->options,
      .options_info = &dpy->options_info,
   };

#ifdef __APPLE__
   /* the darwin backend talks to SweetGPU itself; fd_screen_create dup()s the fd */
   dpy->fd = open("/dev/null", O_RDWR);
#else
   dpy->fd = open("/dev/dri/renderD128", O_RDWR | O_CLOEXEC);
#endif
   dpy->fscreen.screen = dpy->fd >= 0 ? fd_screen_create(dpy->fd, &config, NULL) : NULL;
   if (!dpy->fscreen.screen) {
      fprintf(stderr, "sweetgl: no freedreno screen\n");
      if (dpy->fd >= 0)
         close(dpy->fd);
      driDestroyOptionCache(&dpy->options);
      driDestroyOptionInfo(&dpy->options_info);
      glsl_type_singleton_decref();
      FREE(dpy);
      return NULL;
   }
   dpy->fscreen.get_param = sgl_get_param;
   return dpy;
}

void
sgl_display_destroy(struct sgl_display *dpy)
{
   if (!dpy)
      return;
   st_screen_destroy(&dpy->fscreen);
   dpy->fscreen.screen->destroy(dpy->fscreen.screen);
   close(dpy->fd);
   driDestroyOptionCache(&dpy->options);
   driDestroyOptionInfo(&dpy->options_info);
   glsl_type_singleton_decref();
   FREE(dpy);
}

static void
sgl_fill_visual(struct st_visual *visual, enum pipe_format color_format, bool depth_stencil)
{
   memset(visual, 0, sizeof(*visual));
   /* single-buffered: GL renders to the front buffer, which the caller reads */
   visual->buffer_mask = ST_ATTACHMENT_FRONT_LEFT_MASK;
   visual->color_format = color_format;
   visual->depth_stencil_format = depth_stencil ? PIPE_FORMAT_Z24_UNORM_S8_UINT : PIPE_FORMAT_NONE;
   visual->accum_format = PIPE_FORMAT_NONE;
   if (depth_stencil)
      visual->buffer_mask |= ST_ATTACHMENT_DEPTH_STENCIL_MASK;
}

struct sgl_context *
sgl_context_create(struct sgl_display *dpy, int es_major, struct sgl_context *share)
{
   struct sgl_context *ctx = CALLOC_STRUCT(sgl_context);
   if (!ctx)
      return NULL;
   ctx->dpy = dpy;

   struct st_context_attribs attribs;
   memset(&attribs, 0, sizeof(attribs));
   attribs.profile = API_OPENGLES2;
   attribs.major = es_major >= 3 ? 3 : 2;
   /* 3.1: CoreAnimation's rectangle texture emulation needs glGetTexLevelParameteriv */
   attribs.minor = es_major >= 3 ? 1 : 0;
   /* the visual of the surfaces it will draw to */
   sgl_fill_visual(&attribs.visual, PIPE_FORMAT_R8G8B8A8_UNORM, true);

   enum st_context_error error;
   ctx->st = st_api_create_context(&dpy->fscreen, &attribs, &error, share ? share->st : NULL);
   if (!ctx->st) {
      fprintf(stderr, "sweetgl: st_api_create_context(ES %d) failed: %d\n", attribs.major, error);
      FREE(ctx);
      return NULL;
   }
   ctx->st->frontend_context = ctx;
   return ctx;
}

void
sgl_context_destroy(struct sgl_context *ctx)
{
   if (!ctx)
      return;
   if (st_api_get_current() == ctx->st)
      st_api_make_current(NULL, NULL, NULL);
   st_context_flush(ctx->st, 0, NULL, NULL, NULL);
   st_destroy_context(ctx->st);
   FREE(ctx);
}

static bool
sgl_flush_front(struct st_context *st, struct pipe_frontend_drawable *drawable,
                enum st_attachment_type statt)
{
   /* offscreen: nothing to present */
   return true;
}

/* st/mesa asks for the attachments it renders to; create them on first use */
static bool
sgl_validate(struct st_context *st, struct pipe_frontend_drawable *drawable,
             const enum st_attachment_type *statts, unsigned count,
             struct pipe_resource **out, struct pipe_resource **resolve)
{
   struct sgl_surface *surf = (struct sgl_surface *)drawable;
   struct pipe_screen *screen = surf->dpy->fscreen.screen;

   for (unsigned i = 0; i < count; i++) {
      enum st_attachment_type a = statts[i];
      if (!surf->textures[a]) {
         struct pipe_resource templ = {
            .target = PIPE_TEXTURE_2D,
            .width0 = surf->width,
            .height0 = surf->height,
            .depth0 = 1,
            .array_size = 1,
         };
         if (a == ST_ATTACHMENT_DEPTH_STENCIL) {
            templ.format = surf->visual.depth_stencil_format;
            templ.bind = PIPE_BIND_DEPTH_STENCIL;
         } else {
            templ.format = surf->visual.color_format;
            templ.bind = PIPE_BIND_RENDER_TARGET | PIPE_BIND_SAMPLER_VIEW;
         }
         if (templ.format == PIPE_FORMAT_NONE)
            return false;
         surf->textures[a] = screen->resource_create(screen, &templ);
         if (!surf->textures[a])
            return false;
      }
      pipe_resource_reference(&out[i], surf->textures[a]);
   }
   return true;
}

static struct sgl_surface *
sgl_surface_alloc(struct sgl_display *dpy, unsigned width, unsigned height,
                  enum pipe_format color_format, bool depth_stencil)
{
   struct sgl_surface *surf = CALLOC_STRUCT(sgl_surface);
   if (!surf)
      return NULL;
   surf->dpy = dpy;
   surf->width = width;
   surf->height = height;
   sgl_fill_visual(&surf->visual, color_format, depth_stencil);

   surf->base.visual = &surf->visual;
   surf->base.flush_front = sgl_flush_front;
   surf->base.validate = sgl_validate;
   surf->base.fscreen = &dpy->fscreen;
   p_atomic_set(&surf->base.stamp, 1);
   surf->base.ID = p_atomic_inc_return(&sgl_drawable_id);
   return surf;
}

struct sgl_surface *
sgl_surface_create(struct sgl_display *dpy, unsigned width, unsigned height, bool depth_stencil)
{
   return sgl_surface_alloc(dpy, width, height, PIPE_FORMAT_R8G8B8A8_UNORM, depth_stencil);
}

static enum pipe_format
sgl_iosurface_format(uint32_t pixel_format)
{
   switch (pixel_format) {
   case SGL_IOSURFACE_BGRA:
      return PIPE_FORMAT_B8G8R8A8_UNORM;
   case SGL_IOSURFACE_RGBA:
      return PIPE_FORMAT_R8G8B8A8_UNORM;
   default:
      return PIPE_FORMAT_NONE;
   }
}

/* a texture around an IOSurface: on Darwin an FD handle carries the IOSurface id */
static struct pipe_resource *
sgl_import_iosurface(struct sgl_display *dpy, uint32_t iosurface_id, unsigned width,
                     unsigned height, unsigned bytes_per_row, enum pipe_format format,
                     unsigned bind)
{
   struct pipe_screen *screen = dpy->fscreen.screen;
   struct pipe_resource templ = {
      .target = PIPE_TEXTURE_2D,
      .format = format,
      .width0 = width,
      .height0 = height,
      .depth0 = 1,
      .array_size = 1,
      .bind = bind | PIPE_BIND_SHARED,
   };
   struct winsys_handle whandle = {
      .type = WINSYS_HANDLE_TYPE_FD,
      .handle = iosurface_id,
      .stride = bytes_per_row,
      .modifier = DRM_FORMAT_MOD_LINEAR,
   };
   struct pipe_resource *res =
      screen->resource_from_handle(screen, &templ, &whandle, PIPE_HANDLE_USAGE_FRAMEBUFFER_WRITE);
   if (!res)
      fprintf(stderr, "sweetgl: IOSurface %u (%ux%u, %u bytes per row, %s) not usable by the GPU\n",
              iosurface_id, width, height, bytes_per_row, util_format_short_name(format));
   return res;
}

struct sgl_surface *
sgl_surface_create_iosurface(struct sgl_display *dpy, uint32_t iosurface_id, unsigned width,
                             unsigned height, unsigned bytes_per_row, uint32_t pixel_format,
                             bool depth_stencil)
{
   enum pipe_format format = sgl_iosurface_format(pixel_format);
   if (format == PIPE_FORMAT_NONE) {
      fprintf(stderr, "sweetgl: IOSurface pixel format 0x%08x not supported\n", pixel_format);
      return NULL;
   }
   struct pipe_resource *color = sgl_import_iosurface(dpy, iosurface_id, width, height,
                                                      bytes_per_row, format,
                                                      PIPE_BIND_RENDER_TARGET |
                                                      PIPE_BIND_SAMPLER_VIEW);
   if (!color)
      return NULL;
   struct sgl_surface *surf = sgl_surface_alloc(dpy, width, height, format, depth_stencil);
   if (!surf) {
      pipe_resource_reference(&color, NULL);
      return NULL;
   }
   /* validate() hands this out as the front buffer; depth/stencil is still ours */
   surf->textures[ST_ATTACHMENT_FRONT_LEFT] = color;
   return surf;
}

static enum pipe_format
sgl_pipe_format(enum sgl_format format)
{
   switch (format) {
   case SGL_FMT_BGRA8:
      return PIPE_FORMAT_B8G8R8A8_UNORM;
   case SGL_FMT_RGBA8:
      return PIPE_FORMAT_R8G8B8A8_UNORM;
   case SGL_FMT_R8:
      return PIPE_FORMAT_R8_UNORM;
   case SGL_FMT_RG8:
      return PIPE_FORMAT_R8G8_UNORM;
   case SGL_FMT_RGBA16F:
      return PIPE_FORMAT_R16G16B16A16_FLOAT;
   default:
      return PIPE_FORMAT_NONE;
   }
}

/*
 * One resource per imported IOSurface (and geometry), least recently used out.
 * A dropped entry only drops our reference: textures made from it keep it.
 */
#define SGL_IMPORT_CACHE 32
static struct {
   uint32_t id, width, height, pitch;
   enum pipe_format format;
   struct pipe_resource *res;
   uint64_t used;
} sgl_import_cache[SGL_IMPORT_CACHE];
static uint64_t sgl_import_clock;
static simple_mtx_t sgl_import_lock = SIMPLE_MTX_INITIALIZER;

/* a new reference to the shared resource of the surface, imported if needed */
static struct pipe_resource *
sgl_import_cached(struct sgl_display *dpy, uint32_t id, unsigned width, unsigned height,
                  unsigned pitch, enum pipe_format format)
{
   struct pipe_resource *res = NULL;
   simple_mtx_lock(&sgl_import_lock);
   for (unsigned i = 0; i < SGL_IMPORT_CACHE && !res; i++) {
      if (sgl_import_cache[i].res && sgl_import_cache[i].id == id &&
          sgl_import_cache[i].width == width && sgl_import_cache[i].height == height &&
          sgl_import_cache[i].pitch == pitch && sgl_import_cache[i].format == format) {
         sgl_import_cache[i].used = ++sgl_import_clock;
         pipe_resource_reference(&res, sgl_import_cache[i].res);
      }
   }
   simple_mtx_unlock(&sgl_import_lock);
   if (res)
      return res;

   res = sgl_import_iosurface(dpy, id, width, height, pitch, format,
                              PIPE_BIND_RENDER_TARGET | PIPE_BIND_SAMPLER_VIEW);
   if (!res)
      return NULL;
   simple_mtx_lock(&sgl_import_lock);
   unsigned victim = 0;
   for (unsigned i = 0; i < SGL_IMPORT_CACHE; i++) {
      if (!sgl_import_cache[i].res) {
         victim = i;
         break;
      }
      if (sgl_import_cache[i].used < sgl_import_cache[victim].used)
         victim = i;
   }
   pipe_resource_reference(&sgl_import_cache[victim].res, res);
   sgl_import_cache[victim].id = id;
   sgl_import_cache[victim].width = width;
   sgl_import_cache[victim].height = height;
   sgl_import_cache[victim].pitch = pitch;
   sgl_import_cache[victim].format = format;
   sgl_import_cache[victim].used = ++sgl_import_clock;
   simple_mtx_unlock(&sgl_import_lock);
   return res;
}

bool
sgl_tex_image_iosurface_fmt(struct sgl_context *ctx, unsigned target, uint32_t iosurface_id,
                            unsigned width, unsigned height, unsigned bytes_per_row,
                            enum sgl_format format)
{
   enum pipe_format pf = sgl_pipe_format(format);
   if (pf == PIPE_FORMAT_NONE)
      return false;
   struct pipe_resource *tex =
      sgl_import_cached(ctx->dpy, iosurface_id, width, height, bytes_per_row, pf);
   if (!tex)
      return false;
   st_context_teximage(ctx->st, target, 0, pf, tex, false);
   pipe_resource_reference(&tex, NULL);
   return true;
}

bool
sgl_tex_image_iosurface(struct sgl_context *ctx, unsigned target, uint32_t iosurface_id,
                        unsigned width, unsigned height, unsigned bytes_per_row,
                        uint32_t pixel_format)
{
   enum sgl_format format = pixel_format == SGL_IOSURFACE_BGRA   ? SGL_FMT_BGRA8
                            : pixel_format == SGL_IOSURFACE_RGBA ? SGL_FMT_RGBA8
                                                                 : SGL_FMT_NONE;
   if (format == SGL_FMT_NONE) {
      fprintf(stderr, "sweetgl: IOSurface pixel format 0x%08x not supported\n", pixel_format);
      return false;
   }
   return sgl_tex_image_iosurface_fmt(ctx, target, iosurface_id, width, height, bytes_per_row,
                                      format);
}

void _mesa_TextureBarrierNV(void);

void
sgl_texture_barrier(void)
{
   _mesa_TextureBarrierNV();
}

void
sgl_surface_destroy(struct sgl_surface *surf)
{
   if (!surf)
      return;
   st_api_destroy_drawable(&surf->base);
   for (unsigned i = 0; i < ST_ATTACHMENT_COUNT; i++)
      pipe_resource_reference(&surf->textures[i], NULL);
   FREE(surf);
}

bool
sgl_make_current(struct sgl_context *ctx, struct sgl_surface *surf)
{
   return st_api_make_current(ctx ? ctx->st : NULL, surf ? &surf->base : NULL,
                              surf ? &surf->base : NULL);
}
