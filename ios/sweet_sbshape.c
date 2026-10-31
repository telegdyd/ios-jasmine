/*
 * Injected into SpringBoard (sweetenv=...;SpringBoard:DYLD_INSERT_LIBRARIES=/usr/local/bin/sweet_sbshape.dylib,
 * settings in /usr/local/bin/sbs.conf as "W,H,SCREENW"): replaces the exclusion area (notch) SpringBoard
 * hands UIKit in its display context. UIKit picks the status bar provider by pixel width and requires
 * notchSize == exclusionArea * (nativeScale / scale) to 1e-4 (_UIStatusBarVisualProvider_Split*);
 * SpringBoard's table gives the iPhone X notch (209x30) whatever the display size, so a smaller canvas
 * (task 25) needs the notch of the matching class: 828 wide (iPhone XR) 227x32.
 * Plain C over the ObjC runtime; the context class is in UIKitServices, so the hook is installed when
 * that image shows up.
 *
 * Task 19: with /usr/local/bin/sbs-noparallax present, UIKit's motion effects report "not supported" in
 * SpringBoard (+[_UIMotionEffectEngine _motionEffectsSupported], +[UIView _motionEffectsSupported]; UIKit
 * itself asks MobileGestalt's UIParallaxCapability). jasmine has no motion sensor service (HID usage page
 * 0xff0c), so the Home screen's icon parallax started CoreMotion, which retried the missing accelerometer/gyro,
 * gave up with a fault ("[CLIoHidInterface] Could not set all properties after too many retries"), and every
 * fault made libtrace run all of SpringBoard's state capture handlers (0.25-1.3 s of CPU, partly on the main thread).
 */
#include <mach-o/dyld.h>
#include <objc/message.h>
#include <objc/runtime.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct { double x, y, w, h; } rect;

static IMP orig_set;
static double shape_w, shape_h, screen_w;
static int hooked, want_shape, want_noparallax, hooked_parallax;

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

static BOOL
no_motion_effects(id self, SEL cmd)
{
   return NO;
}

static void
try_hook_parallax(void)
{
   if (!want_noparallax || hooked_parallax)
      return;
   Class e = objc_getClass("_UIMotionEffectEngine"), v = objc_getClass("UIView");
   Method me = e ? class_getClassMethod(e, sel_registerName("_motionEffectsSupported")) : NULL;
   Method mv = v ? class_getClassMethod(v, sel_registerName("_motionEffectsSupported")) : NULL;
   if (!me || !mv)
      return;
   method_setImplementation(me, (IMP)no_motion_effects);
   method_setImplementation(mv, (IMP)no_motion_effects);
   hooked_parallax = 1;
   logf_("motion effects reported unsupported (no motion sensors)");
}

static void
try_hook(void)
{
   try_hook_parallax();
   if (!want_shape || hooked)
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
   FILE *pf = fopen("/usr/local/bin/sbs-noparallax", "r");
   if (pf) {
      fclose(pf);
      want_noparallax = 1;
   }
   FILE *cf = fopen("/usr/local/bin/sbs.conf", "r");
   if (cf) {
      int n = fscanf(cf, "%lf,%lf,%lf", &shape_w, &shape_h, &screen_w);
      fclose(cf);
      if (n >= 2) {
         want_shape = 1;
         if (n < 3)
            screen_w = 414;
      }
   }
   if (!want_shape && !want_noparallax)
      return;
   logf_("sweet_sbshape loaded");
   _dyld_register_func_for_add_image(image_added);
   try_hook();
}
