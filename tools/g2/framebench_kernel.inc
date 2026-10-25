/* SPDX-License-Identifier: MIT
 * Included by sweet_prof.c; no new kernel build target. Protocol v1 is private
 * to tools/g2/framebench.py. All capture allocations are bounded; no disk I/O.
 */
#include <vm/vm_page.h>
#include <sys/proc.h>

#define BC_EVENTS 131072u
#define BC_SAMPLES 65536u
#define BC_STACKS 2048u
#define BC_HASH 4096u
#define BC_SNAPSHOT 32768u

struct bc_event {
	uint32_t us;
	uint16_t kind, phase;
	uint64_t tid;
	uint32_t a, b, c, d;
};
struct bc_sample {
	uint32_t us, stack;
	uint64_t tid, pidtrap, event;
	uint16_t phase;
	uint8_t kind, cpu;
	uint32_t pad;
};
struct bc_stack {
	uint64_t hash;
	uint32_t nk, nu;
	uint64_t frames[SP_KFRAMES + SP_UFRAMES];
};
struct bc_store {
	struct bc_event events[BC_EVENTS];
	struct bc_sample samples[BC_SAMPLES];
	struct bc_stack stacks[BC_STACKS];
	uint32_t hash[BC_HASH];
};
static struct bc_store *bc;
static volatile uint32_t bc_ne, bc_ns, bc_nk, bc_drop, bc_sample_drop, bc_dict_lock;
static volatile uint32_t bc_writers, bc_active, bc_phase, bc_snapshot_seq;
static uint64_t bc_epoch, bc_end, bc_sample_until, bc_last_memory;
static char bc_snapshot[BC_SNAPSHOT];
static size_t bc_snapshot_len;
extern char version[];
extern uint64_t max_mem;
static volatile int64_t bc_mem[8];
bool sweet_bench_enabled(void);
bool
sweet_bench_enabled(void)
{
	return os_atomic_load(&bc_active, acquire) != 0;
}
void sweet_bench_alloc(uint32_t slot, int64_t delta);
void
sweet_bench_alloc(uint32_t slot, int64_t delta)
{
	if (slot < 8) { os_atomic_add(&bc_mem[slot], delta, relaxed); }
}

static void
sweet_bench_memory(uint64_t *out)
{
	for (unsigned i = 0; i < 8; i++) { out[i] = (uint64_t)os_atomic_load(&bc_mem[i], relaxed); }
}

static uint32_t
bc_us(uint64_t now)
{
	uint64_t ns = 0;
	absolutetime_to_nanoseconds(now - bc_epoch, &ns);
	return (uint32_t)(ns / 1000);
}

/* C/C++ hooks: bounded append, no allocation or blocking in the hot path.
 * 20..29 are detailed GPU jobs, retained only in sampled motion windows.
 */
void sweet_bench_event(uint32_t kind, uint32_t a, uint32_t b, uint32_t c, uint32_t d);
void
sweet_bench_event(uint32_t kind, uint32_t a, uint32_t b, uint32_t c, uint32_t d)
{
	if (!os_atomic_load(&bc_active, acquire)) {
		return;
	}
	os_atomic_inc(&bc_writers, acquire);
	uint64_t now = mach_absolute_time();
	if (!os_atomic_load(&bc_active, acquire) || now >= bc_end ||
	    (kind >= 20 && kind <= 29 && now >= os_atomic_load(&bc_sample_until, relaxed))) {
		os_atomic_dec(&bc_writers, release);
		return;
	}
	uint32_t n = os_atomic_add_orig(&bc_ne, 1, relaxed);
	if (n < BC_EVENTS) {
		bc->events[n] = (struct bc_event){bc_us(now), (uint16_t)kind, (uint16_t)bc_phase,
		    current_thread()->thread_id, a, b, c, d};
	} else {
		os_atomic_inc(&bc_drop, relaxed);
	}
	os_atomic_dec(&bc_writers, release);
}

