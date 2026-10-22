/*
 * Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 *
 * sweetca_test: CoreAnimation's own GLES renderer on the Adreno 512 (libsweetca).
 *
 * +[CARenderer rendererWithEAGLContext:options:] builds the same GLESContext and
 * OGL::Renderer as backboardd's. A small layer tree (a solid background, an
 * image, a rounded masked layer, partial opacity, a sublayer transform, a text
 * layer) is rendered into a BGRA IOSurface through it, and compared per pixel
 * with the same tree drawn by CoreAnimation on the CPU (-renderInContext:).
 * The GPU result is read straight from the surface's memory, as the display would.
 *
 * Needs libsweetca (linked in: its constructor replaces EAGLContext's methods).
 * SWEETCA_TRACE=1 in the environment adds GL error checks to the library's log.
 */

#import <Foundation/Foundation.h>
#import <QuartzCore/QuartzCore.h>
#import <CoreGraphics/CoreGraphics.h>
#import <IOSurface/IOSurfaceRef.h>
#import <OpenGLES/EAGL.h>
#import <objc/message.h>
#import <objc/runtime.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern int sweetca_installed(void);
extern void sweetca_set_trace(int level);
extern void sweetca_set_flip(int mode);

#define W 256
#define H 256
#define TOL 8 /* per channel, GPU against CPU renderer */

#define GL_TEXTURE_2D 0x0DE1
#define GL_RGBA 0x1908
#define GL_BGRA 0x80E1
#define GL_UNSIGNED_BYTE 0x1401

static int failures;

#define CHECK(cond, ...)                                                         \
   do {                                                                          \
      if (cond) {                                                                \
         printf("ok: " __VA_ARGS__);                                             \
         printf("\n");                                                           \
      } else {                                                                   \
         printf("FAIL: " __VA_ARGS__);                                           \
         printf("\n");                                                           \
         failures++;                                                             \
      }                                                                          \
      fflush(stdout);                                                            \
   } while (0)

static CGImageRef
make_image(void)
{
   const int n = 64;
   CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
   CGContextRef g = CGBitmapContextCreate(NULL, n, n, 8, n * 4, cs,
                                          kCGImageAlphaPremultipliedFirst | kCGBitmapByteOrder32Little);
   CGColorSpaceRelease(cs);
   /* four quadrants, red green / blue yellow, and a white diagonal */
   CGContextSetRGBFillColor(g, 1, 0, 0, 1);
   CGContextFillRect(g, CGRectMake(0, n / 2, n / 2, n / 2));
   CGContextSetRGBFillColor(g, 0, 1, 0, 1);
   CGContextFillRect(g, CGRectMake(n / 2, n / 2, n / 2, n / 2));
   CGContextSetRGBFillColor(g, 0, 0, 1, 1);
   CGContextFillRect(g, CGRectMake(0, 0, n / 2, n / 2));
   CGContextSetRGBFillColor(g, 1, 1, 0, 1);
   CGContextFillRect(g, CGRectMake(n / 2, 0, n / 2, n / 2));
   CGContextSetRGBStrokeColor(g, 1, 1, 1, 1);
   CGContextSetLineWidth(g, 4);
   CGContextMoveToPoint(g, 0, 0);
   CGContextAddLineToPoint(g, n, n);
   CGContextStrokePath(g);
   CGImageRef img = CGBitmapContextCreateImage(g);
   CGContextRelease(g);
   return img;
}

