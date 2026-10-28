/*
 * Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 */

#include "darwin_priv.h"

uint64_t darwin_bo_news, darwin_bo_imports, darwin_bo_maps, darwin_bo_frees;

static int
darwin_bo_offset(struct fd_bo *bo, uint64_t *offset)
{
   *offset = 0;
   return 0;
}

/* SweetGPU maps a buffer by its handle (write-combined, like the GPU's view) */
static void *
darwin_bo_map(struct fd_bo *bo)
{
   mach_vm_address_t addr = 0;
   mach_vm_size_t size = 0;
   IOReturn ret = IOConnectMapMemory64(to_darwin_device(bo->dev)->conn, bo->handle,
                                       mach_task_self(), &addr, &size, DARWIN_kIOMapAnywhere);
   if (ret) {
      ERROR_MSG("map of buffer %u failed: 0x%x", bo->handle, ret);
      return NULL;
   }
   __atomic_add_fetch(&darwin_bo_maps, 1, __ATOMIC_RELAXED);
   return (void *)(uintptr_t)addr;
}

/* IOSurface.framework (declared here like IOKit in darwin_priv.h) */
struct __IOSurface;
struct __IOSurface *IOSurfaceLookup(uint32_t csid);
int IOSurfaceLock(struct __IOSurface *surface, uint32_t options, uint32_t *seed);
int IOSurfaceUnlock(struct __IOSurface *surface, uint32_t options, uint32_t *seed);
void CFRelease(const void *cf);
#define DARWIN_kIOSurfaceLockReadOnly 1

/* Only reached for shared buffers (imported IOSurfaces), after
 * fd_bo_cpu_prep waited on this process's own fences (on Darwin also with
 * explicit sync, see apply.py). GPU work of other processes on the same
 * surface is not tracked (no implicit sync yet).
 *
 * An imported IOSurface of kernel memory is CPU-cacheable, in our mapping
 * too, and the GPU is not coherent with the CPU caches. The kernel keeps it
 * up lazily (j0053): it cleans and invalidates the surface's lines when the
 * CPU next locks it after GPU work, and cleans before the next GPU job after
 * a writing unlock. Mesa's own CPU access (glReadPixels and transfer maps of
 * an imported texture) used to bypass that, so a read could return lines the
 * CPU had cached from an earlier read instead of what the GPU wrote since
 * (task 24 pixel gate, 2026-10-28), and a CPU write could stay in the cache
 * while the GPU read memory. Take part in the same protocol: a lock now
 * (invalidates what the GPU wrote), and an unlock that is read-only unless
 * the CPU is about to write (then the kernel cleans before the GPU's next
 * use). Pool surfaces are write-combined; the kernel does nothing for them.
 */