static bool
bc_sampling(uint64_t now)
{
	return sp_bench && os_atomic_load(&bc_active, acquire) && now < bc_end &&
	       now < os_atomic_load(&bc_sample_until, relaxed);
}

/* Try-only dictionary ownership: a timer interrupt must never spin on a lock
 * held by the thread it interrupted. Contention/capacity loss is exported.
 */
static void
bc_sample_put(const struct sp_rec *r, const uintptr_t *kf, unsigned nk, const uintptr_t *uf, unsigned nu)
{
	if (!bc_sampling(mach_absolute_time())) {
		return;
	}
	if (!os_atomic_cmpxchg(&bc_dict_lock, 0, 1, acquire)) {
		os_atomic_inc(&bc_sample_drop, relaxed);
		return;
	}
	uint64_t frames[SP_KFRAMES + SP_UFRAMES];
	memcpy(frames, kf, nk * sizeof(uint64_t));
	memcpy(frames + nk, uf, nu * sizeof(uint64_t));
	uint64_t hash = 1469598103934665603ull ^ nk ^ ((uint64_t)nu << 8);
	for (unsigned i = 0; i < nk + nu; i++) {
		hash = (hash ^ frames[i]) * 1099511628211ull;
	}
	uint32_t slot = (uint32_t)hash & (BC_HASH - 1), id = 0;
	for (unsigned probe = 0; probe < BC_HASH; probe++, slot = (slot + 1) & (BC_HASH - 1)) {
		id = bc->hash[slot];
		if (id == 0) {
			if (bc_nk == BC_STACKS) {
				break;
			}
			id = ++bc_nk;
			struct bc_stack *s = &bc->stacks[id - 1];
			s->hash = hash;
			s->nk = nk;
			s->nu = nu;
			memcpy(s->frames, frames, (nk + nu) * sizeof(uint64_t));
			bc->hash[slot] = id;
			break;
		}
		struct bc_stack *s = &bc->stacks[id - 1];
		if (s->hash == hash && s->nk == nk && s->nu == nu &&
		    !memcmp(s->frames, frames, (nk + nu) * sizeof(uint64_t))) {
			break;
		}
		id = 0;
	}
	if (id != 0 && bc_ns < BC_SAMPLES) {
		struct bc_sample *s = &bc->samples[bc_ns++];
		*s = (struct bc_sample){(uint32_t)r->hdr, id - 1, r->tid, r->pidtrap, r->event,
		    (uint16_t)bc_phase, (uint8_t)((r->hdr >> 40) & 15), (uint8_t)(r->hdr >> 32), 0};
		sp_samples++;
	} else {
		os_atomic_inc(&bc_sample_drop, relaxed);
	}
	os_atomic_store(&bc_dict_lock, 0, release);
}

/* One bounded snapshot per second, from the census worker, never a timer IRQ.
 * Approximate unlocked VM counters and independent process ledgers are labelled
 * as such; mapped IOSurfaces/BOs must not be added to resident memory totals.
 */