static CALayer *
make_tree(void)
{
   CALayer *root = [CALayer layer];
   root.frame = CGRectMake(0, 0, W, H);
   CGColorRef bg = CGColorCreateGenericRGB(0.10, 0.20, 0.40, 1);
   root.backgroundColor = bg;
   CGColorRelease(bg);

   /* an image as contents */
   CALayer *image = [CALayer layer];
   image.frame = CGRectMake(16, 16, 96, 96);
   CGImageRef img = make_image();
   image.contents = (__bridge id)img;
   CGImageRelease(img);
   [root addSublayer:image];

   /* corner radius and masksToBounds: the red child sticks out of the rounded corner */
   CALayer *round = [CALayer layer];
   round.frame = CGRectMake(144, 16, 96, 96);
   CGColorRef orange = CGColorCreateGenericRGB(1.0, 0.6, 0.1, 1);
   round.backgroundColor = orange;
   CGColorRelease(orange);
   round.cornerRadius = 32;
   round.masksToBounds = YES;
   CALayer *child = [CALayer layer];
   child.frame = CGRectMake(0, 0, 56, 56);
   CGColorRef red = CGColorCreateGenericRGB(0.9, 0.1, 0.1, 1);
   child.backgroundColor = red;
   CGColorRelease(red);
   [round addSublayer:child];
   [root addSublayer:round];

   /* partial opacity over the background and the neighbour */
   CALayer *fade = [CALayer layer];
   fade.frame = CGRectMake(16, 144, 96, 96);
   CGColorRef white = CGColorCreateGenericRGB(1, 1, 1, 1);
   fade.backgroundColor = white;
   CGColorRelease(white);
   fade.opacity = 0.5;
   [root addSublayer:fade];

   /* a sublayer transform: a rotated green square */
   CALayer *xf = [CALayer layer];
   xf.frame = CGRectMake(144, 144, 96, 96);
   xf.sublayerTransform = CATransform3DMakeRotation(M_PI / 6, 0, 0, 1);
   CALayer *sq = [CALayer layer];
   sq.bounds = CGRectMake(0, 0, 40, 40);
   sq.position = CGPointMake(48, 48);
   CGColorRef green = CGColorCreateGenericRGB(0.1, 0.8, 0.2, 1);
   sq.backgroundColor = green;
   CGColorRelease(green);
   [xf addSublayer:sq];
   [root addSublayer:xf];

   /* text */
   CATextLayer *text = [CATextLayer layer];
   text.frame = CGRectMake(56, 116, 150, 24);
   text.string = @"Hello CA";
   text.fontSize = 20;
   CGColorRef tc = CGColorCreateGenericRGB(1, 1, 1, 1);
   text.foregroundColor = tc;
   CGColorRelease(tc);
   text.contentsScale = 1;
   [root addSublayer:text];
   return root;
}

typedef struct {
   unsigned diff;
   unsigned region[5];
} result;

static const struct {
   const char *name;
   int x0, y0, x1, y1;
} regions[5] = {
   {"image", 16, 16, 112, 112},
   {"rounded", 144, 16, 240, 112},
   {"opacity", 16, 144, 112, 240},
   {"rotated", 144, 144, 240, 240},
   {"text", 56, 116, 206, 140},
};

/* BGRA rows top first on both sides; flip: compare against the vertically flipped reference */
static result
compare(const uint8_t *gpu, size_t gpu_pitch, const uint8_t *ref, size_t ref_pitch, bool flip)
{
   result r = {0};
   for (int y = 0; y < H; y++) {
      const uint8_t *a = gpu + (size_t)y * gpu_pitch;
      const uint8_t *b = ref + (size_t)(flip ? H - 1 - y : y) * ref_pitch;
      for (int x = 0; x < W; x++) {
         int d = 0;
         for (int c = 0; c < 3; c++) {
            int e = abs((int)a[x * 4 + c] - (int)b[x * 4 + c]);
            d = e > d ? e : d;
         }
         if (d > TOL) {
            r.diff++;
            for (int i = 0; i < 5; i++) {
               if (x >= regions[i].x0 && x < regions[i].x1 && y >= regions[i].y0 && y < regions[i].y1)
                  r.region[i]++;
            }
         }
      }
   }
   return r;
}

static void
sample(const char *what, const uint8_t *p, size_t pitch, int x, int y)
{
   const uint8_t *q = p + (size_t)y * pitch + (size_t)x * 4;
   printf("  %s (%d,%d): b=%02x g=%02x r=%02x a=%02x\n", what, x, y, q[0], q[1], q[2], q[3]);
}

static void
samples(const char *name, const uint8_t *p, size_t pitch)
{
   printf(" %s:\n", name);
   sample("background", p, pitch, 4, 4);
   sample("image, red quadrant", p, pitch, 40, 36);
   sample("image, blue quadrant", p, pitch, 40, 92);
   sample("rounded, orange", p, pitch, 200, 70);
   sample("rounded, red child", p, pitch, 156, 28);
   sample("opacity", p, pitch, 40, 168);
   sample("rotated, green", p, pitch, 192, 192);
   sample("text area", p, pitch, 100, 128);
}

