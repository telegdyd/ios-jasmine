/*
 * What LaunchServices and ExtensionKit know about an extension point: are its app extensions
 * registered, and does a query for the point find them? Written for PosterBoard's wallpaper
 * providers (com.apple.posterkit.provider), which never start on jasmine.
 *   sweet_extq [--sync|--rebuild] [EXTENSION_POINT [BUNDLE_ID...]]
 * --sync / --rebuild first ask lsd to sync with MobileInstallation / rebuild its database.
 * Plain C over the ObjC runtime (the CI build links nothing but libSystem), everything looked
 * up with dlsym, so a missing class or selector is printed instead of crashing. Run it through
 * sweetd.
 */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef void *id;
typedef void *SEL;

static id (*getclass)(const char *);
static SEL (*selname)(const char *);
static int (*responds)(id, SEL);
static id (*objclass)(id);
static void *(*poolpush)(void);
static void (*poolpop)(void *);
static void **(*methodlist)(id, unsigned int *);
static SEL (*methodname)(void *);
static const char *(*selstr)(SEL);
static void *msgsend;

/* objc_msgSend called through the exact non-variadic type (arm64 passes variadic arguments on
 * the stack, the callee expects registers) */
#define M0(o, s) ((id(*)(id, SEL))msgsend)((o), selname(s))
#define M1(o, s, a) ((id(*)(id, SEL, id))msgsend)((o), selname(s), (id)(a))
#define M2(o, s, a, b) ((id(*)(id, SEL, id, id))msgsend)((o), selname(s), (id)(a), (id)(b))
#define MU(o, s) ((unsigned long (*)(id, SEL))msgsend)((o), selname(s))
#define MI(o, s, i) ((id(*)(id, SEL, unsigned long))msgsend)((o), selname(s), (unsigned long)(i))

static id
str(const char *s)
{
	return M1(getclass("NSString"), "stringWithUTF8String:", s);
}

static const char *
desc(id o)
{
	if (o == NULL) {
		return "(nil)";
	}
	const char *s = (const char *)M0(M0(o, "description"), "UTF8String");
	return s ? s : "(no description)";
}

static int
can(id o, const char *s)
{
	return o != NULL && responds(objclass(o), selname(s));
}

/* the selectors of a class (instance side, or the metaclass for class methods) containing FILTER */
static void
dump_methods(const char *cls, int meta, const char *filter)
{
	id c = getclass(cls);
	unsigned int n = 0;
	if (c == NULL) {
		printf("  class %s: missing\n", cls);
		return;
	}
	void **list = methodlist(meta ? objclass(c) : c, &n);
	printf("  %s %s methods matching \"%s\":", meta ? "+" : "-", cls, filter);
	for (unsigned int i = 0; i < n; i++) {
		const char *name = selstr(methodname(list[i]));
		if (strstr(name, filter)) {
			printf(" %s", name);
		}
	}
	printf("\n");
	free(list);
}

static void
print_array(const char *what, id arr)
{
	unsigned long n = arr ? MU(arr, "count") : 0;
	printf("%s: %lu\n", what, n);
	for (unsigned long i = 0; i < n && i < 40; i++) {
		printf("  [%lu] %s\n", i, desc(MI(arr, "objectAtIndex:", i)));
	}
}

/* LSApplicationWorkspace -installedPlugins: every PlugInKit-registered extension */
static void
ls_plugins(const char *point)
{
	id ws = getclass("LSApplicationWorkspace") ? M0(getclass("LSApplicationWorkspace"), "defaultWorkspace") : NULL;
	if (!can(ws, "installedPlugins")) {
		printf("LSApplicationWorkspace installedPlugins: not available\n");
		return;
	}
	id all = M0(ws, "installedPlugins");
	unsigned long n = all ? MU(all, "count") : 0, hits = 0;
	printf("LS installedPlugins: %lu in all\n", n);
	for (unsigned long i = 0; i < n; i++) {
		id p = MI(all, "objectAtIndex:", i);
		const char *proto = can(p, "protocol") ? desc(M0(p, "protocol")) : "?";
		const char *ident = can(p, "pluginIdentifier") ? desc(M0(p, "pluginIdentifier")) : "?";
		if (n <= 10 || strcmp(proto, point) == 0 || strstr(ident, "oster")) {
			printf("  %s (%s)\n", ident, proto);
			hits++;
		}
	}
	printf("LS installedPlugins for %s or named *oster*: %lu\n", point, hits);
}