static void
bc_memory_snapshot(uint64_t now)
{
	static task_t refs[256];
	if (!sp_bench || !bc_active || now - bc_last_memory < sp_period * 500) {
		return;
	}
	bc_last_memory = now;
	os_atomic_inc(&bc_snapshot_seq, release);
	uint64_t mem[8] = {};
	sweet_bench_memory(mem);
	size_t n = (size_t)snprintf(bc_snapshot, sizeof(bc_snapshot),
	    "memory %u %llu %llu %llu %llu %llu %u %u %llu %llu %llu %llu %llu %llu %llu %llu\n",
	    bc_us(now), max_mem, (uint64_t)vm_page_free_count * PAGE_SIZE,
	    (uint64_t)vm_page_wire_count * PAGE_SIZE, (uint64_t)vm_page_active_count * PAGE_SIZE,
	    (uint64_t)vm_page_inactive_count * PAGE_SIZE, vm_page_free_wanted, PAGE_SIZE,
	    mem[0], mem[1], mem[2], mem[3], mem[4], mem[5], mem[6], mem[7]);
	unsigned count = 0, total = 0;
	task_t task;
	lck_mtx_lock(&tasks_threads_lock);
	queue_iterate(&tasks, task, task_t, tasks) {
		total++;
		if (count < sizeof(refs) / sizeof(refs[0])) {
			task_reference(task);
			refs[count++] = task;
		}
	}
	lck_mtx_unlock(&tasks_threads_lock);
	for (unsigned i = 0; i < count; i++) {
		task = refs[i];
		void *p = get_bsdtask_info(task);
		uint64_t footprint = get_task_phys_footprint(task);
		uint64_t resident = get_task_resident_size(task);
		uint64_t compressed = get_task_compressed(task);
		if (n + 192 < sizeof(bc_snapshot)) {
			n += (size_t)snprintf(bc_snapshot + n, sizeof(bc_snapshot) - n,
			    "process %d %llu %llu %llu %llu %s\n", task_pid(task), get_task_uniqueid(task),
			    footprint, resident, compressed, p != NULL ? proc_name_address(p) : "kernel_task");
		}
		task_deallocate(task);
	}
	n += (size_t)snprintf(bc_snapshot + n, sizeof(bc_snapshot) - n, "tasks %u %u\n", count, total);
	bc_snapshot_len = n;
	os_atomic_inc(&bc_snapshot_seq, release);
	sweet_bench_event(40, vm_page_free_count, vm_page_wire_count, vm_page_free_wanted, total);
}

static const char *bc_cmd(const char *line);
const char *sweet_prof_cmd(const char *line);

/* Binary blobs are immutable once both capture and its writer/census workers
 * have stopped. The command service serializes control/export operations.
 */
const char *sweet_bench_blob(const char *line, const void **data, size_t *len);
const char *
sweet_bench_blob(const char *line, const void **data, size_t *len)
{
	if (strncmp(line, "bench data ", 11)) {
		return NULL;
	}
	*data = NULL;
	*len = 0;
	if (bc == NULL || bc_active || sp_census_running || bc_writers || bc_dict_lock) {
		return "ERR capture busy or empty\n";
	}
	const char *what = line + 11;
	if (!strcmp(what, "events")) {
		*data = bc->events;
		*len = (bc_ne < BC_EVENTS ? bc_ne : BC_EVENTS) * sizeof(struct bc_event);
	} else if (!strcmp(what, "samples")) {
		*data = bc->samples;
		*len = bc_ns * sizeof(struct bc_sample);
	} else if (!strcmp(what, "stacks")) {
		*data = bc->stacks;
		*len = bc_nk * sizeof(struct bc_stack);
	} else if (!strcmp(what, "meta")) {
		*data = sp_meta;
		*len = sp_meta_used;
	} else {
		return "ERR unknown blob\n";
	}
	snprintf(sp_reply, sizeof(sp_reply), "OK %lu\n", *len);
	return sp_reply;
}

