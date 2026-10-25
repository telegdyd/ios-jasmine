"""Put the freedreno darwin backend into a Mesa tree (argv[1])."""
import pathlib
import shutil
import sys

root = pathlib.Path(sys.argv[1])
here = pathlib.Path(__file__).parent
drm = root / 'src/freedreno/drm'
(drm / 'darwin').mkdir(exist_ok=True)
for f in ('darwin_priv.h', 'darwin_device.c', 'darwin_bo.c', 'darwin_pipe.c', 'sweet_profile.c'):
    (drm / 'darwin' / f).write_text((here / f).read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
(root / 'src/util/sweet_profile.h').write_text((here / 'sweet_profile.h').read_text(encoding='utf-8'),
                                             encoding='utf-8', newline='\n')


def sub(rel, old, new):
    p = root / rel
    s = p.read_text(encoding='utf-8')
    if s.count(old) != 1:
        sys.exit(f'{rel}: expected one match, found {s.count(old)}: {old[:70]!r}')
    p.write_text(s.replace(old, new), encoding='utf-8', newline='\n')


sub('src/freedreno/drm/freedreno_device.c',
    'struct fd_device *msm_device_new(int fd, drmVersionPtr version);\n',
    'struct fd_device *msm_device_new(int fd, drmVersionPtr version);\n'
    '#ifdef __APPLE__\n'
    '/* darwin/: the SweetGPU IOKit driver of ios-jasmine; the fd is not used */\n'
    'struct fd_device *darwin_device_new(int fd);\n'
    '#endif\n')
sub('src/freedreno/drm/freedreno_device.c',
    '''   os_get_page_size(&os_page_size);

   /* figure out if we are kgsl or msm drm driver: */
   version = drmGetVersion(fd);''',
    '''   os_get_page_size(&os_page_size);

#ifdef __APPLE__
   (void)version;
   dev = darwin_device_new(fd);
   if (!dev)
      return NULL;
   /* Sub-allocation heaps for rings and small buffers, as on a6xx+ (PERF-TASKS task 4):
    * without them every batch's command rings and every small buffer is a SweetGPU
    * create + map + free whenever the caches run dry. Upstream keeps a5xx off them
    * because its userspace fences looked unreliable there; SweetGPU's are exact
    * (pipe control fence == last_fence after every wait, round t4d3), and the bo and
    * ring caches already rely on the same fences.
    */
   use_heap = true;
   goto init;
#endif

   /* figure out if we are kgsl or msm drm driver: */
   version = drmGetVersion(fd);''')
sub('src/freedreno/drm/freedreno_device.c',
    '''   if (!dev)
      return NULL;

   fd_drm_perfetto_init();''',
    '''   if (!dev)
      return NULL;

#ifdef __APPLE__
init:
#endif
   fd_drm_perfetto_init();''')
sub('src/freedreno/drm/meson.build',
    "libfreedreno_drm_files += libfreedreno_drm_msm_files\n",
    "libfreedreno_drm_files += libfreedreno_drm_msm_files\n\n"
    "# ios-jasmine: the SweetGPU IOKit driver instead of a DRM device\n"
    "if host_machine.system() == 'darwin'\n"
    "  libfreedreno_drm_files += files(\n"
    "    'darwin/darwin_bo.c',\n"
    "    'darwin/darwin_device.c',\n"
    "    'darwin/darwin_pipe.c',\n"
    "    'darwin/darwin_priv.h',\n"
    "    'darwin/sweet_profile.c',\n"
    "  )\n"
    "  libfreedreno_drm_deps += dependency('appleframeworks', modules : ['IOKit', 'CoreFoundation'])\n"
    "endif\n")
# libdrm stand-in for Apple platforms (include/darwin-drm/xf86drm.h), on the include path there
(root / 'include/darwin-drm').mkdir(exist_ok=True)
(root / 'include/darwin-drm/xf86drm.h').write_text((here / 'xf86drm.h').read_text(encoding='utf-8'),
                                                 encoding='utf-8', newline='\n')
sub('meson.build',
    "system_has_kms_drm = ['openbsd',",
    "# ios-jasmine: no libdrm on Apple platforms; freedreno uses include/darwin-drm/xf86drm.h\n"
    "if host_machine.system() == 'darwin'\n"
    "  pre_args += '-I' + (meson.current_source_dir() / 'include' / 'darwin-drm')\n"
    "endif\n"
    "system_has_kms_drm = ['openbsd',")
# freedreno on Darwin is a graphics driver even before any GL frontend is built:
# full NIR and gallium's shader helpers (u_simple_shaders, blitter) are needed
sub('meson.build',
    "with_gfx_compute = [\n  with_any_opengl,\n",
    "with_gfx_compute = [\n  with_any_opengl,\n  host_machine.system() == 'darwin' and with_gallium_freedreno,\n")
# Darwin has no KMS/DRM, but its freedreno drm layer is the darwin backend
sub('src/freedreno/meson.build',
    "if system_has_kms_drm\n  subdir('drm')\nendif\n",
    "if system_has_kms_drm or host_machine.system() == 'darwin'\n  subdir('drm')\nendif\n")
# sweetgpu_fdtest: the first on-device test (gallium only), next to gmemtool
(root / 'src/gallium/drivers/freedreno/sweetgpu_fdtest.c').write_text(
    (here / 'sweetgpu_fdtest.c').read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
p = root / 'src/gallium/drivers/freedreno/meson.build'
s = p.read_text(encoding='utf-8')
s += """
# ios-jasmine: the first test of freedreno on the SweetGPU kernel driver
if host_machine.system() == 'darwin'
  sweetgpu_fdtest = executable(
    'sweetgpu_fdtest',
    [
      'sweetgpu_fdtest.c',
      # freedreno references renderonly (KMS scanout buffers, unused here);
      # libgallium has it only with libdrm
      '../../auxiliary/renderonly/renderonly.c',
      freedreno_tracepoints[1],
      freedreno_xml_header_files,
    ],
    include_directories : [freedreno_includes, inc_util, inc_gallium_aux],
    dependencies : [
      idep_nir,
      idep_mesautil,
      idep_u_tracepoints,
      idep_xmlconfig,
    ],
    link_with : [
      libfreedreno,
      libfreedreno_drm,
      libfreedreno_ir2,
      libfreedreno_ir3,
      libfreedreno_layout,
      libgallium,
      libfreedreno_perfcntrs,
    ],
    install : false,
  )
endif
"""
p.write_text(s, encoding='utf-8', newline='\n')
# a5xx: sample and render linear IOSurfaces whose rows are 64-byte aligned (CoreAnimation's are,
# the 256 bytes of gmem_align_w x cpp are for GMEM resolve, which we do not use there: sysmem).
# Found by ios-sailfish (Pixel 1) with the same driver.
sub('src/gallium/drivers/freedreno/freedreno_resource.c',
    '''      rsc->layout.pitchalign = MAX2(rsc->layout.pitchalign, 5);

   if (rsc->layout.pitch0 < (prsc->width0 * rsc->layout.cpp) ||''',
    '''      rsc->layout.pitchalign = MAX2(rsc->layout.pitchalign, 5);

#ifdef __APPLE__
   /* ios-jasmine: linear a5xx surfaces with 64-byte aligned rows are used in place */
   if (is_a5xx(screen) && handle->modifier == DRM_FORMAT_MOD_LINEAR &&
       handle->stride % 64 == 0)
      rsc->layout.pitchalign = 6;
#endif

   if (rsc->layout.pitch0 < (prsc->width0 * rsc->layout.cpp) ||''')
# PERF-TASKS task 4 diagnostic: the buffer caches' bucket counters (FD_BO_CACHE_STATS) without its
# per-miss log lines, and why a lookup misses: a busy entry at the bucket's head (with that entry's
# fence and its pipe's control fence) or idle entries with other flags. libsweetca logs the sums.
sub('src/freedreno/drm/freedreno_priv.h',
    '''   int count, hits, misses, expired;
   struct list_head list;
};''',
    '''   int count, hits, misses, expired;
#ifdef __APPLE__
   int busy, flagskip;
#endif
   struct list_head list;
};''')
sub('src/freedreno/drm/freedreno_priv.h',
    '''   int num_buckets;
   time_t time;
};''',
    '''   int num_buckets;
   time_t time;
#ifdef __APPLE__
   uint32_t diag_ufence, diag_ctrl, diag_want, diag_had;
#endif
};''')
sub('src/freedreno/drm/freedreno_bo_cache.c',
    '''#define FD_BO_CACHE_STATS 0

#define BO_CACHE_LOG(cache, fmt, ...) do {                      \\
      if (FD_BO_CACHE_STATS) {                                  \\''',
    '''#ifdef __APPLE__
/* ios-jasmine: counters on, log lines off (libsweetca logs the sums) */
#define FD_BO_CACHE_STATS 1
#define FD_BO_CACHE_LOG 0
#else
#define FD_BO_CACHE_STATS 0
#define FD_BO_CACHE_LOG FD_BO_CACHE_STATS
#endif

#define BO_CACHE_LOG(cache, fmt, ...) do {                      \\
      if (FD_BO_CACHE_LOG) {                                    \\''')
sub('src/freedreno/drm/freedreno_bo_cache.c',
    '''#define BO_CACHE_DEC(bucket, field) do {                        \\
      if (FD_BO_CACHE_STATS) {                                  \\
         (bucket)->field++;                                     \\''',
    '''#define BO_CACHE_DEC(bucket, field) do {                        \\
      if (FD_BO_CACHE_STATS) {                                  \\
         (bucket)->field--;                                     \\''')
sub('src/freedreno/drm/freedreno_bo_cache.c',
    '''static void
dump_cache_stats(struct fd_bo_cache *cache)
{
   if (!FD_BO_CACHE_STATS)
      return;''',
    '''static void
dump_cache_stats(struct fd_bo_cache *cache)
{
   if (!FD_BO_CACHE_LOG)
      return;''')
sub('src/freedreno/drm/freedreno_bo_cache.c',
    '''static struct fd_bo *
find_in_bucket(struct fd_bo_bucket *bucket, uint32_t flags)
{''',
    '''static struct fd_bo *
find_in_bucket(struct fd_bo_cache *cache, struct fd_bo_bucket *bucket, uint32_t flags)
{''')
sub('src/freedreno/drm/freedreno_bo_cache.c',
    '''      if (fd_bo_state(entry) != FD_BO_STATE_IDLE) {
         break;
      }
      if (entry->alloc_flags == flags) {
         bo = entry;
         bo_remove_from_bucket(bucket, bo);
         break;
      }
   }''',
    '''      if (fd_bo_state(entry) != FD_BO_STATE_IDLE) {
#ifdef __APPLE__
         bucket->busy++;
         simple_mtx_lock(&fence_lock);
         if (entry->nr_fences) {
            cache->diag_ufence = entry->fences[0]->ufence;
            cache->diag_ctrl = entry->fences[0]->pipe->control->fence;
         }
         simple_mtx_unlock(&fence_lock);
#endif
         break;
      }
#ifdef __APPLE__
      /* the darwin backend allocates the same memory whatever the hints say */
      if (!((entry->alloc_flags ^ flags) & ~_FD_BO_HINTS)) {
#else
      if (entry->alloc_flags == flags) {
#endif
         bo = entry;
         bo_remove_from_bucket(bucket, bo);
         break;
      }
#ifdef __APPLE__
      bucket->flagskip++;
      cache->diag_want = flags;
      cache->diag_had = entry->alloc_flags;
#endif
   }''')
sub('src/freedreno/drm/freedreno_bo_cache.c',
    '''      bo = find_in_bucket(bucket, flags);''',
    '''      bo = find_in_bucket(cache, bucket, flags);''')
# sweetgl: GL ES contexts on the freedreno screen without EGL/DRI, and its test
sgl = root / 'src/gallium/frontends/sweetgl'
sgl.mkdir(exist_ok=True)
for f in ('meson.build', 'sweetgl.h', 'sweetgl.c', 'sweetgl_tickets.inc', 'sweetgl_gles2.c', 'sweetgpu_gltest.c', 'sweetca.c', 'sweetca_pass_trace.inc',
          'sweetca_slots.inc'):
    (sgl / f).write_text((here / 'sweetgl' / f).read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
p = root / 'src/gallium/meson.build'
s = p.read_text(encoding='utf-8')
s += """
# ios-jasmine: GL ES on freedreno without EGL or DRI (sweetgl)
if with_gallium_freedreno and with_gles2 and not with_dri
  subdir('frontends/sweetgl')
endif
"""
p.write_text(s, encoding='utf-8', newline='\n')
print('applied')
