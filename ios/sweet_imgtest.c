/*
 * Decode an image file with ImageIO, as Core Animation does for .ca package assets, and report
 * what came out (type, size, a few pixel values), or that it failed:
 *   sweet_imgtest [-c] FILE [FILE...]
 * Plain C over CoreFoundation / ImageIO / CoreGraphics. Run it through sweetd.
 * /private/var/tmp/sweet_imgtest.png present (or SWEET_IMGTEST_PNG=path): the drawn pixels are
 * written there as PNG. -c and the trap file: see below (NOTES.md 2026-11-01 05:10, HEIC).
 */
#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CoreGraphics.h>
#include <ImageIO/ImageIO.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int
test(const char *path)
{
	CFURLRef url = CFURLCreateFromFileSystemRepresentation(NULL, (const UInt8 *)path, (CFIndex)strlen(path), false);
	CGImageSourceRef src = url ? CGImageSourceCreateWithURL(url, NULL) : NULL;
	if (url) CFRelease(url);
	if (!src) { printf("%s: no image source\n", path); return 1; }
	char type[128] = "?";
	CFStringRef t = CGImageSourceGetType(src);
	if (t) CFStringGetCString(t, type, sizeof(type), kCFStringEncodingUTF8);
	size_t count = CGImageSourceGetCount(src);
	CGImageSourceStatus st = CGImageSourceGetStatus(src);
	CGImageRef img = count ? CGImageSourceCreateImageAtIndex(src, 0, NULL) : NULL;
	if (!img) {
		printf("%s: %s, %zu images, status %d: DECODE FAILED\n", path, type, count, (int)st);
		CFRelease(src);
		return 1;
	}
	size_t w = CGImageGetWidth(img), h = CGImageGetHeight(img);
	/* draw into RGBA8 to force the actual decode, then sample a 5x5 grid */
	unsigned char *px = calloc(w * h, 4);
	CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
	CGContextRef ctx = px ? CGBitmapContextCreate(px, w, h, 8, w * 4, cs, kCGImageAlphaPremultipliedLast) : NULL;
	unsigned long long sum = 0, nonzero = 0;
	if (ctx) {
		CGContextDrawImage(ctx, CGRectMake(0, 0, (CGFloat)w, (CGFloat)h), img);
		for (size_t i = 0; i < w * h; i++) {
			unsigned v = px[4 * i] + px[4 * i + 1] + px[4 * i + 2] + px[4 * i + 3];
			sum += v;
			if (v) nonzero++;
		}
	}
	printf("%s: %s %zux%zu bpc %zu alpha %d; drawn: %s, %.1f%% non-zero pixels, mean %.1f; samples",
	       path, type, w, h, CGImageGetBitsPerComponent(img), (int)CGImageGetAlphaInfo(img), ctx ? "yes" : "NO",
	       w * h ? 100.0 * (double)nonzero / (double)(w * h) : 0.0, w * h ? (double)sum / (double)(w * h * 4) : 0.0);
	for (int gy = 1; ctx && gy <= 3; gy++)
		for (int gx = 1; gx <= 3; gx++) {
			size_t i = (h * gy / 4) * w + w * gx / 4;
			printf(" %02x%02x%02x%02x", px[4 * i], px[4 * i + 1], px[4 * i + 2], px[4 * i + 3]);
		}
	printf("\n");
	const char *png = getenv("SWEET_IMGTEST_PNG");	/* or the fixed path below, when it exists */
	if (!png && access("/private/var/tmp/sweet_imgtest.png", 0) == 0) png = "/private/var/tmp/sweet_imgtest.png";
	CGImageRef drawn = ctx && png ? CGBitmapContextCreateImage(ctx) : NULL;
	if (drawn) {	/* the drawn pixels as PNG, to look at */
		CFURLRef u = CFURLCreateFromFileSystemRepresentation(NULL, (const UInt8 *)png, (CFIndex)strlen(png), false);
		CGImageDestinationRef d = CGImageDestinationCreateWithURL(u, CFSTR("public.png"), 1, NULL);
		if (d) {
			CGImageDestinationAddImage(d, drawn, NULL);
			printf("%s: %s\n", png, CGImageDestinationFinalize(d) ? "written" : "NOT written");
			CFRelease(d);
		}
		CFRelease(u);
		CGImageRelease(drawn);
	}
	if (ctx) CGContextRelease(ctx);
	CGColorSpaceRelease(cs);
	free(px);
	CGImageRelease(img);
	CFRelease(src);
	return 0;
}