int
main(void)
{
   @autoreleasepool {
      setvbuf(stdout, NULL, _IOLBF, 0);
      if (getenv("SWEETCA_TRACE"))
         sweetca_set_trace(atoi(getenv("SWEETCA_TRACE")));
      else
         sweetca_set_trace(1);
      CHECK(sweetca_installed(), "libsweetca replaced the EAGLContext methods");

      EAGLContext *ctx = [[EAGLContext alloc] initWithAPI:kEAGLRenderingAPIOpenGLES3];
      CHECK(ctx != nil, "[[EAGLContext alloc] initWithAPI:3] gives a context");
      if (!ctx) {
         printf("FAIL: no context\n");
         return 1;
      }
      CHECK([ctx API] == kEAGLRenderingAPIOpenGLES3, "-API is 3");
      void **macro = ((void **(*)(id, SEL))objc_msgSend)(ctx, sel_registerName("getMacroContextPrivate"));
      CHECK(macro != NULL && macro[0] != NULL, "getMacroContextPrivate gives {rctx, dispatch}");
      if (!macro)
         return 1;
      void *rctx = macro[0];
      void **disp = macro + 1;
      CHECK([EAGLContext setCurrentContext:ctx], "+setCurrentContext:");
      CHECK([EAGLContext currentContext] == ctx, "+currentContext");

      /* the destination: a BGRA IOSurface with rows CA and the GPU both like */
      NSDictionary *props = @{
         (__bridge NSString *)kIOSurfaceWidth : @(W),
         (__bridge NSString *)kIOSurfaceHeight : @(H),
         (__bridge NSString *)kIOSurfaceBytesPerElement : @4,
         (__bridge NSString *)kIOSurfaceBytesPerRow : @(W * 4),
         (__bridge NSString *)kIOSurfacePixelFormat : @(0x42475241u),
      };
      IOSurfaceRef surf = IOSurfaceCreate((__bridge CFDictionaryRef)props);
      CHECK(surf != NULL, "IOSurface %dx%d BGRA created (id %u, pitch %zu)", W, H,
            surf ? IOSurfaceGetID(surf) : 0, surf ? IOSurfaceGetBytesPerRow(surf) : (size_t)0);
      if (!surf)
         return 1;
      size_t pitch = IOSurfaceGetBytesPerRow(surf);

      /* the texture CA renders into */
      unsigned tex = 0;
      ((void (*)(void *, int, unsigned *))disp[98])(rctx, 1, &tex); /* glGenTextures */
      ((void (*)(void *, unsigned, unsigned))disp[5])(rctx, GL_TEXTURE_2D, tex); /* glBindTexture */
      BOOL bound = ((BOOL(*)(id, SEL, IOSurfaceRef, NSUInteger, NSUInteger, uint32_t, uint32_t, NSUInteger,
                             NSUInteger, uint32_t, BOOL))objc_msgSend)(
         ctx, sel_registerName("texImageIOSurface:target:internalFormat:width:height:format:type:plane:invert:"),
         surf, GL_TEXTURE_2D, GL_RGBA, W, H, GL_BGRA, GL_UNSIGNED_BYTE, 0, YES); /* rows as they are: it is a render target */
      CHECK(bound && tex != 0, "texImageIOSurface: binds the surface to texture %u", tex);

      /* CA draws into the framebuffer bound on the context: ours has the surface's texture as its color */
      unsigned fbo = 0;
      ((void (*)(void *, int, unsigned *))disp[674])(rctx, 1, &fbo);                      /* glGenFramebuffers */
      ((void (*)(void *, unsigned, unsigned))disp[672])(rctx, 0x8D40, fbo);               /* glBindFramebuffer */
      ((void (*)(void *, unsigned, unsigned, unsigned, unsigned, int))disp[677])(rctx, 0x8D40, 0x8CE0, GL_TEXTURE_2D,
                                                                                  tex, 0); /* glFramebufferTexture2D */
      ((void (*)(void *, int, int, int, int))disp[335])(rctx, 0, 0, W, H); /* glViewport: an app sets it, EAGL has no drawable here */

      result best = {~0u};
      unsigned best_mode = 0;
      bool any = false;
      uint8_t *out = malloc((size_t)H * pitch);
      Class CAR = NSClassFromString(@"CARenderer");
      CHECK(CAR != Nil, "CARenderer class");
      /* modes of libsweetca's handling of IOSurface textures (sweetca_set_flip); a fresh layer tree each,
       * so CA uploads its images again */
      for (int mode = 4; mode < 5; mode++) {
         sweetca_set_flip(mode);
         /* the layer tree, drawn by CA on the CPU as the reference */
         CALayer *root = make_tree();
         [CATransaction flush];
         CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
         CGContextRef g = CGBitmapContextCreate(NULL, W, H, 8, W * 4, cs,
                                                kCGImageAlphaPremultipliedFirst | kCGBitmapByteOrder32Little);
         CGColorSpaceRelease(cs);
         CGContextTranslateCTM(g, 0, H);
         CGContextScaleCTM(g, 1, -1);
         [root renderInContext:g];
         const uint8_t *ref = CGBitmapContextGetData(g);
         size_t ref_pitch = CGBitmapContextGetBytesPerRow(g);
         if (mode == 0)
            samples("CPU reference", ref, ref_pitch);

         id renderer = ((id(*)(id, SEL, id, id))objc_msgSend)((id)CAR, sel_registerName("rendererWithEAGLContext:options:"),
                                                             ctx, nil);
         CHECK(renderer != nil, "+rendererWithEAGLContext:options: gives a renderer (CA's GLES renderer)");
         if (!renderer)
            return 1;
         ((void (*)(id, SEL, id))objc_msgSend)(renderer, sel_registerName("setLayer:"), root);
         ((void (*)(id, SEL, CGRect))objc_msgSend)(renderer, sel_registerName("setBounds:"), CGRectMake(0, 0, W, H));
         [CATransaction flush];

         /* junk first, so pixels the GPU did not write stand out */
         IOSurfaceLock(surf, 0, NULL);
         memset(IOSurfaceGetBaseAddress(surf), 0x5a, (size_t)H * pitch);
         IOSurfaceUnlock(surf, 0, NULL);

         double t0 = CACurrentMediaTime();
         ((void (*)(id, SEL, CFTimeInterval, void *))objc_msgSend)(renderer, sel_registerName("beginFrameAtTime:timeStamp:"),
                                                                   t0, NULL);
         ((void (*)(id, SEL, CGRect))objc_msgSend)(renderer, sel_registerName("addUpdateRect:"), CGRectMake(0, 0, W, H));
         ((void (*)(id, SEL))objc_msgSend)(renderer, sel_registerName("render"));
         ((void (*)(id, SEL))objc_msgSend)(renderer, sel_registerName("endFrame"));
         double t1 = CACurrentMediaTime();
         ((void (*)(void *))disp[89])(rctx); /* glFinish: the display waits for nobody */

         IOSurfaceLock(surf, kIOSurfaceLockReadOnly, NULL);
         memcpy(out, IOSurfaceGetBaseAddress(surf), (size_t)H * pitch);
         IOSurfaceUnlock(surf, kIOSurfaceLockReadOnly, NULL);
         printf("render, mode %d took %.0f ms\n", mode, (t1 - t0) * 1000);
         char name[64];
         snprintf(name, sizeof(name), "GPU, mode %d", mode);
         samples(name, out, pitch);
         result r = compare(out, pitch, ref, ref_pitch, false);
         printf(" mode %d: %u of %d pixels differ by more than %d (image %u, rounded %u, opacity %u, "
                "rotated %u, text %u)\n",
                mode, r.diff, W * H, TOL, r.region[0], r.region[1], r.region[2], r.region[3], r.region[4]);
         /* where they differ: 16x16 blocks, '.' none, else the count in tens (9 = 90 or more) */
         printf(" difference map:\n");
         for (int by = 0; by < H / 16; by++) {
            char row[H / 16 + 1];
            for (int bx = 0; bx < W / 16; bx++) {
               int n = 0;
               for (int y = 0; y < 16; y++)
                  for (int x = 0; x < 16; x++) {
                     const uint8_t *a = out + (size_t)(by * 16 + y) * pitch + (bx * 16 + x) * 4;
                     const uint8_t *b = ref + (size_t)(by * 16 + y) * ref_pitch + (bx * 16 + x) * 4;
                     int d = 0;
                     for (int c = 0; c < 3; c++)
                        d = abs(a[c] - b[c]) > d ? abs(a[c] - b[c]) : d;
                     n += d > TOL;
                  }
               row[bx] = n == 0 ? '.' : (char)('0' + (n / 10 > 9 ? 9 : n / 10));
            }
            row[W / 16] = 0;
            printf("  %s\n", row);
         }
         /* the rounded layer, sampled every 4 pixels: B black, O orange, R red, b background, ? other; GPU left, CPU right */
         printf(" rounded layer, GPU | CPU:\n");
         for (int y = 16; y < 112; y += 4) {
            char a[25], b[25];
            for (int x = 144; x < 240; x += 4) {
               for (int w = 0; w < 2; w++) {
                  const uint8_t *q = (w ? ref + (size_t)y * ref_pitch : out + (size_t)y * pitch) + (size_t)x * 4;
                  int bl = q[0], gr = q[1], rd = q[2];
                  char ch = rd < 20 && gr < 20 && bl < 20 ? 'B' : (rd > 200 && gr > 120 && bl < 80) ? 'O'
                            : (rd > 180 && gr < 90 && bl < 90) ? 'R' : (rd < 60 && bl > 90 && bl < 150) ? 'b' : '?';
                  (w ? b : a)[(x - 144) / 4] = ch;
               }
            }
            a[24] = b[24] = 0;
            printf("  %s | %s\n", a, b);
         }
         if (r.diff < best.diff) {
            best = r;
            best_mode = mode;
            any = true;
         }
         CGContextRelease(g);
      }
      free(out);
      printf("best: mode %u, %u pixels differ\n", best_mode, best.diff);
      CHECK(any && best.diff <= (unsigned)(W * H) / 50, "GPU render matches the CPU reference (at most 2%% of pixels differ)");
      CFRelease(surf);
   }
   if (failures) {
      printf("FAIL: %d checks failed\n", failures);
      return 1;
   }
   printf("PASS: CoreAnimation's GLES renderer drew the layer tree on the Adreno 512\n");
   return 0;
}