static const char *
bc_cmd(const char *line)
{
	if (strncmp(line, "bench ", 6)) {
		return NULL;
	}
	const char *a = line + 6;
	if (!strcmp(a, "caps")) {
		snprintf(sp_reply, sizeof(sp_reply),
		    "bench-v1 events=32 samples=40 stacks=400 capture_bytes=%lu legacy_profile_bytes=%llu display=ctl-flush-observed,unvalidated\n%s\n",
		    sizeof(struct bc_store) + BC_SNAPSHOT + (2u << 20), sp_buf != NULL ? sp_size : 0, version);
	} else if (!strncmp(a, "start ", 6)) {
		if (sp_census_running || bc_active || bc_writers || bc_dict_lock) {
			return "ERR capture busy\n";
		}
		a += 6;
		uint64_t secs = sp_num(&a), len = 0;
		if (secs < 1 || secs > 90) {
			return "ERR duration must be 1..90 s\n";
		}
		if (bc == NULL) {
			vm_offset_t b = 0;
			if (kmem_alloc(kernel_map, &b, sizeof(*bc), KMA_DATA | KMA_ZERO, VM_KERN_MEMORY_DIAG) != KERN_SUCCESS) {
				return "ERR no capture memory\n";
			}
			bc = (struct bc_store *)b;
		}
		bzero(bc, sizeof(*bc));
		bc_ne = bc_ns = bc_nk = bc_drop = bc_sample_drop = bc_phase = 0;
		bc_epoch = mach_absolute_time();
		nanoseconds_to_absolutetime(secs * NSEC_PER_SEC, &len);
		bc_end = bc_epoch + len;
		bc_sample_until = bc_last_memory = 0;
		bc_snapshot_len = 0;
		sp_bench = 1;
		os_atomic_store(&bc_active, 1, release);
		/* Parent uses our epoch/deadline, compact sink, and a small metadata buffer. */
		const char *r = sweet_prof_cmd("prof start 60 2000 5000 backboardd,SpringBoard,PosterBoard,Preferences");
		if (strncmp(r, "prof: started", 13)) {
			bc_active = 0;
			sp_bench = 0;
			return r;
		}
		sweet_bench_event(1, 0, 0, 0, 0);
		return "OK bench started\n";
	} else if (!strncmp(a, "phase ", 6)) {
		if (!bc_active) {
			return "ERR no active capture\n";
		}
		a += 6;
		uint64_t phase = sp_num(&a), sample_ms = sp_num(&a);
		if (phase > 65535 || sample_ms > 4000) {
			return "ERR phase or sample duration\n";
		}
		bc_phase = (uint32_t)phase;
		uint64_t duration = 0;
		nanoseconds_to_absolutetime(sample_ms * NSEC_PER_MSEC, &duration);
		os_atomic_store(&bc_sample_until, mach_absolute_time() + duration, release);
		sweet_bench_event(2, (uint32_t)phase, (uint32_t)sample_ms, 0, 0);
		snprintf(sp_reply, sizeof(sp_reply), "OK phase %llu us %u\n", phase, bc_us(mach_absolute_time()));
	} else if (!strncmp(a, "mark ", 5)) {
		a += 5;
		uint64_t moving = sp_num(&a);
		if (!bc_active || moving > 1) { return "ERR motion marker\n"; }
		sweet_bench_event(4, (uint32_t)moving, 0, 0, 0);
		snprintf(sp_reply, sizeof(sp_reply), "OK mark %llu us %u\n", moving, bc_us(mach_absolute_time()));
	} else if (!strcmp(a, "census-all")) {
		if (!bc_active) { return "ERR no active capture\n"; }
		sp_census_all = 1;
		return "OK all-thread census enabled\n";
	} else if (!strcmp(a, "snapshot")) {
		for (unsigned attempt = 0; attempt < 3; attempt++) {
			uint32_t seq = os_atomic_load(&bc_snapshot_seq, acquire);
			if (seq & 1) {
				continue;
			}
			size_t n = bc_snapshot_len;
			memcpy(sp_reply, bc_snapshot, n);
			sp_reply[n] = 0;
			if (seq == os_atomic_load(&bc_snapshot_seq, acquire)) {
				return sp_reply;
			}
		}
		return "ERR snapshot updating\n";
	} else if (!strcmp(a, "stop")) {
		sweet_bench_event(3, 0, 0, 0, 0);
		os_atomic_store(&bc_active, 0, release);
		sp_on = 0;
		thread_wakeup(&sp_census_running);
		return "OK stopping\n";
	} else if (!strcmp(a, "stat")) {
		snprintf(sp_reply, sizeof(sp_reply),
		    "bench-v1 active=%u busy=%u events=%u samples=%u stacks=%u event_dropped=%u sample_dropped=%u epoch=%llu elapsed_us=%u meta=%llu\n",
		    bc_active, sp_census_running || bc_writers || bc_dict_lock, bc_ne, bc_ns, bc_nk,
		    bc_drop, bc_sample_drop, bc_epoch, bc_epoch ? bc_us(mach_absolute_time()) : 0, sp_meta_used);
	} else {
		return "ERR unknown bench command\n";
	}
	return sp_reply;
}
