/*
 * Injected into SpringBoard (sweetenv=...;SpringBoard:DYLD_INSERT_LIBRARIES=/usr/local/bin/sweet_sbshape.dylib,
 * settings in /usr/local/bin/sbs.conf as "W,H,SCREENW"): replaces the exclusion area (notch) SpringBoard
 * hands UIKit in its display context. UIKit picks the status bar provider by pixel width and requires
 * notchSize == exclusionArea * (nativeScale / scale) to 1e-4 (_UIStatusBarVisualProvider_Split*);
 * SpringBoard's table gives the iPhone X notch (209x30) whatever the display size, so a smaller canvas
 * (task 25) needs the notch of the matching class: 828 wide (iPhone XR) 227x32.
 * Plain C over the ObjC runtime; the context class is in UIKitServices, so the hook is installed when
 * that image shows up.
 */
#include <mach-o/dyld.h>
#include <objc/message.h>
#include <objc/runtime.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct { double x, y, w, h; } rect;

static IMP orig_set;
static double shape_w, shape_h, screen_w;
static int hooked;

static void
logf_(const char *msg)
{
   FILE *f = fopen("/var/tmp/sweet_sbshape.log", "a");
   if (f) {
      fprintf(f, "%s\n", msg);
      fclose(f);
   }
}

static void
hook_set(id self, SEL cmd, id shape)
{
   Class c = objc_getClass("UISDisplaySingleRectShape");
   id n = ((id(*)(id, SEL))objc_msgSend)((id)c, sel_registerName("alloc"));
   rect r = { (screen_w - shape_w) / 2, 0, shape_w, shape_h };
   n = ((id(*)(id, SEL, rect))objc_msgSend)(n, sel_registerName("initWithRect:"), r);
   char b[160];
   snprintf(b, sizeof(b), "setExclusionArea: %p -> %p (%.2f x %.2f)", shape, n, shape_w, shape_h);
   logf_(b);
   ((void (*)(id, SEL, id))orig_set)(self, cmd, n ? n : shape);
}

static void
try_hook(void)
{
   if (hooked)
      return;
   Class c = objc_getClass("UISMutableDisplayContext");
   if (!c)
      return;
   Method m = class_getInstanceMethod(c, sel_registerName("setExclusionArea:"));
   if (!m)
      return;
   orig_set = method_setImplementation(m, (IMP)hook_set);
   hooked = 1;
   logf_("hooked UISMutableDisplayContext setExclusionArea:");
}

static void
image_added(const struct mach_header *mh, intptr_t slide)
{
   try_hook();
}

__attribute__((constructor)) static void
init(void)
{
   FILE *cf = fopen("/usr/local/bin/sbs.conf", "r");
   if (!cf)
      return;
   int n = fscanf(cf, "%lf,%lf,%lf", &shape_w, &shape_h, &screen_w);
   fclose(cf);
   if (n < 2)
      return;
   if (n < 3)
      screen_w = 414;
   logf_("sweet_sbshape loaded");
   _dyld_register_func_for_add_image(image_added);
   try_hook();
}
