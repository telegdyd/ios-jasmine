/*
 * Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 *
 * sweet_shot: what the render server shows. Asks backboardd to render the
 * display into an IOSurface of ours (CARenderServerRenderDisplay, the call
 * screenshot tools use), prints a coarse luminance map and a few statistics,
 * and writes the picture at half size as "SHOT w h\n" + BGRA rows to OUT.
 *   sweet_shot [OUT [W H [DISPLAY]]]   defaults: /usr/local/bin/sweet_shot.raw 1125 2436 LCD
 * With the GPU renderer in backboardd this goes through the same path as a
 * frame: our surface is bound with attachImage: and drawn into by the GPU.
 */
#import <Foundation/Foundation.h>
#include <CoreFoundation/CoreFoundation.h>
#include <IOSurface/IOSurfaceRef.h>
#include <dlfcn.h>
#include <mach/mach.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef void (*render_display_fn)(mach_port_t, CFStringRef, IOSurfaceRef, int, int);

static IOSurfaceRef
make_surface(int w, int h)
{
   int bpe = 4, fmt = 'BGRA';
   CFNumberRef nw = CFNumberCreate(NULL, kCFNumberIntType, &w);
   CFNumberRef nh = CFNumberCreate(NULL, kCFNumberIntType, &h);
   CFNumberRef nb = CFNumberCreate(NULL, kCFNumberIntType, &bpe);
   CFNumberRef nf = CFNumberCreate(NULL, kCFNumberIntType, &fmt);
   const void *k[] = {kIOSurfaceWidth, kIOSurfaceHeight, kIOSurfaceBytesPerElement, kIOSurfacePixelFormat};
   const void *v[] = {nw, nh, nb, nf};
   CFDictionaryRef d = CFDictionaryCreate(NULL, k, v, 4, &kCFTypeDictionaryKeyCallBacks,
                                          &kCFTypeDictionaryValueCallBacks);
   IOSurfaceRef s = IOSurfaceCreate(d);
   CFRelease(d);
   CFRelease(nw);
   CFRelease(nh);
   CFRelease(nb);
   CFRelease(nf);
   return s;
}

int
main(int argc, char **argv)
{
   const char *out = argc > 1 ? argv[1] : "/usr/local/bin/sweet_shot.raw";
   int w = argc > 3 ? atoi(argv[2]) : 1125, h = argc > 3 ? atoi(argv[3]) : 2436;
   const char *name = argc > 4 ? argv[4] : "LCD";
   void *qc = dlopen("/System/Library/Frameworks/QuartzCore.framework/QuartzCore", RTLD_NOW);
   render_display_fn render = qc ? (render_display_fn)dlsym(qc, "CARenderServerRenderDisplay") : NULL;
   if (!render) {
      printf("FAIL: no CARenderServerRenderDisplay (%s)\n", dlerror());
      return 1;
   }
   IOSurfaceRef s = make_surface(w, h);
   if (!s) {
      printf("FAIL: IOSurfaceCreate %dx%d\n", w, h);
      return 1;
   }
   /* a marker colour, so "nothing was drawn" is told apart from black */
   IOSurfaceLock(s, 0, NULL);
   size_t pitch = IOSurfaceGetBytesPerRow(s);
   uint8_t *base = IOSurfaceGetBaseAddress(s);
   for (int y = 0; y < h; y++) {
      uint32_t *row = (uint32_t *)(base + y * pitch);
      for (int x = 0; x < w; x++)
         row[x] = 0xff00ff00; /* BGRA bytes 00 ff 00 ff: opaque green */
   }
   IOSurfaceUnlock(s, 0, NULL);

   CFStringRef disp = CFStringCreateWithCString(NULL, name, kCFStringEncodingUTF8);
   struct timespec t0, t1;
   clock_gettime(CLOCK_MONOTONIC, &t0);
   render(0, disp, s, 0, 0);
   clock_gettime(CLOCK_MONOTONIC, &t1);
   CFRelease(disp);
   double ms = (t1.tv_sec - t0.tv_sec) * 1e3 + (t1.tv_nsec - t0.tv_nsec) / 1e6;

   IOSurfaceLock(s, kIOSurfaceLockReadOnly, NULL);
   base = IOSurfaceGetBaseAddress(s);
   size_t black = 0, marker = 0, n = (size_t)w * h;
   double sum[3] = {0, 0, 0};
   for (int y = 0; y < h; y++) {
      const uint8_t *row = base + y * pitch;
      for (int x = 0; x < w; x++) {
         const uint8_t *p = row + x * 4;
         if (p[0] == 0 && p[1] == 0xff && p[2] == 0 && p[3] == 0xff)
            marker++;
         else if (p[0] < 8 && p[1] < 8 && p[2] < 8)
            black++;
         sum[0] += p[2];
         sum[1] += p[1];
         sum[2] += p[0];
      }
   }
   printf("sweet_shot: %s %dx%d pitch %zu, render %.1f ms, mean rgb %.0f %.0f %.0f, black %.1f%%, untouched %.1f%%\n",
          name, w, h, pitch, ms, sum[0] / n, sum[1] / n, sum[2] / n, 100.0 * black / n, 100.0 * marker / n);
   /* luminance map, 45 columns: " .:-=+*#%@" dark to light, G for untouched pixels */
   const char *ramp = " .:-=+*#%@";
   int cols = 45, cw = w / cols, rows = h / (cw * 2);
   for (int r = 0; r < rows; r++) {
      char line[64];
      for (int cx = 0; cx < cols; cx++) {
         int px = cx * cw + cw / 2, py = r * cw * 2 + cw;
         const uint8_t *p = base + py * pitch + px * 4;
         if (p[0] == 0 && p[1] == 0xff && p[2] == 0 && p[3] == 0xff) {
            line[cx] = 'G';
            continue;
         }
         int l = (p[2] * 3 + p[1] * 6 + p[0]) / 10;
         line[cx] = ramp[l * 10 / 256];
      }
      line[cols] = 0;
      printf("|%s|\n", line);
   }
   FILE *f = fopen(out, "wb");
   if (f) {
      int hw = w / 2, hh = h / 2;
      fprintf(f, "SHOT %d %d\n", hw, hh);
      uint32_t *line = malloc(hw * 4);
      for (int y = 0; y < hh; y++) {
         const uint32_t *row = (const uint32_t *)(base + y * 2 * pitch);
         for (int x = 0; x < hw; x++)
            line[x] = row[x * 2];
         fwrite(line, 4, hw, f);
      }
      free(line);
      fclose(f);
      printf("sweet_shot: wrote %s (%dx%d)\n", out, w / 2, h / 2);
   }
   IOSurfaceUnlock(s, kIOSurfaceLockReadOnly, NULL);
   CFRelease(s);
   printf("%s\n", marker == n ? "FAIL: nothing rendered" : "PASS: rendered");
   return marker == n;
}