/*
 * -c: also decode through CMPhoto (ImageIO's HEIF backend) and list VideoToolbox's decoders, to see
 * which codec step fails and with what OSStatus. Private entry points via dlsym; argument order from
 * the iOS 16.7 disassembly (CMPhotoDecompressionCreateCVPixelBufferForIndex(src, index, opts, &pb),
 * SessionCreate(alloc, opts, &s), SessionCreateContainer(s, opts, src, NULL, &c),
 * ContainerCreateImageForIndex(c, index, opts, 2 = CVPixelBuffer, &pb)).
 */
typedef int (*cmp_cvpb_fn)(CFTypeRef, CFIndex, CFDictionaryRef, CFTypeRef *);
typedef int (*cmp_sess_fn)(CFAllocatorRef, CFDictionaryRef, CFTypeRef *);
typedef int (*cmp_cont_fn)(CFTypeRef, CFDictionaryRef, CFTypeRef, void *, CFTypeRef *);
typedef int (*cmp_img_fn)(CFTypeRef, CFIndex, CFDictionaryRef, int, CFTypeRef *);
typedef size_t (*cvpb_size_fn)(CFTypeRef);
typedef uint32_t (*cvpb_fmt_fn)(CFTypeRef);
typedef int (*cvpb_lock_fn)(CFTypeRef, uint64_t);
typedef void *(*cvpb_plane_fn)(CFTypeRef, size_t);
typedef size_t (*cvpb_planesz_fn)(CFTypeRef, size_t);

static void *cmphoto, *cv;

/*
 * -c with /private/var/tmp/sweet_imgtest_trap present: every "mov wN, #CVReturn" (-6660..-6690) in
 * CoreVideo becomes a brk; the SIGTRAP handler does the mov and, when the next instruction leaves
 * with the error, prints where (pc, lr, frame chain; 20H392 cache addresses) and, for -6662 in
 * checkIOSurfaceAndCreatePixelBufferBacking, the surface's geometry. IOSurfaceCreate's entry is
 * trapped too and prints the properties of planar surfaces. (Shared-cache code calls other images
 * through direct branch islands, so swapping GOT pointers catches nothing; patching code does.)
 */
#include <libkern/OSCacheControl.h>
#include <mach-o/getsect.h>
#include <mach/mach.h>
#include <signal.h>
#include <sys/ucontext.h>
static uintptr_t trap_lo, trap_hi, trap_create;
static uint32_t trap_ins[0x40000];	/* index (pc - trap_lo) / 4 -> the movn it replaced */

static void
sym(const char *tag, uint64_t a)
{
	Dl_info di;
	uint64_t slide = (uint64_t)dlsym(cv, "CVPixelBufferCreate") - 0x1a1ec044cULL;	/* 20H392 cache */
	if (dladdr((void *)a, &di) && di.dli_sname && strcmp(di.dli_sname, "<redacted>"))
		printf(" %s %s+%#lx", tag, di.dli_sname, (unsigned long)(a - (uint64_t)di.dli_saddr));
	else
		printf(" %s %#llx", tag, a - slide);
}

