/*
 * Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 */

#include <mach/mach_time.h>

#include "util/os_time.h"

#include "freedreno_ringbuffer_sp.h"
#include "darwin_priv.h"

/* sweet_gpu.c's UCHE_TRAP_BASE and the GPU clock it runs at (gpumhz=266) */
#define DARWIN_UCHE_TRAP_BASE 0x0001ffffffff0000ull
#define DARWIN_MAX_FREQ       266000000ull

static int
darwin_pipe_get_param(struct fd_pipe *pipe, enum fd_param_id param, uint64_t *value)
{
   struct darwin_pipe *darwin_pipe = to_darwin_pipe(pipe);
   switch (param) {
   case FD_DEVICE_ID:
   case FD_GPU_ID:
      *value = darwin_pipe->gpu_id;
      return 0;
   case FD_GMEM_SIZE:
      *value = darwin_pipe->gmem;
      return 0;
   case FD_GMEM_BASE:
      *value = darwin_pipe->gmem_base;
      return 0;
   case FD_CHIP_ID:
      *value = darwin_pipe->chip_id;
      return 0;
   case FD_MAX_FREQ:
      *value = DARWIN_MAX_FREQ;
      return 0;
   case FD_TIMESTAMP:
      return darwin_get_param(pipe->dev, SWEETGPU_PARAM_TIMESTAMP, value);
   case FD_NR_PRIORITIES:
      *value = 1;
      return 0;
   case FD_CTX_FAULTS:
   case FD_GLOBAL_FAULTS:
   case FD_SUSPEND_COUNT:
      *value = 0;
      return 0;
   case FD_VA_SIZE:
      return darwin_get_param(pipe->dev, SWEETGPU_PARAM_VA_SIZE, value);
   case FD_UCHE_TRAP_BASE:
      *value = DARWIN_UCHE_TRAP_BASE;
      return 0;
   default:
      ERROR_MSG("invalid param id: %d", param);
      return -1;
   }
}

static int
darwin_pipe_set_param(struct fd_pipe *pipe, enum fd_param_id param, uint64_t value)
{
   return -1;
}

/* for libsweetca's profile: kernel submits and waits, and the ticks spent in those calls */
uint64_t darwin_submits, darwin_submit_ticks, darwin_wait_ticks, darwin_waits;
uint32_t darwin_last_kfence, darwin_last_ufence;

static int
darwin_pipe_wait(struct fd_pipe *pipe, const struct fd_fence *fence, uint64_t timeout)
{
   uint64_t ms = timeout == OS_TIMEOUT_INFINITE ? 60000 : timeout / 1000000;
   uint64_t in[2] = { fence->kfence, ms };
   uint64_t t0 = mach_absolute_time();
   IOReturn ret = IOConnectCallScalarMethod(to_darwin_device(pipe->dev)->conn, SWEETGPU_WAIT,
                                            in, 2, NULL, NULL);
   __atomic_add_fetch(&darwin_wait_ticks, mach_absolute_time() - t0, __ATOMIC_RELAXED);
   __atomic_add_fetch(&darwin_waits, 1, __ATOMIC_RELAXED);
   if (ret == DARWIN_kIOReturnTimeout)
      return -ETIMEDOUT;
   if (ret) {
      ERROR_MSG("wait for fence %u failed: 0x%x", fence->kfence, ret);
      return -EIO;
   }
   return 0;
}

struct darwin_ib {
   uint64_t iova;
   uint32_t dwords;
   uint32_t pad;
};

/* As msm_ringbuffer_sp.c's flush_submit_list. Every buffer is always mapped,
 * so the BO table only tells the kernel which buffers' caches to maintain
 * around this job (j0035: header word 2 = handle count, handles after the IBs).
 * A table that would not fit IOKit's inline struct (4 KiB) is left out; the
 * kernel then maintains every buffer, as before.
 */
