/*
 * Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 *
 * freedreno backend for the SweetGPU kernel driver of ios-jasmine (XNU on a
 * Snapdragon 660, Adreno 512): instead of Linux's msm DRM ioctls, an IOKit
 * user client (iokit/Kernel/arm/SweetGPU.cpp in ios-jasmine's j0026):
 *
 *   selector 0  get param     in: param                 out: value
 *   selector 1  buffer new    in: size, flags           out: handle, GPU VA
 *   selector 2  buffer free   in: handle
 *   selector 3  submit        struct in: u32 n, u32 0, n x {u64 iova, u32 dwords, u32 0}
 *                                                       out: seqno
 *   selector 4  wait          in: seqno, timeout ms     kIOReturnTimeout
 *   selector 5  completed                               out: last seqno done
 *   selector 6  import IOSurface  in: id, flags     out: handle, GPU VA, size, offset
 *   selector 7  buffer info   in: handle                out: GPU VA, size
 *   memory type = handle      IOConnectMapMemory64 maps a buffer
 *
 * Shared buffers are IOSurfaces (j0032): on Darwin a WINSYS_HANDLE_TYPE_FD
 * handle carries an IOSurface id instead of a dma-buf fd, and the kernel
 * maps the surface's own memory into the GPU address space.
 *
 * Every buffer stays mapped in the one GPU address space, so submits carry
 * only the command buffers' GPU addresses (no BO list, no relocations).
 */

#ifndef DARWIN_PRIV_H_
#define DARWIN_PRIV_H_

#include "freedreno_drmif.h"
#include "freedreno_priv.h"

#include <mach/mach.h>

/* IOKit user-client calls: the library is in the iPhoneOS SDK, its headers are not */
typedef mach_port_t io_object_t;
typedef io_object_t io_service_t;
typedef io_object_t io_connect_t;
typedef int IOReturn;
typedef struct __CFDictionary *CFMutableDictionaryRef;
extern const mach_port_t kIOMainPortDefault;
CFMutableDictionaryRef IOServiceMatching(const char *name);
io_service_t IOServiceGetMatchingService(mach_port_t main, CFMutableDictionaryRef matching);
IOReturn IOServiceOpen(io_service_t service, task_port_t owning, uint32_t type, io_connect_t *connect);
IOReturn IOServiceClose(io_connect_t connect);
IOReturn IOObjectRelease(io_object_t object);
IOReturn IOConnectCallScalarMethod(io_connect_t connection, uint32_t selector, const uint64_t *input,
                                   uint32_t inputCnt, uint64_t *output, uint32_t *outputCnt);
IOReturn IOConnectCallMethod(io_connect_t connection, uint32_t selector, const uint64_t *input,
                             uint32_t inputCnt, const void *inputStruct, size_t inputStructCnt,
                             uint64_t *output, uint32_t *outputCnt, void *outputStruct,
                             size_t *outputStructCnt);
IOReturn IOConnectMapMemory64(io_connect_t connect, uint32_t memoryType, task_port_t intoTask,
                              mach_vm_address_t *atAddress, mach_vm_size_t *ofSize, uint32_t options);
IOReturn IOConnectUnmapMemory64(io_connect_t connect, uint32_t memoryType, task_port_t fromTask,
                                mach_vm_address_t atAddress);
#define DARWIN_kIOMapAnywhere      0x00000001
#define DARWIN_kIOReturnTimeout    ((IOReturn)0xe00002d6)

enum sweetgpu_selector {
   SWEETGPU_GET_PARAM = 0,
   SWEETGPU_BUFFER_NEW = 1,
   SWEETGPU_BUFFER_FREE = 2,
   SWEETGPU_SUBMIT = 3,
   SWEETGPU_WAIT = 4,
   SWEETGPU_COMPLETED = 5,
   SWEETGPU_IMPORT_IOSURFACE = 6,
   SWEETGPU_BUFFER_INFO = 7,
};

/* sweet_gpu_param() numbers */
enum sweetgpu_param {
   SWEETGPU_PARAM_READY = 0,
   SWEETGPU_PARAM_CHIP_ID = 1,
   SWEETGPU_PARAM_GPU_ID = 2,
   SWEETGPU_PARAM_GMEM_SIZE = 3,
   SWEETGPU_PARAM_GMEM_BASE = 4,
   SWEETGPU_PARAM_VA_START = 5,
   SWEETGPU_PARAM_VA_SIZE = 6,
   SWEETGPU_PARAM_NR_RINGS = 7,
   SWEETGPU_PARAM_TIMESTAMP = 8,
};

struct darwin_device {
   struct fd_device base;
   io_connect_t conn;
};
FD_DEFINE_CAST(fd_device, darwin_device);

struct darwin_pipe {
   struct fd_pipe base;
   uint32_t gpu_id;
   uint64_t chip_id;
   uint64_t gmem_base;
   uint32_t gmem;
};
FD_DEFINE_CAST(fd_pipe, darwin_pipe);

struct darwin_bo {
   struct fd_bo base;
   uint64_t iova;
};
FD_DEFINE_CAST(fd_bo, darwin_bo);

struct fd_device *darwin_device_new(int fd);
struct fd_pipe *darwin_pipe_new(struct fd_device *dev, enum fd_pipe_id id, uint32_t prio);
struct fd_bo *darwin_bo_new(struct fd_device *dev, uint32_t size, uint32_t flags);
struct fd_bo *darwin_bo_from_handle(struct fd_device *dev, uint32_t size, uint32_t handle);
struct fd_bo *darwin_bo_from_iosurface(struct fd_device *dev, int iosurface_id);
int darwin_get_param(struct fd_device *dev, enum sweetgpu_param param, uint64_t *value);

/* darwin_pipe.c: kernel submits and waits and the mach ticks spent in them (libsweetca's profile) */
extern uint64_t darwin_submits, darwin_submit_ticks, darwin_wait_ticks, darwin_waits;

#endif /* DARWIN_PRIV_H_ */