static void
on_trap(int sig, siginfo_t *si, void *uc_)
{
	ucontext_t *uc = uc_;
	_STRUCT_ARM_THREAD_STATE64 *ss = &uc->uc_mcontext->__ss;
	uint64_t pc = ss->__pc;
	if (pc == trap_create) {	/* IOSurfaceCreate entry: show the properties, then do its stp x20, x19, [sp, #-32]! */
		CFStringRef d = CFCopyDescription((CFTypeRef)ss->__x[0]);
		static char buf[8192];
		if (d && CFStringGetCString(d, buf, sizeof(buf), kCFStringEncodingUTF8) && strstr(buf, "PlaneInfo")) {
			for (char *p = buf; *p; p++) if (*p == '\n') *p = ' ';
			printf("  IOSurfaceCreate");
			sym("from", ss->__lr);
			printf(": %s\n", buf);
		}
		if (d) CFRelease(d);
		ss->__sp -= 32;
		((uint64_t *)ss->__sp)[0] = ss->__x[20];
		((uint64_t *)ss->__sp)[1] = ss->__x[19];
		ss->__pc = pc + 4;
		return;
	}
	if (pc < trap_lo || pc >= trap_hi || !trap_ins[(pc - trap_lo) / 4]) { signal(SIGTRAP, SIG_DFL); return; }
	uint32_t ins = trap_ins[(pc - trap_lo) / 4], val = ~((ins >> 5) & 0xffff);
	int rd = ins & 31;
	if (rd < 29) ss->__x[rd] = val;
	ss->__pc = pc + 4;
	/* Many sites only preset the error before an argument check: report only when the next
	 * instruction leaves with it (b, ret, or a cbz/cbnz/b.cond that is taken now). */
	uint32_t nx = *(uint32_t *)(pc + 4), f = ss->__cpsr >> 28;
	int N = f >> 3 & 1, Z = f >> 2 & 1, C = f >> 1 & 1, V = f & 1, take;
	if ((nx & 0xfc000000) == 0x14000000 || nx == 0xd65f03c0) take = 1;
	else if ((nx & 0x7e000000) == 0x34000000) {
		uint64_t v = (nx & 31) == 31 ? 0 : ss->__x[nx & 31];
		if (!(nx >> 31)) v &= 0xffffffff;
		take = (v == 0) ^ ((nx >> 24) & 1);
	} else if ((nx & 0xff000010) == 0x54000000) {
		switch ((nx & 15) >> 1) {
		case 0: take = Z; break;
		case 1: take = C; break;
		case 2: take = N; break;
		case 3: take = V; break;
		case 4: take = C && !Z; break;
		case 5: take = N == V; break;
		case 6: take = N == V && !Z; break;
		default: take = 1; break;
		}
		if ((nx & 1) && (nx & 15) != 15) take = !take;
	} else take = 0;
	if (!take) return;
	printf("  %d:", (int)val);
	sym("at", pc);
	sym("lr", ss->__lr);
	uint64_t *fp = (uint64_t *)ss->__fp;
	for (int d = 0; d < 8 && fp && ((uintptr_t)fp & 7) == 0; d++, fp = (uint64_t *)fp[0]) sym("<", fp[1]);
	printf("\n");
	if ((int)val == -6662 && ss->__x[21]) {	/* checkIOSurfaceAndCreatePixelBufferBacking keeps the surface in x21 */
		void *h = dlopen("/System/Library/Frameworks/IOSurface.framework/IOSurface", RTLD_NOW);
		const void *s = (const void *)ss->__x[21];
#define G(n) ((size_t (*)(uint64_t))dlsym(h, "IOSurfaceGet" #n))((uint64_t)s)
#define GP(n, p) ((size_t (*)(uint64_t, size_t))dlsym(h, "IOSurfaceGet" #n "OfPlane"))((uint64_t)s, p)
		uint32_t f = (uint32_t)G(PixelFormat);
		size_t np = G(PlaneCount);
		printf("    surface %zux%zu '%c%c%c%c' bpr %zu bpe %zu alloc %zu planes %zu base %#zx\n", G(Width), G(Height),
		       f >> 24, (f >> 16) & 255, (f >> 8) & 255, f & 255, G(BytesPerRow), G(BytesPerElement), G(AllocSize), np, G(BaseAddress));
		for (size_t p = 0; p < np; p++)
			printf("      plane %zu: %zux%zu bpr %zu bpe %zu elem %zux%zu base +%#zx\n", p, GP(Width, p), GP(Height, p),
			       GP(BytesPerRow, p), GP(BytesPerElement, p), GP(ElementWidth, p), GP(ElementHeight, p),
			       GP(BaseAddress, p) - G(BaseAddress));
#undef G
#undef GP
	}
}

