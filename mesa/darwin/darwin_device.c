/*
 * Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 */

#include "darwin_priv.h"

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

   return dev;
}
