/*
 * Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 *
 * Stand-in for libdrm's xf86drm.h on Apple platforms (ios-jasmine): there is
 * no DRM device, freedreno runs on its darwin backend (src/freedreno/drm/
 * darwin). The common freedreno code and the msm backend still reference a
 * few libdrm calls; here they all fail with -ENODEV.
 */

#ifndef _XF86DRM_H_
#define _XF86DRM_H_

#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

#include "drm-uapi/drm.h"

#define DRM_NODE_PRIMARY 0
#define DRM_NODE_CONTROL 1
#define DRM_NODE_RENDER  2
#define DRM_NODE_MAX     3
#define DRM_BUS_PCI      0
#define DRM_BUS_PLATFORM 2

typedef struct _drmVersion {
   int version_major;
   int version_minor;
   int version_patchlevel;
   int name_len;
   char *name;
   int date_len;
   char *date;
   int desc_len;
   char *desc;
} drmVersion, *drmVersionPtr;

typedef struct _drmPlatformDeviceInfo {
   char **compatible;
} drmPlatformDeviceInfo, *drmPlatformDeviceInfoPtr;

typedef struct _drmDevice {
   char **nodes;
   int available_nodes;
   int bustype;
   union {
      drmPlatformDeviceInfoPtr platform;
   } deviceinfo;
} drmDevice, *drmDevicePtr;

static inline drmVersionPtr drmGetVersion(int fd) { (void)fd; errno = ENODEV; return NULL; }
static inline void drmFreeVersion(drmVersionPtr v) { (void)v; }
static inline int drmIoctl(int fd, unsigned long request, void *arg)
{ (void)fd; (void)request; (void)arg; return -ENODEV; }
static inline int drmCommandWrite(int fd, unsigned long index, void *data, unsigned long size)
{ (void)fd; (void)index; (void)data; (void)size; return -ENODEV; }
static inline int drmCommandWriteRead(int fd, unsigned long index, void *data, unsigned long size)
{ (void)fd; (void)index; (void)data; (void)size; return -ENODEV; }
static inline int drmCommandRead(int fd, unsigned long index, void *data, unsigned long size)
{ (void)fd; (void)index; (void)data; (void)size; return -ENODEV; }
static inline int drmGetCap(int fd, uint64_t capability, uint64_t *value)
{ (void)fd; (void)capability; (void)value; return -ENODEV; }
static inline int drmOpenWithType(const char *name, const char *busid, int type)
{ (void)name; (void)busid; (void)type; return -ENODEV; }
static inline int drmPrimeHandleToFD(int fd, uint32_t handle, uint32_t flags, int *prime_fd)
{ (void)fd; (void)handle; (void)flags; (void)prime_fd; return -ENODEV; }
static inline int drmPrimeFDToHandle(int fd, int prime_fd, uint32_t *handle)
{ (void)fd; (void)prime_fd; (void)handle; return -ENODEV; }
static inline int drmSyncobjCreate(int fd, uint32_t flags, uint32_t *handle)
{ (void)fd; (void)flags; (void)handle; return -ENODEV; }
static inline int drmSyncobjDestroy(int fd, uint32_t handle)
{ (void)fd; (void)handle; return -ENODEV; }
static inline int drmSyncobjFDToHandle(int fd, int obj_fd, uint32_t *handle)
{ (void)fd; (void)obj_fd; (void)handle; return -ENODEV; }
static inline int drmSyncobjExportSyncFile(int fd, uint32_t handle, int *sync_file_fd)
{ (void)fd; (void)handle; (void)sync_file_fd; return -ENODEV; }
static inline int drmSyncobjImportSyncFile(int fd, uint32_t handle, int sync_file_fd)
{ (void)fd; (void)handle; (void)sync_file_fd; return -ENODEV; }
static inline int drmSyncobjReset(int fd, const uint32_t *handles, uint32_t handle_count)
{ (void)fd; (void)handles; (void)handle_count; return -ENODEV; }
static inline int drmGetDevice2(int fd, uint32_t flags, drmDevicePtr *device)
{ (void)fd; (void)flags; (void)device; return -ENODEV; }
static inline void drmFreeDevice(drmDevicePtr *device) { (void)device; }

#endif /* _XF86DRM_H_ */
