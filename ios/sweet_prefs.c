/*
 * Injected into Settings (Preferences), installed as /q.dylib, through the kernel's @ui group
 * (j0128: sweetenv=@ui:DYLD_INSERT_LIBRARIES=/s.dylib:/q.dylib, shared with SpringBoard, so it does
 * nothing outside Preferences).
 *
 * Privacy & Security hides Location Services unless -[PUIPrivacyController
 * refreshLocationServicesAvailable] stores a value: it asks CoreTelephony for the SIM subscriptions
 * (a carrier bundle may set LocationServicesAvailable = NO) and, on an error, returns without storing
 * anything, and nil reads as "not available". jasmine runs no CommCenter (no baseband), so the call
 * always fails. After the original, a nil value is replaced by YES, which is what iOS stores when there
 * is no SIM or the carrier says nothing. PrivacySettingsUI loads lazily, so the hook is installed when
 * its image shows up. Log: /var/tmp/sweet_prefs.log.
 */
#include <mach-o/dyld.h>
#include <objc/message.h>
#include <objc/runtime.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static IMP orig_refresh;
static int hooked;

static void
logf_(const char *msg)
{
	FILE *f = fopen("/var/tmp/sweet_prefs.log", "a");
	if (f) {
		fprintf(f, "%s\n", msg);
		fclose(f);
	}
}

static void
hook_refresh(id self, SEL cmd)
{
	((void (*)(id, SEL))orig_refresh)(self, cmd);
	SEL get = sel_registerName("_cachedLocationServicesAvailableValue");
	if (((id (*)(id, SEL))objc_msgSend)(self, get) != NULL)
		return;
	id yes = ((id (*)(id, SEL, char))objc_msgSend)((id)objc_getClass("NSNumber"),
	    sel_registerName("numberWithBool:"), 1);
	((void (*)(id, SEL, id))objc_msgSend)(self, sel_registerName("set_cachedLocationServicesAvailableValue:"), yes);
	logf_("location services: CoreTelephony gave no answer, set available");
}

static void
try_hook(void)
{
	if (hooked)
		return;
	Class c = objc_getClass("PUIPrivacyController");
	if (!c)
		return;
	Method m = class_getInstanceMethod(c, sel_registerName("refreshLocationServicesAvailable"));
	if (!m || !class_getInstanceMethod(c, sel_registerName("set_cachedLocationServicesAvailableValue:")))
		return;
	hooked = 1;
	orig_refresh = method_setImplementation(m, (IMP)hook_refresh);
	logf_("hooked -[PUIPrivacyController refreshLocationServicesAvailable]");
}

static void
image_added(const struct mach_header *mh, intptr_t slide)
{
	try_hook();
}

__attribute__((constructor)) static void
init(void)
{
	const char *name = getprogname();
	if (!name || strcmp(name, "Preferences") != 0)
		return;
	logf_("sweet_prefs loaded");
	_dyld_register_func_for_add_image(image_added);
	try_hook();
}
