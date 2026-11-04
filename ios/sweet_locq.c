/*
 * What CoreLocation tells Settings about location services. Settings > Privacy & Security shows
 * the Location Services row only when -[PUIPrivacyController refreshLocationServicesAvailable]
 * finds them available, so this prints the CLLocationManager class answers it can use.
 *   sweet_locq
 * Plain C over the ObjC runtime (dlsym only, as sweet_extq). Run it through sweetd.
 */
#include <dlfcn.h>
#include <stdio.h>

typedef void *id;
typedef void *SEL;

int
main(void)
{
	void *objc = dlopen("/usr/lib/libobjc.A.dylib", RTLD_NOW);
	if (!objc || !dlopen("/System/Library/Frameworks/CoreLocation.framework/CoreLocation", RTLD_NOW)) {
		printf("dlopen: %s\n", dlerror());
		return 1;
	}
	id (*getclass)(const char *) = dlsym(objc, "objc_getClass");
	SEL (*selname)(const char *) = dlsym(objc, "sel_registerName");
	int (*responds)(id, SEL) = dlsym(objc, "class_respondsToSelector");
	id (*objclass)(id) = dlsym(objc, "object_getClass");
	void *msgsend = dlsym(objc, "objc_msgSend");
	void *(*poolpush)(void) = dlsym(objc, "objc_autoreleasePoolPush");
	poolpush();

	id cl = getclass("CLLocationManager");
	if (!cl) {
		printf("no CLLocationManager\n");
		return 1;
	}
	static const char *sels[] = {
		"locationServicesAvailable", "locationServicesEnabled", "isLocationServicesPreferencesDialogEnabled",
		"headingAvailable", "significantLocationChangeMonitoringAvailable", "authorizationStatus",
	};
	for (unsigned i = 0; i < sizeof sels / sizeof *sels; i++) {
		SEL s = selname(sels[i]);
		if (!responds(objclass(cl), s)) {
			printf("+%s: not implemented\n", sels[i]);
			continue;
		}
		long v = ((long (*)(id, SEL))msgsend)(cl, s);
		printf("+%s: %ld\n", sels[i], v & (i == 5 ? -1L : 0xff));
	}
	return 0;
}
