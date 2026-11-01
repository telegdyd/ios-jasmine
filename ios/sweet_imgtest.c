/*
 * Decode an image file with ImageIO, as Core Animation does for .ca package assets, and report
 * what came out (type, size, a few pixel values), or that it failed:
 *   sweet_imgtest FILE [FILE...]
 * Plain C over CoreFoundation / ImageIO / CoreGraphics. Run it through sweetd.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CoreGraphics.h>
#include <ImageIO/ImageIO.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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
	if (ctx) CGContextRelease(ctx);
	CGColorSpaceRelease(cs);
	free(px);
	CGImageRelease(img);
	CFRelease(src);
	return 0;
}

int
main(int argc, char **argv)
{
	if (argc < 2) { fprintf(stderr, "usage: sweet_imgtest FILE [FILE...]\n"); return 2; }
	int bad = 0;
	for (int i = 1; i < argc; i++) bad |= test(argv[i]);
	return bad;
}
