/*
 * Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 */

#include "darwin_priv.h"

/* the last device opened and its pipes, for darwin_prof_report() */
static struct fd_device *prof_dev;
struct fd_pipe *darwin_pipes[DARWIN_MAX_PIPES];

int
darwin_get_param(struct fd_device *dev, enum sweetgpu_param param, uint64_t *value)
{
   uint64_t in = param;
   uint32_t nout = 1;
   IOReturn ret = IOConnectCallScalarMethod(to_darwin_device(dev)->conn, SWEETGPU_GET_PARAM,
                                            &in, 1, value, &nout);
   return ret ? -EIO : 0;
}

static void
darwin_bo_close_handle(struct fd_bo *bo)
{
   uint64_t in = bo->handle;
   IOConnectCallScalarMethod(to_darwin_device(bo->dev)->conn, SWEETGPU_BUFFER_FREE, &in, 1,
                             NULL, NULL);
   __atomic_add_fetch(&darwin_bo_frees, 1, __ATOMIC_RELAXED);
}

static void
darwin_device_destroy(struct fd_device *dev)
{
   IOServiceClose(to_darwin_device(dev)->conn);
}

static const struct fd_device_funcs funcs = {
   .bo_new = darwin_bo_new,
   .bo_from_handle = darwin_bo_from_handle,
   .bo_from_dmabuf = darwin_bo_from_iosurface,
   .bo_close_handle = darwin_bo_close_handle,
   .pipe_new = darwin_pipe_new,
   .destroy = darwin_device_destroy,
};

/* fd is not used: the device is the SweetGPU IOKit service */
struct fd_device *
darwin_device_new(int fd)
{
   io_service_t service =
      IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("SweetGPU"));
   if (!service) {
      ERROR_MSG("no SweetGPU service (kernel without sweetgpu=4?)");
      return NULL;
   }

   io_connect_t conn = 0;
   IOReturn ret = IOServiceOpen(service, mach_task_self(), 0, &conn);
   IOObjectRelease(service);
   if (ret) {
      ERROR_MSG("cannot open SweetGPU: 0x%x", ret);
      return NULL;
   }

   struct darwin_device *darwin_dev = calloc(1, sizeof(*darwin_dev));
   if (!darwin_dev) {
      IOServiceClose(conn);
      return NULL;
   }
   darwin_dev->conn = conn;

   struct fd_device *dev = &darwin_dev->base;
   dev->funcs = &funcs;
   /* softpin, GMEM base and VA size queries: what SweetGPU offers */
   dev->version = FD_VERSION_VA_SIZE;
   dev->bo_size = sizeof(struct darwin_bo);

   uint64_t ready = 0;
   if (darwin_get_param(dev, SWEETGPU_PARAM_READY, &ready) || !ready) {
      ERROR_MSG("SweetGPU is not ready");
      IOServiceClose(conn);
      free(darwin_dev);
      return NULL;
   }

   prof_dev = dev;
   return dev;
}

struct cache_sum {
   int hits, misses, busy, flagskip, expired, count;
};

static struct cache_sum
cache_sum(struct fd_bo_cache *cache)
{
   struct cache_sum s = {0};
   for (int i = 0; i < cache->num_buckets; i++) {
      struct fd_bo_bucket *b = &cache->cache_bucket[i];
      s.hits += b->hits;
      s.misses += b->misses;
      s.busy += b->busy;
      s.flagskip += b->flagskip;
      s.expired += b->expired;
      s.count += b->count;
   }
   return s;
}

/* one cache since the last report (bucket counters from FD_BO_CACHE_STATS) */
static void
cache_line(void (*log)(const char *fmt, ...), struct fd_bo_cache *cache, struct cache_sum *last)
{
   struct cache_sum s = cache_sum(cache);
   log("sweetca: prof: %s: %d hits, %d misses (%d at a busy head, %d flag skips), %d expired, %d cached; "
       "busy head ufence %u ctrl %u, flag skip wanted 0x%x had 0x%x",
       cache->name, s.hits - last->hits, s.misses - last->misses, s.busy - last->busy,
       s.flagskip - last->flagskip, s.expired - last->expired, s.count, cache->diag_ufence, cache->diag_ctrl,
       cache->diag_want, cache->diag_had);
   *last = s;
}

void
darwin_prof_report(void (*log)(const char *fmt, ...))
{
   static uint64_t news0, maps0, frees0;
   static struct cache_sum bo0, ring0;
   struct fd_device *dev = prof_dev;
   if (!dev)
      return;

   uint64_t news = darwin_bo_news, maps = darwin_bo_maps, frees = darwin_bo_frees;
   log("sweetca: prof: SweetGPU buffers: %llu created, %llu mapped, %llu freed",
       (unsigned long long)(news - news0), (unsigned long long)(maps - maps0),
       (unsigned long long)(frees - frees0));
   news0 = news;
   maps0 = maps;
   frees0 = frees;

   cache_line(log, &dev->bo_cache, &bo0);
   cache_line(log, &dev->ring_cache, &ring0);

   uint64_t done = 0;
   uint32_t nout = 1;
   IOConnectCallScalarMethod(to_darwin_device(dev)->conn, SWEETGPU_COMPLETED, NULL, 0, &done, &nout);
   char line[512];
   int n = snprintf(line, sizeof(line), "kernel done %llu, last submit kfence %u ufence %u;",
                    (unsigned long long)done, darwin_last_kfence, darwin_last_ufence);
   for (int i = 0; i < DARWIN_MAX_PIPES && n < (int)sizeof(line); i++) {
      struct fd_pipe *p = darwin_pipes[i];
      if (p && p->control)
         n += snprintf(line + n, sizeof(line) - n, " pipe %d: last_fence %u ctrl %u;", i, p->last_fence,
                       p->control->fence);
   }
   log("sweetca: prof: fences: %s", line);
}