/*
 * Ask lsd to bring its database up to date with MobileInstallation (installd): "sync" is the
 * path that registers the extension points frameworks define (NSExtensionSDK), "rebuild" a full
 * rebuild of the system app database.
 */
static void
ls_refresh(const char *how)
{
	id ws = getclass("LSApplicationWorkspace") ? M0(getclass("LSApplicationWorkspace"), "defaultWorkspace") : NULL;
	const char *s = strcmp(how, "sync") == 0 ? "_LSPrivateSyncWithMobileInstallation" :
	    "_LSPrivateRebuildApplicationDatabasesForSystemApps:internal:user:";
	if (!can(ws, s)) {
		printf("%s: not available\n", s);
		dump_methods("LSApplicationWorkspace", 0, "_LSPrivate");
		return;
	}
	printf("%s ...\n", s);
	unsigned long ok = strcmp(how, "sync") == 0 ? MU(ws, s) :
	    ((unsigned long (*)(id, SEL, int, int, int))msgsend)(ws, selname(s), 1, 1, 1);
	printf("%s returned %lu\n", s, ok & 0xff);
}

/* LSApplicationExtensionRecord for one bundle id: registered at all, and under which point */
static void
ls_record(const char *bundle)
{
	id cls = getclass("LSApplicationExtensionRecord");
	id err = NULL;
	if (cls == NULL) {
		printf("record %s: no LSApplicationExtensionRecord class\n", bundle);
		return;
	}
	id rec = M2(M0(cls, "alloc"), "initWithBundleIdentifier:error:", str(bundle), &err);
	if (rec == NULL) {
		printf("record %s: none, error %s\n", bundle, desc(err));
		return;
	}
	printf("record %s: found\n", bundle);
	if (can(rec, "extensionPointRecord")) {
		id pt = M0(rec, "extensionPointRecord");
		printf("  extension point record: %s\n", desc(pt));
	}
	if (can(rec, "URL")) {
		printf("  URL: %s\n", desc(M0(rec, "URL")));
	}
	if (can(rec, "entitlements")) {
		printf("  entitlements: %s\n", desc(M0(rec, "entitlements")));
	}
}

/* the ExtensionKit query a host makes (ExtensionFoundation _EXQuery / _EXQueryController) */
static void
ex_query(const char *point)
{
	id qcls = getclass("_EXQuery"), ccls = getclass("_EXQueryController");
	if (qcls == NULL || ccls == NULL) {
		printf("ExtensionKit query: _EXQuery %s, _EXQueryController %s\n", qcls ? "ok" : "missing",
		    ccls ? "ok" : "missing");
		return;
	}
	id q = M0(qcls, "alloc");
	if (!can(q, "initWithExtensionPointIdentifier:") || !responds(objclass(ccls), selname("executeQuery:"))) {
		printf("ExtensionKit query: selectors differ\n");
		dump_methods("_EXQuery", 0, "init");
		dump_methods("_EXQueryController", 1, "uer");
		return;
	}
	q = M1(q, "initWithExtensionPointIdentifier:", str(point));
	print_array("ExtensionKit _EXQueryController executeQuery", M1(ccls, "executeQuery:", q));
}

