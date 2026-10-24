/*
 * Read the phone's unified log (what `log show` prints on a Mac) through OSLogStore:
 *   sweet_oslog SECONDS [PROCESS[,PROCESS...]|-] [SUBSTRING]
 * prints the entries of the last SECONDS seconds, only from the named processes (- = all)
 * and only those containing SUBSTRING. Needs the logging entitlements in ios/entitlements.plist.
 * Plain C over the ObjC runtime as sweet_extq.c. Run it through sweetd.
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

#define M0(o, s) ((id(*)(id, SEL))msgsend)((o), selname(s))
#define M1(o, s, a) ((id(*)(id, SEL, id))msgsend)((o), selname(s), (id)(a))
#define M2(o, s, a, b) ((id(*)(id, SEL, id, id))msgsend)((o), selname(s), (id)(a), (id)(b))
#define MD(o, s, d) ((id(*)(id, SEL, double))msgsend)((o), selname(s), (double)(d))
#define MF(o, s) ((double (*)(id, SEL))msgsend)((o), selname(s))
#define MU(o, s) ((unsigned long (*)(id, SEL))msgsend)((o), selname(s))

static const char *
cstr(id o)
{
	if (o == NULL) {
		return "";
	}
	const char *s = (const char *)M0(M0(o, "description"), "UTF8String");
	return s ? s : "";
}

static int
can(id o, const char *s)
{
	return o != NULL && responds(objclass(o), selname(s));
}

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

/* PROCS is a comma list; NAME matches when it is one of its items */
static int
proc_wanted(const char *procs, const char *name)
{
	size_t n = strlen(name);
	for (const char *p = procs; *p;) {
		const char *e = strchr(p, ',');
		size_t len = e ? (size_t)(e - p) : strlen(p);
		if (len == n && strncmp(p, name, n) == 0) {
			return 1;
		}
		if (e == NULL) {
			break;
		}
		p = e + 1;
	}
	return 0;
}

static id
open_store(void)
{
	id cls = getclass("OSLogStore"), err = NULL, store = NULL;
	if (cls == NULL) {
		printf("no OSLogStore class\n");
		return NULL;
	}
	if (responds(objclass(cls), selname("localStoreAndReturnError:"))) {
		store = M1(cls, "localStoreAndReturnError:", &err);
		if (store) {
			return store;
		}
		printf("localStoreAndReturnError: %s\n", cstr(err));
	}
	if (responds(objclass(cls), selname("storeWithScope:error:"))) {
		err = NULL;
		/* OSLogStoreSystem = 0 */
		store = ((id(*)(id, SEL, long, id *))msgsend)(cls, selname("storeWithScope:error:"), 0, &err);
		if (store) {
			return store;
		}
		printf("storeWithScope:System: %s\n", cstr(err));
	}
	dump_methods("OSLogStore", 1, "tore");
	return NULL;
}

int
main(int argc, char **argv)
{
	static const char *const libs[] = {
		"/usr/lib/libobjc.A.dylib",
		"/System/Library/Frameworks/Foundation.framework/Foundation",
		"/System/Library/Frameworks/OSLog.framework/OSLog",
	};
	double secs = argc > 1 ? atof(argv[1]) : 600;
	const char *procs = argc > 2 && strcmp(argv[2], "-") != 0 ? argv[2] : NULL;
	const char *needle = argc > 3 ? argv[3] : NULL;
	unsigned long seen = 0, shown = 0;

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
	setvbuf(stdout, NULL, _IOLBF, 0);
	void *pool = poolpush();
	id store = open_store();
	if (store == NULL) {
		poolpop(pool);
		return 1;
	}
	id since = MD(getclass("NSDate"), "dateWithTimeIntervalSinceNow:", -secs);
	id pos = M1(store, "positionWithDate:", since), err = NULL;
	id en = ((id(*)(id, SEL, unsigned long, id, id, id *))msgsend)(store,
	    selname("entriesEnumeratorWithOptions:position:predicate:error:"), 0, pos, NULL, &err);
	if (en == NULL) {
		printf("entriesEnumerator: %s\n", cstr(err));
		poolpop(pool);
		return 1;
	}
	double t0 = MF(since, "timeIntervalSince1970");
	for (;;) {
		void *inner = poolpush();
		id e = M0(en, "nextObject");
		if (e == NULL) {
			poolpop(inner);
			break;
		}
		seen++;
		const char *proc = can(e, "process") ? cstr(M0(e, "process")) : "";
		if (procs && !proc_wanted(procs, proc)) {
			poolpop(inner);
			continue;
		}
		const char *msg = cstr(M0(e, "composedMessage"));
		if (needle && !strstr(msg, needle)) {
			poolpop(inner);
			continue;
		}
		double t = MF(M0(e, "date"), "timeIntervalSince1970") - t0;
		const char *sub = can(e, "subsystem") ? cstr(M0(e, "subsystem")) : "";
		const char *cat = can(e, "category") ? cstr(M0(e, "category")) : "";
		long pid = can(e, "processIdentifier") ? (long)(int)MU(e, "processIdentifier") : -1;
		long level = can(e, "level") ? (long)MU(e, "level") : -1;
		printf("%8.3f %s[%ld] L%ld %s:%s: %s\n", t, proc, pid, level, sub, cat, msg);
		shown++;
		poolpop(inner);
	}
	printf("# %lu entries read, %lu shown\n", seen, shown);
	poolpop(pool);
	return 0;
}