static void
trap_cv(void)
{
	Dl_info di;
	if (!dladdr(dlsym(cv, "CVPixelBufferCreate"), &di)) return;
	unsigned long size = 0;
	uint32_t *t = (uint32_t *)getsectiondata(di.dli_fbase, "__TEXT", "__text", &size);
	if (!t || size / 4 > sizeof(trap_ins) / 4) { printf("trap: no text\n"); return; }
	trap_lo = (uintptr_t)t;
	trap_hi = trap_lo + size;
	struct sigaction sa = { 0 };
	sa.sa_sigaction = on_trap;
	sa.sa_flags = SA_SIGINFO;
	sigaction(SIGTRAP, &sa, NULL);
	int n = 0;
	for (size_t k = 0; k < size / 4; k++) {
		uint32_t imm = (t[k] >> 5) & 0xffff;	/* movn wN, #imm: a CVReturn -6660..-6690 */
		if ((t[k] & 0xffe00000) != 0x12800000 || imm < 6659 || imm > 6689) continue;
		uintptr_t page = (uintptr_t)(t + k) & ~0x3fffUL;
		if (vm_protect(mach_task_self(), page, 0x4000, 0, VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY)) { printf("trap: vm_protect RW failed\n"); return; }
		trap_ins[k] = t[k];
		t[k] = 0xd4200000 | (0x6661 << 5);	/* brk #0x6661 */
		vm_protect(mach_task_self(), page, 0x4000, 0, VM_PROT_READ | VM_PROT_EXECUTE);
		sys_icache_invalidate(t + k, 4);
		n++;
	}
	printf("trap: %d CoreVideo CVReturn sites patched\n", n);
	uint32_t *c = dlsym(dlopen("/System/Library/Frameworks/IOSurface.framework/IOSurface", RTLD_NOW), "IOSurfaceCreate");
	if (c && *c == 0xa9be4ff4) {	/* stp x20, x19, [sp, #-32]! */
		uintptr_t page = (uintptr_t)c & ~0x3fffUL;
		vm_protect(mach_task_self(), page, 0x4000, 0, VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY);
		*c = 0xd4200000 | (0x1055 << 5);
		vm_protect(mach_task_self(), page, 0x4000, 0, VM_PROT_READ | VM_PROT_EXECUTE);
		sys_icache_invalidate(c, 4);
		trap_create = (uintptr_t)c;
	} else
		printf("trap: IOSurfaceCreate starts %#x\n", c ? *c : 0);
}

