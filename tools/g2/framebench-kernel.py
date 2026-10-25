#!/usr/bin/env python3
"""Apply framebench instrumentation to an isolated, already patched XNU tree.

This edits source files only. Generate the distributable j0099 patch with git diff
in that tree. Refuses changed/unexpected integration sites; never boots a device.
"""
from pathlib import Path
import argparse
import shutil


def apply(root):
    pending = {}
    def edit(name, replacements):
        path = root / name
        text = path.read_text()
        for old, new, count in replacements:
            actual = text.count(old)
            if actual != count:
                raise ValueError(f'{name}: expected {count} occurrences of {old[:85]!r}, got {actual}')
            text = text.replace(old, new)
        pending[path] = text

    edit('osfmk/arm64/sweet_prof.c', [
        ('static void\nsp_put(', 'static int sp_bench;\nstatic uint64_t sp_num(const char **s);\nstatic char sp_reply[128 * 1024];\n#include "sweet_bench.inc"\n\nstatic void\nsp_put(', 1),
        ('\tuint64_t len = sizeof(*r) + 8ull * (nk + nu);', '\tif (sp_bench) { bc_sample_put(r, kf, nk, uf, nu); return; }\n\tif (sp_buf == NULL) { return; } /* a late timer after a compact-only capture */\n\tuint64_t len = sizeof(*r) + 8ull * (nk + nu);', 1),
        ('\tthread_t th = current_thread();', '\tif (sp_bench && !bc_sampling(now)) {\n\t\trunning_timer_setup(processor, RUNNING_TIMER_SWEETPROF, NULL, sp_next(now), now);\n\t\treturn;\n\t}\n\tthread_t th = current_thread();', 1),
        ('\t\tif (task != kernel_task && sp_meta_used + 4096 < sp_meta_size)', '\t\tif (task != kernel_task && (!sp_bench || sp_named(p)) && sp_meta_used + 4096 < sp_meta_size)', 1),
        ('\t\tif (sp_census_period != 0) {', '''\t\tif (sp_bench && now - bc_last_memory >= sp_period * 500) {
\t\t\tfor (unsigned i = 0; i < nt; i++) { task_deallocate(targets[i]); }
\t\t\tnt = 0;
\t\t\tlck_mtx_lock(&tasks_threads_lock);
\t\t\tqueue_iterate(&tasks, task, task_t, tasks) {
\t\t\t\tvoid *p = get_bsdtask_info(task);
\t\t\t\tif (nt < SP_TASKS && sp_named(p)) { task_reference(task); targets[nt++] = task; }
\t\t\t}
\t\t\tlck_mtx_unlock(&tasks_threads_lock);
\t\t\tbc_memory_snapshot(now);
\t\t}
\t\tif (sp_census_period != 0 && (!sp_bench || bc_sampling(now))) {''', 1),
        ('\tsp_write_meta();', '\tif (sp_bench) { os_atomic_store(&bc_active, 0, release); }\n\tsp_write_meta();\n\tsp_bench = 0;', 1),
        ('static char sp_reply[128 * 1024];\n\n/* bsd/dev', '/* bsd/dev', 1),
        ('\tif (strncmp(line, "prof ", 5) != 0)', '\tconst char *bench = bc_cmd(line);\n\tif (bench != NULL) { return bench; }\n\tif (strncmp(line, "prof ", 5) != 0)', 1),
        ('\t\tif (sp_buf == NULL) {\n\t\t\tvm_offset_t b = 0, m = 0;', '\t\tif ((!sp_bench && sp_buf == NULL) || sp_meta == NULL) {\n\t\t\tvm_offset_t b = (vm_offset_t)sp_buf, m = (vm_offset_t)sp_meta;', 1),
        ('if (kmem_alloc(kernel_map, &b, sp_size, KMA_DATA | KMA_ZERO, VM_KERN_MEMORY_DIAG) != KERN_SUCCESS ||\n\t\t\t    kmem_alloc(kernel_map, &m, sp_meta_size, KMA_DATA | KMA_ZERO, VM_KERN_MEMORY_DIAG) != KERN_SUCCESS)', 'if ((!sp_bench && b == 0 && kmem_alloc(kernel_map, &b, sp_size, KMA_DATA | KMA_ZERO, VM_KERN_MEMORY_DIAG) != KERN_SUCCESS) ||\n\t\t\t    (m == 0 && kmem_alloc(kernel_map, &m, sp_meta_size, KMA_DATA | KMA_ZERO, VM_KERN_MEMORY_DIAG) != KERN_SUCCESS))', 1),
        ('sp_epoch = mach_absolute_time();', 'sp_epoch = sp_bench ? bc_epoch : mach_absolute_time();', 1),
        ('sp_end = sp_epoch + len;', 'sp_end = sp_bench ? bc_end : sp_epoch + len;', 1),
    ])

    edit('bsd/dev/sweet_usb.c', [
        ('static char ud_cmd_line[2048], ud_cmd_reply[8192];', 'static char ud_cmd_line[2048], ud_cmd_reply[8192];\nextern const char *sweet_bench_blob(const char *, const void **, size_t *);', 1),
        ('\t\tbool reboot = strcmp(line, "reboot") == 0;', '\t\tstruct timeval bt = { .tv_sec = 5, .tv_usec = 0 };\n\t\t(void)sock_setsockopt(cs, SOL_SOCKET, SO_SNDTIMEO, &bt, sizeof(bt));\n\t\tconst void *binary = NULL;\n\t\tsize_t binary_len = 0;\n\t\tconst char *binary_header = sweet_bench_blob(line, &binary, &binary_len);\n\t\tbool reboot = strcmp(line, "reboot") == 0;', 1),
        ('\t\tconst char *prof = reboot ? NULL : sweet_prof_cmd(line);', '\t\tconst char *prof = binary_header != NULL ? binary_header : reboot ? NULL : sweet_prof_cmd(line);', 1),
        ('\t\tsock_close(cs);\n\t\tif (reboot)', '\t\tfor (size_t off = 0; off < binary_len;) {\n\t\t\tsize_t part = binary_len - off;\n\t\t\tif (part > 65536) { part = 65536; }\n\t\t\tstruct iovec iov = { .iov_base = (char *)binary + off, .iov_len = part };\n\t\t\tstruct msghdr msg = { .msg_iov = &iov, .msg_iovlen = 1 };\n\t\t\tsize_t sent = 0;\n\t\t\tif (sock_send(cs, &msg, 0, &sent) != 0 || sent == 0) { break; }\n\t\t\toff += sent;\n\t\t}\n\t\tsock_close(cs);\n\t\tif (reboot)', 1),
    ])
    decl = '\nextern "C" void sweet_bench_event(uint32_t, uint32_t, uint32_t, uint32_t, uint32_t);\nextern "C" void sweet_bench_alloc(uint32_t, int64_t);\nextern "C" bool sweet_bench_enabled(void);\n'
    edit('iokit/Kernel/arm/SweetFramebuffer.cpp', [
        ('#include "SweetSurface.h"', '#include "SweetSurface.h"' + decl, 1),
        ('\tsweet_fps_count();', '\tsweet_fps_count();\n\tsweet_bench_event(11, get32(rec, 0x50), get32(rec, 0x54), get32(rec, 0x104), 0);', 1),
        ('\t\tnoteShown(get32(rec, 0x50));\n\t\tstatic uint32_t frames', '\t\tnoteShown(get32(rec, 0x50));\n\t\tsweet_bench_event(12, get32(rec, 0x50), inPlace, 0, 0);\n\t\tstatic uint32_t frames', 1),
        ('\t\t\tscanScaled(pa, s->bytesPerRow);', '\t\t\tsweet_bench_event(13, get32(rec, 0x50), s->id, s->gpuSeqno, 1);\n\t\t\tscanScaled(pa, s->bytesPerRow);', 1),
        ('\tfShownID = fLatchID;\n\tfLatchID = 0;', '\tsweet_bench_event((fCtl0[0x18 / 4] & fFlushMask) ? 15 : 14, fLatchID, fShownID, (uint32_t)(ns / 1000), fCtl0[0x18 / 4]);\n\tfShownID = fLatchID;\n\tfLatchID = 0;', 1),
        ('\t\tfShownID = id;          /*', '\t\tsweet_bench_event(16, id, 0, 0, 0);\n\t\tfShownID = id;          /*', 1),
        ('\tsweet_fps_tick = now;', '\tsweet_fps_tick = now;\n\tif (sweet_bench_enabled() && fb->fIntf1 != NULL) {\n\t\tvolatile uint32_t *r = fb->fIntf1 + 0x800 / 4;\n\t\tsweet_bench_event(17, r[0xac / 4], r[0xb0 / 4] & 0xffff, fb->fVTotal, fb->fPanelUS);\n\t}', 1),
        ('\t\t\tsweet_fb_wait_us += ns / 1000;', '\t\t\tif (ns > 100000) { sweet_bench_event(18, id, (uint32_t)(ns / 1000), done, 0); }\n\t\t\tsweet_fb_wait_us += ns / 1000;', 1),
        ('\t\t\t*us += ns / 1000;', '\t\t\tif (ns > 100000) { sweet_bench_event(19, s->id, (uint32_t)(ns / 1000), shown, retiring); }\n\t\t\t*us += ns / 1000;', 1),
        ('\t\tout[0] = ++fFB->fSwapID;', '\t\tout[0] = ++fFB->fSwapID;\n\t\tsweet_bench_event(10, (uint32_t)out[0], 0, 0, 0);', 1),
    ])
    edit('bsd/dev/sweet_gpu.c', [
        ('int sweet_gpu_submit(const uint64_t *iova,', '#include <os/atomic_private.h>\nint sweet_gpu_submit(const uint64_t *iova,', 1),
        ('int sweet_gpu_submit(const uint64_t *iova,', 'extern void sweet_bench_event(uint32_t, uint32_t, uint32_t, uint32_t, uint32_t);\nint sweet_gpu_submit(const uint64_t *iova,', 1),
        ('\tgpu_wr(CP_RB_WPTR, sg.wptr);\n\tlck_mtx_unlock(gpu_lock);', '\tgpu_wr(CP_RB_WPTR, sg.wptr);\n\tsweet_bench_event(20, *seqno, n, sg.wptr, 0);\n\tlck_mtx_unlock(gpu_lock);', 1),
        ('\treturn sg.mem[FENCE_OFF / 4];', '\tuint32_t done = sg.mem[FENCE_OFF / 4];\n\tif (sweet_bench_enabled()) {\n\t\tstatic volatile uint32_t observed;\n\t\tuint32_t old = os_atomic_load(&observed, relaxed);\n\t\tif ((int32_t)(done - old) > 0 && os_atomic_cmpxchg(&observed, old, done, relaxed)) {\n\t\t\tsweet_bench_event(21, done, old, 0, 0);\n\t\t}\n\t}\n\treturn done;', 1),
        ('extern void sweet_bench_event(uint32_t, uint32_t, uint32_t, uint32_t, uint32_t);', 'extern bool sweet_bench_enabled(void);\nextern void sweet_bench_event(uint32_t, uint32_t, uint32_t, uint32_t, uint32_t);', 1),
        ('\tuint64_t deadline;\n\tclock_interval_to_deadline(timeout_ms', '\tuint64_t deadline;\n\tsweet_bench_event(23, seqno, timeout_ms, 0, 0);\n\tclock_interval_to_deadline(timeout_ms', 1),
        ('\t\t\treturn ETIMEDOUT;\n\t\t}\n\t\tdelay(50);', '\t\t\tsweet_bench_event(24, seqno, ETIMEDOUT, 0, 0);\n\t\t\treturn ETIMEDOUT;\n\t\t}\n\t\tdelay(50);', 1),
        ('\t\tdelay(50);\n\t}\n\treturn 0;', '\t\tdelay(50);\n\t}\n\tsweet_bench_event(24, seqno, 0, 0, 0);\n\treturn 0;', 1),
    ])
    edit('iokit/Kernel/arm/SweetGPU.cpp', [
        ('#include "SweetSurface.h"', '#include "SweetSurface.h"' + decl, 1),
        ('\tuint64_t iova, size;', '\tuint64_t iova, size;\n\tbool benchCounted = false;', 1),
        ('\tuint64_t pa = topaz_gpu_pool_alloc(size, va);', '\tuint64_t pa = topaz_gpu_pool_alloc(size, va);\n\tif (pa != 0) { sweet_bench_alloc(4, (int64_t)size); }', 1),
        ('\ttopaz_gpu_pool_free(pa, size);\n\tIOLockUnlock(sweet_gpu_pool_lock);', '\ttopaz_gpu_pool_free(pa, size);\n\tsweet_bench_alloc(4, -(int64_t)size);\n\tIOLockUnlock(sweet_gpu_pool_lock);', 1),
        ('\t\t\tb->poolPA = pa;', '\t\t\tb->poolPA = pa;\n\t\t\tsweet_bench_alloc(4, (int64_t)size);', 1),
        ('\t\t\ttopaz_gpu_pool_free(poolPA, size);', '\t\t\ttopaz_gpu_pool_free(poolPA, size);\n\t\t\tsweet_bench_alloc(4, -(int64_t)size);', 1),
        ('SweetGPUBuffer::free()\n{', 'SweetGPUBuffer::free()\n{\n\tsweet_bench_alloc(7, 1);', 1),
        ('\tOSObject::free();', '\tif (benchCounted) {\n\t\tsweet_bench_alloc(0, -1);\n\t\tsweet_bench_alloc(1, -(int64_t)size);\n\t}\n\tsweet_bench_alloc(7, -1);\n\tOSObject::free();', 1),
        ('SweetGPUUserClient::addBuffer(SweetGPUBuffer *b)\n{', 'SweetGPUUserClient::addBuffer(SweetGPUBuffer *b)\n{\n\tif (!b->benchCounted) {\n\t\tb->benchCounted = true;\n\t\tsweet_bench_alloc(0, 1);\n\t\tsweet_bench_alloc(1, (int64_t)b->size);\n\t}', 1),
        ('\t\t\treturn kIOReturnNoMemory;\n\t\t}\n\t\tuint32_t handle', '\t\t\tsweet_bench_alloc(6, 1);\n\t\t\treturn kIOReturnNoMemory;\n\t\t}\n\t\tuint32_t handle', 1),
        ('\t\t\t\t\tjs->gpuSeqno = seqno;', '\t\t\t\t\tsweet_bench_event(22, seqno, js->id, (uint32_t)job->bufs[i]->size, 0);\n\t\t\t\t\tjs->gpuSeqno = seqno;', 1),
    ])
    edit('iokit/Kernel/arm/SweetSurface.h', [
        ('\tvoid free() APPLE_KEXT_OVERRIDE;', '\tuint64_t benchBytes = 0;\n\tbool benchCounted = false;\n\tvoid free() APPLE_KEXT_OVERRIDE;', 1),
    ])
    edit('iokit/Kernel/arm/SweetSurface.cpp', [
        ('#include "SweetSurface.h"', '#include "SweetSurface.h"' + decl, 1),
        ('\tscanoutSlot = -1;\n\tOSObject::free();', '\tscanoutSlot = -1;\n\tif (benchCounted) { sweet_bench_alloc(2, -1); sweet_bench_alloc(3, -(int64_t)benchBytes); }\n\tOSObject::free();', 1),
        ('\t\t\ts->id = id;', '\t\t\tif (!s->benchCounted) {\n\t\t\t\ts->benchCounted = true; s->benchBytes = s->allocSize;\n\t\t\t\tsweet_bench_alloc(2, 1); sweet_bench_alloc(3, (int64_t)s->benchBytes);\n\t\t\t}\n\t\t\ts->id = id;', 1),
    ])
    for path, text in pending.items():
        path.write_text(text)
    shutil.copyfile(Path(__file__).with_name('framebench_kernel.inc'), root / 'osfmk/arm64/sweet_bench.inc')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('tree', type=Path)
    apply(p.parse_args().tree.resolve())
