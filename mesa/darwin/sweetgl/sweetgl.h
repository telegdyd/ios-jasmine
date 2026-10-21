/*
 * Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 *
 * sweetgl: a small GL ES frontend for ios-jasmine. Mesa's GL (st/mesa) on the
 * freedreno screen, without EGL or DRI: a display owns the GPU screen, a
 * context is a GL ES 2/3 context, a surface is a framebuffer (color and
 * optional depth/stencil) the context renders into, offscreen or an IOSurface.
 * Modelled on Haiku's hgl frontend; the EAGL side (OpenGLES.framework) is
 * meant to sit on top.
 *
 * IOSurfaces are shared with the GPU without copies (SweetGPU maps the
 * surface's own memory, kernel j0032). Rows are stored top row first, as
 * CoreAnimation and the display expect; on the Adreno 512 the bytes per row
 * must be a multiple of 256 (64 pixels of 4 bytes).
 */

#ifndef SWEETGL_H
#define SWEETGL_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

struct sgl_display;
struct sgl_context;
struct sgl_surface;

/* the GPU screen (freedreno on SweetGPU); NULL if the GPU is not up */
struct sgl_display *sgl_display_create(void);
void sgl_display_destroy(struct sgl_display *dpy);

/* a GL ES context: es_major 2 or 3 (3 gives the highest 3.x the driver has) */
struct sgl_context *sgl_context_create(struct sgl_display *dpy, int es_major,
                                       struct sgl_context *share);
void sgl_context_destroy(struct sgl_context *ctx);

/* an offscreen RGBA8 framebuffer, with a 24/8 depth/stencil buffer if asked */
struct sgl_surface *sgl_surface_create(struct sgl_display *dpy, unsigned width,
                                       unsigned height, bool depth_stencil);
void sgl_surface_destroy(struct sgl_surface *surf);

/* IOSurface pixel formats (IOSurfaceGetPixelFormat) that sweetgl takes */
#define SGL_IOSURFACE_BGRA 0x42475241 /* 'BGRA', what CoreAnimation renders */
#define SGL_IOSURFACE_RGBA 0x52474241 /* 'RGBA' */

/* a surface whose color buffer is an IOSurface: the context renders into its memory */
struct sgl_surface *sgl_surface_create_iosurface(struct sgl_display *dpy, uint32_t iosurface_id,
                                                 unsigned width, unsigned height,
                                                 unsigned bytes_per_row, uint32_t pixel_format,
                                                 bool depth_stencil);

/*
 * The texture bound to target (GL_TEXTURE_2D) of ctx, which must be current,
 * samples an IOSurface (EAGL's texImageIOSurface:); level 0 only.
 */
bool sgl_tex_image_iosurface(struct sgl_context *ctx, unsigned target, uint32_t iosurface_id,
                             unsigned width, unsigned height, unsigned bytes_per_row,
                             uint32_t pixel_format);

/* bind ctx and surf to the calling thread (NULL, NULL unbinds) */
bool sgl_make_current(struct sgl_context *ctx, struct sgl_surface *surf);

#ifdef __cplusplus
}
#endif

#endif /* SWEETGL_H */