static int
flush_submit_list(struct list_head *submit_list)
{
   struct fd_submit_sp *fd_submit = to_fd_submit_sp(last_submit(submit_list));
   struct fd_pipe *pipe = fd_submit->base.pipe;
   unsigned nr_cmds = 0;

   foreach_submit (submit, submit_list)
      nr_cmds += to_fd_ringbuffer_sp(submit->primary)->u.nr_cmds;

   size_t len = 8 + nr_cmds * sizeof(struct darwin_ib);
   uint8_t *req = calloc(1, 4096 > len ? 4096 : len);
   if (!req)
      return -ENOMEM;
   *(uint32_t *)req = nr_cmds;
   struct darwin_ib *ibs = (struct darwin_ib *)(req + 8);

   unsigned cmd_idx = 0;
   foreach_submit_safe (submit, submit_list) {
      struct fd_ringbuffer_sp *deferred_primary = to_fd_ringbuffer_sp(submit->primary);

      for (unsigned i = 0; i < deferred_primary->u.nr_cmds; i++) {
         struct fd_bo *ring_bo = deferred_primary->u.cmds[i].ring_bo;
         fd_submit_append_bo(fd_submit, ring_bo);
         ibs[cmd_idx].iova = fd_bo_get_iova(ring_bo) + submit_offset(ring_bo, deferred_primary->offset);
         ibs[cmd_idx].dwords = deferred_primary->u.cmds[i].size / 4;
         cmd_idx++;
      }

      if (submit == last_submit(submit_list))
         break;

      struct fd_submit_sp *fd_deferred_submit = to_fd_submit_sp(submit);
      for (unsigned i = 0; i < fd_deferred_submit->nr_bos; i++)
         fd_submit_append_bo(fd_submit, fd_deferred_submit->bos[i]);

      list_del(&submit->node);
      fd_submit_del(submit);
   }

   if (len + 4ull * fd_submit->nr_bos <= 4096) {
      uint32_t *handles = (uint32_t *)(req + len);
      for (unsigned i = 0; i < fd_submit->nr_bos; i++)
         handles[i] = fd_submit->bos[i]->handle;
      ((uint32_t *)req)[1] = fd_submit->nr_bos;
      len += 4ull * fd_submit->nr_bos;
   }

   uint64_t seqno = 0;
   uint32_t nout = 1;
   uint64_t t0 = mach_absolute_time();
   IOReturn ret = IOConnectCallMethod(to_darwin_device(pipe->dev)->conn, SWEETGPU_SUBMIT, NULL, 0,
                                      req, len, &seqno, &nout, NULL, NULL);
   __atomic_add_fetch(&darwin_submit_ticks, mach_absolute_time() - t0, __ATOMIC_RELAXED);
   __atomic_add_fetch(&darwin_submits, 1, __ATOMIC_RELAXED);
   free(req);
   if (ret) {
      ERROR_MSG("submit of %u command buffers failed: 0x%x", nr_cmds, ret);
      return -EIO;
   }
   fd_submit->out_fence->kfence = (uint32_t)seqno;
   fd_submit->out_fence->fence_fd = -1;
   darwin_last_kfence = (uint32_t)seqno;
   darwin_last_ufence = fd_submit->base.fence;

   if (fd_submit->in_fence_fd != -1)
      close(fd_submit->in_fence_fd);

   return 0;
}

static struct fd_submit *
darwin_submit_sp_new(struct fd_pipe *pipe)
{
   return fd_submit_sp_new(pipe, flush_submit_list);
}

static void
darwin_pipe_destroy(struct fd_pipe *pipe)
{
   for (int i = 0; i < DARWIN_MAX_PIPES; i++) {
      struct fd_pipe *expected = pipe;
      __atomic_compare_exchange_n(&darwin_pipes[i], &expected, NULL, false, __ATOMIC_RELAXED,
                                  __ATOMIC_RELAXED);
   }
   fd_pipe_sp_ringpool_fini(pipe);
   free(to_darwin_pipe(pipe));
}

static const struct fd_pipe_funcs sp_funcs = {
   .ringbuffer_new_object = fd_ringbuffer_sp_new_object,
   .submit_new = darwin_submit_sp_new,
   .flush = fd_pipe_sp_flush,
   .get_param = darwin_pipe_get_param,
   .set_param = darwin_pipe_set_param,
   .wait = darwin_pipe_wait,
   .destroy = darwin_pipe_destroy,
};

struct fd_pipe *
darwin_pipe_new(struct fd_device *dev, enum fd_pipe_id id, uint32_t prio)
{
   if (id != FD_PIPE_3D)
      return NULL;

   struct darwin_pipe *darwin_pipe = calloc(1, sizeof(*darwin_pipe));
   if (!darwin_pipe)
      return NULL;

   struct fd_pipe *pipe = &darwin_pipe->base;
   pipe->dev = dev;
   pipe->funcs = &sp_funcs;
   /* SweetGPU has no implicit sync between processes: submits naming shared
    * buffers (imported IOSurfaces) can be merged like the others. Without
    * this, backboardd made a kernel submit for every ~1.5 draws.
    */
   pipe->no_implicit_sync = true;

   uint64_t v = 0;
   if (!darwin_get_param(dev, SWEETGPU_PARAM_GPU_ID, &v))
      darwin_pipe->gpu_id = v;
   if (!darwin_get_param(dev, SWEETGPU_PARAM_CHIP_ID, &v))
      darwin_pipe->chip_id = v;
   if (!darwin_get_param(dev, SWEETGPU_PARAM_GMEM_SIZE, &v))
      darwin_pipe->gmem = v;
   if (!darwin_get_param(dev, SWEETGPU_PARAM_GMEM_BASE, &v))
      darwin_pipe->gmem_base = v;

   if (!(darwin_pipe->gpu_id || darwin_pipe->chip_id)) {
      free(darwin_pipe);
      return NULL;
   }

   INFO_MSG("SweetGPU pipe: GPU-id %u, chip-id 0x%016" PRIx64 ", GMEM 0x%08x", darwin_pipe->gpu_id,
            darwin_pipe->chip_id, darwin_pipe->gmem);

   fd_pipe_sp_ringpool_init(pipe);

   for (int i = 0; i < DARWIN_MAX_PIPES; i++) {
      struct fd_pipe *expected = NULL;
      if (__atomic_compare_exchange_n(&darwin_pipes[i], &expected, pipe, false, __ATOMIC_RELAXED,
                                      __ATOMIC_RELAXED))
         break;
   }

   return pipe;
}