static void
pbstats(const char *what, int err, CFTypeRef pb)
{
	if (err || !pb) { printf("  %s: OSStatus %d, buffer %p\n", what, err, pb); return; }
	uint32_t f = ((cvpb_fmt_fn)dlsym(cv, "CVPixelBufferGetPixelFormatType"))(pb);
	size_t w = ((cvpb_size_fn)dlsym(cv, "CVPixelBufferGetWidth"))(pb);
	size_t h = ((cvpb_size_fn)dlsym(cv, "CVPixelBufferGetHeight"))(pb);
	size_t planes = ((cvpb_size_fn)dlsym(cv, "CVPixelBufferGetPlaneCount"))(pb);
	((cvpb_lock_fn)dlsym(cv, "CVPixelBufferLockBaseAddress"))(pb, 1);
	printf("  %s: OK '%c%c%c%c' %zux%zu, %zu planes;", what, f >> 24, (f >> 16) & 255, (f >> 8) & 255, f & 255, w, h, planes);
	for (size_t p = 0; p < (planes ? planes : 1); p++) {
		const unsigned char *b = planes ? ((cvpb_plane_fn)dlsym(cv, "CVPixelBufferGetBaseAddressOfPlane"))(pb, p)
		                                : ((cvpb_plane_fn)dlsym(cv, "CVPixelBufferGetBaseAddress"))(pb, 0);
		size_t bpr = planes ? ((cvpb_planesz_fn)dlsym(cv, "CVPixelBufferGetBytesPerRowOfPlane"))(pb, p)
		                    : ((cvpb_size_fn)dlsym(cv, "CVPixelBufferGetBytesPerRow"))(pb);
		size_t ph = planes ? ((cvpb_planesz_fn)dlsym(cv, "CVPixelBufferGetHeightOfPlane"))(pb, p) : h;
		unsigned long long nz = 0;
		for (size_t i = 0; b && i < bpr * ph; i++) nz += b[i] != 0;
		printf(" plane %zu %p %zu B/row: %.1f%% non-zero bytes", p, (void *)b, bpr, bpr * ph ? 100.0 * (double)nz / (double)(bpr * ph) : 0.0);
	}
	((cvpb_lock_fn)dlsym(cv, "CVPixelBufferUnlockBaseAddress"))(pb, 1);
	printf("\n");
	CFRelease(pb);
}