static int
darwin_bo_cpu_prep(struct fd_bo *bo, struct fd_pipe *pipe, uint32_t op)
{
   struct darwin_bo *darwin_bo = to_darwin_bo(bo);

   if (!darwin_bo->iosurface_id || !(op & (FD_BO_PREP_READ | FD_BO_PREP_WRITE)))
      return 0;

   struct __IOSurface *s = __atomic_load_n((struct __IOSurface **)&darwin_bo->iosurface, __ATOMIC_ACQUIRE);
   if (!s) {
      struct __IOSurface *found = IOSurfaceLookup(darwin_bo->iosurface_id);
      if (!found) {
         ERROR_MSG("IOSurface %u of buffer %u not found for CPU access", darwin_bo->iosurface_id, bo->handle);
         return 0;
      }
      struct __IOSurface *expected = NULL;
      if (__atomic_compare_exchange_n((struct __IOSurface **)&darwin_bo->iosurface, &expected, found, false,
                                      __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
         s = found;
      } else {
         CFRelease(found);
         s = expected;
      }
   }

   uint32_t options = (op & FD_BO_PREP_WRITE) ? 0 : DARWIN_kIOSurfaceLockReadOnly;
   int ret = IOSurfaceLock(s, options, NULL);
   if (ret) {
      ERROR_MSG("IOSurface %u lock for CPU access failed: 0x%x", darwin_bo->iosurface_id, ret);
      return 0;
   }
   IOSurfaceUnlock(s, options, NULL);
   return 0;
}

static int
darwin_bo_madvise(struct fd_bo *bo, int willneed)
{
   return willneed;
}

static uint64_t
darwin_bo_iova(struct fd_bo *bo)
{
   return to_darwin_bo(bo)->iova;
}

static void
darwin_bo_set_name(struct fd_bo *bo, const char *fmt, va_list ap)
{
}

static void
darwin_bo_destroy(struct fd_bo *bo)
{
   /* unmap here: fd_bo_fini_common would munmap() an IOKit mapping */
   if (bo->map) {
      IOConnectUnmapMemory64(to_darwin_device(bo->dev)->conn, bo->handle, mach_task_self(),
                             (mach_vm_address_t)(uintptr_t)bo->map);
      bo->map = NULL;
   }
   if (to_darwin_bo(bo)->iosurface)
      CFRelease(to_darwin_bo(bo)->iosurface);
   fd_bo_fini_common(bo);
}

static const struct fd_bo_funcs funcs = {
   .offset = darwin_bo_offset,
   .map = darwin_bo_map,
   .cpu_prep = darwin_bo_cpu_prep,
   .madvise = darwin_bo_madvise,
   .iova = darwin_bo_iova,
   .set_name = darwin_bo_set_name,
   .destroy = darwin_bo_destroy,
};

static struct fd_bo *
darwin_bo_wrap(struct fd_device *dev, uint32_t size, uint32_t handle, uint64_t iova)
{
   struct darwin_bo *darwin_bo = calloc(1, sizeof(*darwin_bo));
   if (!darwin_bo)
      return NULL;

   struct fd_bo *bo = &darwin_bo->base;
   bo->size = size;
   bo->handle = handle;
   bo->funcs = &funcs;
   darwin_bo->iova = iova;

   fd_bo_init_common(bo, dev);

   return bo;
}

/* a handle the kernel gave out (an imported IOSurface): ask it where the buffer is */
struct fd_bo *
darwin_bo_from_handle(struct fd_device *dev, uint32_t size, uint32_t handle)
{
   uint64_t in = handle;
   uint64_t out[2] = { 0, 0 };
   uint32_t nout = 2;

   IOReturn ret = IOConnectCallScalarMethod(to_darwin_device(dev)->conn, SWEETGPU_BUFFER_INFO,
                                            &in, 1, out, &nout);
   if (ret) {
      ERROR_MSG("no buffer %u: 0x%x", handle, ret);
      return NULL;
   }
   __atomic_add_fetch(&darwin_bo_imports, 1, __ATOMIC_RELAXED);
   return darwin_bo_wrap(dev, (uint32_t)out[1], handle, out[0]);
}

/* fd_bo_from_dmabuf on Darwin: the "fd" is an IOSurface id */
struct fd_bo *
darwin_bo_from_iosurface(struct fd_device *dev, int iosurface_id)
{
   uint64_t in[2] = { (uint32_t)iosurface_id, 0 };
   uint64_t out[4] = { 0, 0, 0, 0 };
   uint32_t nout = 4;

   IOReturn ret = IOConnectCallScalarMethod(to_darwin_device(dev)->conn, SWEETGPU_IMPORT_IOSURFACE,
                                            in, 2, out, &nout);
   if (ret || !out[0]) {
      ERROR_MSG("IOSurface %d not imported: 0x%x", iosurface_id, ret);
      return NULL;
   }
   /* out[3]: wrapped client memory that starts inside its first page. The buffer
    * covers the whole pages; the importer puts the resource at that offset
    * (winsys_handle.offset, which freedreno's layout takes as slice 0's offset). */
   /* one handle per surface: the device's handle table finds a second import */
   struct fd_bo *bo = fd_bo_from_handle(dev, (uint32_t)out[0], (uint32_t)out[2]);
   if (bo)
      to_darwin_bo(bo)->iosurface_id = (uint32_t)iosurface_id;   /* for CPU access (darwin_bo_cpu_prep) */
   return bo;
}

struct fd_bo *
darwin_bo_new(struct fd_device *dev, uint32_t size, uint32_t flags)
{
   uint64_t in[2] = { size, (flags & FD_BO_GPUREADONLY) ? 1 : 0 };
   uint64_t out[2] = { 0, 0 };
   uint32_t nout = 2;

   IOReturn ret = IOConnectCallScalarMethod(to_darwin_device(dev)->conn, SWEETGPU_BUFFER_NEW,
                                            in, 2, out, &nout);
   if (ret || !out[0]) {
      ERROR_MSG("buffer of %u bytes not allocated: 0x%x", size, ret);
      return NULL;
   }
   __atomic_add_fetch(&darwin_bo_news, 1, __ATOMIC_RELAXED);

   struct fd_bo *bo = darwin_bo_wrap(dev, size, (uint32_t)out[0], out[1]);
   if (!bo)
      IOConnectCallScalarMethod(to_darwin_device(dev)->conn, SWEETGPU_BUFFER_FREE, out, 1,
                                NULL, NULL);
   return bo;
}