/* the PlugInKit route (NSExtension, through pkd) */
static void
pk_query(const char *point)
{
	id cls = getclass("NSExtension"), err = NULL;
	if (cls == NULL || !responds(objclass(cls), selname("extensionsWithMatchingAttributes:error:"))) {
		printf("NSExtension extensionsWithMatchingAttributes: not available\n");
		return;
	}
	id attrs = M2(getclass("NSDictionary"), "dictionaryWithObject:forKey:", str(point), str("NSExtensionPointName"));
	id arr = M2(cls, "extensionsWithMatchingAttributes:error:", attrs, &err);
	print_array("NSExtension extensionsWithMatchingAttributes", arr);
	if (err) {
		printf("  error: %s\n", desc(err));
	}
}

int
main(int argc, char **argv)
{
	static const char *const def_bundles[] = {
		"com.apple.WallpaperKit.CollectionsPoster",
		"com.apple.GradientPoster.GradientPosterExtension",
		"com.apple.EmojiPoster.EmojiPosterExtension",
	};
	const char *refresh = NULL;
	if (argc > 1 && (strcmp(argv[1], "--sync") == 0 || strcmp(argv[1], "--rebuild") == 0)) {
		refresh = argv[1] + 2;
		argc--;
		argv++;
	}
	const char *point = argc > 1 ? argv[1] : "com.apple.posterkit.provider";
	static const char *const libs[] = {
		"/usr/lib/libobjc.A.dylib",
		"/System/Library/Frameworks/Foundation.framework/Foundation",
		"/System/Library/Frameworks/CoreServices.framework/CoreServices",
		"/System/Library/Frameworks/MobileCoreServices.framework/MobileCoreServices",
		"/System/Library/Frameworks/ExtensionFoundation.framework/ExtensionFoundation",
		"/System/Library/PrivateFrameworks/ExtensionFoundation.framework/ExtensionFoundation",
		"/System/Library/Frameworks/ExtensionKit.framework/ExtensionKit",
	};

	for (size_t i = 0; i < sizeof(libs) / sizeof(libs[0]); i++) {
		if (dlopen(libs[i], RTLD_NOW | RTLD_GLOBAL) == NULL) {
			printf("dlopen %s: %s\n", libs[i], dlerror());
		}
	}
	getclass = (id(*)(const char *))dlsym(RTLD_DEFAULT, "objc_getClass");
	selname = (SEL(*)(const char *))dlsym(RTLD_DEFAULT, "sel_registerName");
	responds = (int (*)(id, SEL))dlsym(RTLD_DEFAULT, "class_respondsToSelector");
	objclass = (id(*)(id))dlsym(RTLD_DEFAULT, "object_getClass");
	poolpush = (void *(*)(void))dlsym(RTLD_DEFAULT, "objc_autoreleasePoolPush");
	poolpop = (void (*)(void *))dlsym(RTLD_DEFAULT, "objc_autoreleasePoolPop");
	methodlist = (void **(*)(id, unsigned int *))dlsym(RTLD_DEFAULT, "class_copyMethodList");
	methodname = (SEL(*)(void *))dlsym(RTLD_DEFAULT, "method_getName");
	selstr = (const char *(*)(SEL))dlsym(RTLD_DEFAULT, "sel_getName");
	msgsend = dlsym(RTLD_DEFAULT, "objc_msgSend");
	if (!getclass || !selname || !responds || !objclass || !poolpush || !poolpop || !methodlist ||
	    !methodname || !selstr || !msgsend) {
		printf("ObjC runtime not found\n");
		return 1;
	}
	void *pool = poolpush();
	setvbuf(stdout, NULL, _IOLBF, 0);
	printf("extension point %s\n", point);
	if (refresh) {
		ls_refresh(refresh);
	}
	ls_plugins(point);
	if (argc > 2) {
		for (int i = 2; i < argc; i++) {
			ls_record(argv[i]);
		}
	} else {
		for (size_t i = 0; i < sizeof(def_bundles) / sizeof(def_bundles[0]); i++) {
			ls_record(def_bundles[i]);
		}
	}
	ex_query(point);
	pk_query(point);
	poolpop(pool);
	return 0;
}