static void
cmphoto_test(const char *path)
{
	CFURLRef url = CFURLCreateFromFileSystemRepresentation(NULL, (const UInt8 *)path, (CFIndex)strlen(path), false);
	cmp_cvpb_fn cvpb = (cmp_cvpb_fn)dlsym(cmphoto, "CMPhotoDecompressionCreateCVPixelBufferForIndex");
	cmp_sess_fn sess = (cmp_sess_fn)dlsym(cmphoto, "CMPhotoDecompressionSessionCreate");
	cmp_cont_fn cont = (cmp_cont_fn)dlsym(cmphoto, "CMPhotoDecompressionSessionCreateContainer");
	cmp_img_fn img = (cmp_img_fn)dlsym(cmphoto, "CMPhotoDecompressionContainerCreateImageForIndex");
	CFTypeRef pb = NULL;
	int err = cvpb(url, 0, NULL, &pb);
	pbstats("CMPhoto default", err, pb);
	for (int sw = 0; sw < 2; sw++) {
		const void *k[] = { CFSTR("PreferSoftwareCodec") }, *v[] = { kCFBooleanTrue };
		CFDictionaryRef o = sw ? CFDictionaryCreate(NULL, k, v, 1, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks) : NULL;
		CFTypeRef s = NULL, c = NULL;
		pb = NULL;
		int e1 = sess(NULL, NULL, &s), e2 = -1;
		err = -1;
		if (!e1) e2 = cont(s, o, url, NULL, &c);
		if (!e2) err = img(c, 0, o, 2, &pb);
		printf("  session %d, container %d\n", e1, e2);
		pbstats(sw ? "CMPhoto container PreferSoftwareCodec" : "CMPhoto container", err, pb);
		if (c) CFRelease(c);
		if (s) CFRelease(s);
		if (o) CFRelease(o);
	}
	/* one decode option at a time: which part of the decode makes the error */
	static const struct { const char *key; int val; } opt[] = {
		{ "kCMPhotoDecompressionOption_OutputPixelFormat", 'BGRA' },
		{ "kCMPhotoDecompressionOption_OutputPixelFormat", '420f' },
		{ "kCMPhotoDecompressionOption_OutputPixelFormat", '420v' },
		{ "kCMPhotoDecompressionOption_AccelerationMode", 0 },
		{ "kCMPhotoDecompressionOption_AccelerationMode", 1 },
		{ "kCMPhotoDecompressionOption_AccelerationMode", 2 },
		{ "kCMPhotoDecompressionOption_UseVTDecompression", 0 },
		{ "kCMPhotoDecompressionOption_UseVTDecompression", 1 },
		{ "kCMPhotoDecompressionOption_MaxPixelSize", 256 },
		{ "kCMPhotoDecompressionOption_PreferLowMemory", 1 },
		{ "kCMPhotoDecompressionOption_TiledDownsampling", 0 },
	};
	CFTypeRef s = NULL, c = NULL;
	if (sess(NULL, NULL, &s) || cont(s, NULL, url, NULL, &c)) { CFRelease(url); return; }
	for (size_t i = 0; i < sizeof(opt) / sizeof(opt[0]); i++) {
		CFStringRef *key = dlsym(cmphoto, opt[i].key);
		if (!key) { printf("  no %s\n", opt[i].key); continue; }
		const void *k[] = { *key }, *v[1];
		v[0] = strstr(opt[i].key, "Use") || strstr(opt[i].key, "Prefer") || strstr(opt[i].key, "Tiled")
		           ? (opt[i].val ? kCFBooleanTrue : kCFBooleanFalse)
		           : (const void *)CFNumberCreate(NULL, kCFNumberIntType, &opt[i].val);
		CFDictionaryRef o = CFDictionaryCreate(NULL, k, v, 1, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
		char what[160];
		snprintf(what, sizeof(what), "%s = %#x", opt[i].key + 29, opt[i].val);
		pb = NULL;
		err = img(c, 0, o, 2, &pb);
		pbstats(what, err, pb);
		CFRelease(o);
	}
	CFRelease(c);
	CFRelease(s);
	CFRelease(url);
}

static void
vt_list(void)
{
	void *vt = dlopen("/System/Library/Frameworks/VideoToolbox.framework/VideoToolbox", RTLD_NOW);
	int (*list)(CFDictionaryRef, CFArrayRef *) = vt ? dlsym(vt, "VTCopyVideoDecoderList") : NULL;
	Boolean (*hw)(uint32_t) = vt ? dlsym(vt, "VTIsHardwareDecodeSupported") : NULL;
	CFArrayRef a = NULL;
	int err = list ? list(NULL, &a) : -1;
	printf("VTIsHardwareDecodeSupported(hvc1) = %d; VTCopyVideoDecoderList %d, %ld decoders:\n",
	       hw ? hw('hvc1') : -1, err, a ? (long)CFArrayGetCount(a) : 0L);
	for (CFIndex i = 0; a && i < CFArrayGetCount(a); i++) {
		CFStringRef d = CFCopyDescription(CFArrayGetValueAtIndex(a, i));
		char buf[1024];
		if (d && CFStringGetCString(d, buf, sizeof(buf), kCFStringEncodingUTF8) && strstr(buf, "hvc1")) {
			for (char *p = buf; *p; p++) if (*p == '\n') *p = ' ';
			printf("  %s\n", buf);
		}
		if (d) CFRelease(d);
	}
	if (a) CFRelease(a);
}

int
main(int argc, char **argv)
{
	setvbuf(stdout, NULL, _IONBF, 0);
	int c = argc > 1 && !strcmp(argv[1], "-c");
	if (argc < 2 + c) { fprintf(stderr, "usage: sweet_imgtest [-c] FILE [FILE...]\n"); return 2; }
	if (c) {
		cmphoto = dlopen("/System/Library/PrivateFrameworks/CMPhoto.framework/CMPhoto", RTLD_NOW);
		cv = dlopen("/System/Library/Frameworks/CoreVideo.framework/CoreVideo", RTLD_NOW);
		if (!cmphoto || !cv) { printf("dlopen: %s\n", dlerror()); return 1; }
		if (access("/private/var/tmp/sweet_imgtest_trap", 0) == 0) trap_cv();
		vt_list();
		/* plain IOSurface-backed CVPixelBuffers in the formats an HEVC decode can go through */
		int (*create)(CFAllocatorRef, size_t, size_t, uint32_t, CFDictionaryRef, CFTypeRef *) = dlsym(cv, "CVPixelBufferCreate");
		const void *k[] = { CFSTR("IOSurfaceProperties") }, *v[] = { CFDictionaryCreate(NULL, NULL, NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks) };
		CFDictionaryRef attr = CFDictionaryCreate(NULL, k, v, 1, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
		static const uint32_t fmts[] = { 'BGRA', 'RGBA', '420v', '420f', 'x420', '422v', 'L008', '&8v0', 0 };
		printf("CVPixelBufferCreate 1271x1823:");
		for (int f = 0; fmts[f]; f++) {
			CFTypeRef pb = NULL;
			int e1 = create(NULL, 1271, 1823, fmts[f], NULL, &pb);
			if (pb) CFRelease(pb);
			pb = NULL;
			int e2 = create(NULL, 1271, 1823, fmts[f], attr, &pb);
			if (pb) CFRelease(pb);
			printf(" '%c%c%c%c' %d/%d", fmts[f] >> 24, (fmts[f] >> 16) & 255, (fmts[f] >> 8) & 255, fmts[f] & 255, e1, e2);
		}
		printf("  (plain/IOSurface)\n");
		CFRelease(attr);
		/* IOSurfaceCreate with each extra property CMPhoto's surface pool uses */
		void *ios = dlopen("/System/Library/Frameworks/IOSurface.framework/IOSurface", RTLD_NOW);
		CFTypeRef (*screate)(CFDictionaryRef) = dlsym(ios, "IOSurfaceCreate");
		static const char *extra[] = { NULL, "kIOSurfaceAllocateFromSuperbuffer", "kIOSurfaceCacheMode", "kIOSurfaceMapCacheAttribute",
		                               "kIOSurfacePreallocPages", "kIOSurfaceNonPurgeable", "kIOSurfaceName", "kIOSurfaceAllocSize" };
		printf("IOSurfaceCreate 1271x1823 BGRA +");
		for (size_t x = 0; x < sizeof(extra) / sizeof(extra[0]); x++) {
			int w = 1271, h = 1823, bpe = 4, fmt = 'BGRA', one = 1, big = 1271 * 1823 * 4 + 65536;
			CFMutableDictionaryRef d = CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
			CFDictionarySetValue(d, *(CFStringRef *)dlsym(ios, "kIOSurfaceWidth"), CFNumberCreate(NULL, kCFNumberIntType, &w));
			CFDictionarySetValue(d, *(CFStringRef *)dlsym(ios, "kIOSurfaceHeight"), CFNumberCreate(NULL, kCFNumberIntType, &h));
			CFDictionarySetValue(d, *(CFStringRef *)dlsym(ios, "kIOSurfaceBytesPerElement"), CFNumberCreate(NULL, kCFNumberIntType, &bpe));
			CFDictionarySetValue(d, *(CFStringRef *)dlsym(ios, "kIOSurfacePixelFormat"), CFNumberCreate(NULL, kCFNumberIntType, &fmt));
			CFStringRef *ek = extra[x] ? dlsym(ios, extra[x]) : NULL;
			if (ek) {
				const void *v = !strcmp(extra[x], "kIOSurfaceName") ? (const void *)CFSTR("sweet") :
				                !strcmp(extra[x], "kIOSurfaceAllocSize") ? (const void *)CFNumberCreate(NULL, kCFNumberIntType, &big) :
				                strstr(extra[x], "Cache") ? (const void *)CFNumberCreate(NULL, kCFNumberIntType, &one) : kCFBooleanTrue;
				CFDictionarySetValue(d, *ek, v);
			}
			CFTypeRef sf = screate(d);
			printf(" %s:%s", extra[x] ? extra[x] + 9 : "none", ek || !extra[x] ? (sf ? "ok" : "NULL") : "nokey");
			if (sf) CFRelease(sf);
			CFRelease(d);
		}
		printf("\n");
	}
	int bad = 0;
	for (int i = 1 + c; i < argc; i++) {
		bad |= test(argv[i]);
		if (c) cmphoto_test(argv[i]);
	}
	return bad;
}
