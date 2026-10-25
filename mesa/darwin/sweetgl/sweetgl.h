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

/* what an IOSurface's bytes are, for textures made from one (EAGL's texImageIOSurface:) */
enum sgl_format {
   SGL_FMT_NONE,
   SGL_FMT_BGRA8,
   SGL_FMT_RGBA8,
   SGL_FMT_R8,
   SGL_FMT_RG8,
   SGL_FMT_RGBA16F,
};

/*
 * Like sgl_tex_image_iosurface, with the format given directly. One GPU
 * resource is kept per (surface, size, pitch, format) and shared by every
 * texture and render target made from it, so work that renders into a surface
 * and work that samples it are ordered by Mesa (two resources over the same
 * memory would not be). offset: where the pixels start in the surface's GPU
 * buffer (client memory that begins inside its first page). Fails if the GPU
 * cannot use the surface in place.
 */
bool sgl_tex_image_iosurface_fmt(struct sgl_context *ctx, unsigned target, uint32_t iosurface_id,
                                 unsigned width, unsigned height, unsigned bytes_per_row,
                                 unsigned offset, enum sgl_format format);

/* GL_NV_texture_barrier on the current context: later draws see earlier draws' pixels */
void sgl_texture_barrier(void);

/* Units whose 2D binding is sampled by a current graphics program. Uses Mesa's
 * linked-program state, including sampler arrays and glUniform changes. */
uint32_t sgl_sampled_2d_units(struct sgl_context *ctx);

/*
 * With Mesa's threaded context (the default; GALLIUM_THREAD=0 turns it off),
 * a driver thread does freedreno's draw, batch and submit work. sgl_kick sends
 * what ctx has queued to the GPU without waiting, from that thread; false
 * without the threaded context. sgl_follow_thread gives the driver thread the
 * calling thread's scheduling policy and priority.
 */
bool sgl_kick(struct sgl_context *ctx);
bool sgl_pipeline_available(struct sgl_context *ctx);
int sgl_flush_submit(struct sgl_context *ctx);
bool sgl_tickets_available(struct sgl_context *ctx);
int sgl_ticket_write(struct sgl_context *ctx, uint32_t surface);
int sgl_ticket_flush(struct sgl_context *ctx); /* ordered callback, no drain wait */
int sgl_ticket_finish(struct sgl_context *ctx); /* resolve own writes before CPU access */
int sgl_ticket_error(struct sgl_context *ctx);
void sgl_follow_thread(struct sgl_context *ctx);

/* bind ctx and surf to the calling thread (NULL, NULL unbinds) */
bool sgl_make_current(struct sgl_context *ctx, struct sgl_surface *surf);
/* Optional FIFO marker after a CA flush; does not submit or wait. */
void sgl_trace_frame_end(struct sgl_context *ctx, unsigned frame);

#ifdef __cplusplus
}
#endif

#endif /* SWEETGL_H */
