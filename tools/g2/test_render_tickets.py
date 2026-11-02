#!/usr/bin/env python3
"""Exercise actual assembled kernel ticket functions with host ownership stubs.

python test_render_tickets.py --source PATH/TO/SweetRenderTickets.inc --emit test.cpp
clang++ -std=c++17 -fsanitize=address,undefined test.cpp -o test && ./test
No device/epoch mutation. The stubs check lock/release discipline, not hardware.
"""
import argparse
from pathlib import Path


def function(source, name):
    start = source.index('\n' + name + '(')
    start = source.rfind('\n', 0, start) + 1
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + '\n'


STUBS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
using IOReturn = int;
enum { kIOReturnSuccess, kIOReturnUnsupported, kIOReturnAborted,
       kIOReturnBusy, kIOReturnBadArgument, kIOReturnNotReady };
static int locked, releases;
void IOLockLock(int *) { assert(!locked); locked = 1; }
void IOLockUnlock(int *) { assert(locked); locked = 0; }
void IOLockWakeup(int *, void *, bool) { assert(locked); }
struct OSArray { void release() { assert(!locked); ++releases; } };
#define OSSafeReleaseNULL(p) do { if (p) { (p)->release(); (p) = nullptr; } } while (0)
constexpr unsigned SWEET_TICKET_PROOFS = 1024;
struct SweetSubmitProof { uint64_t serial, issued; uint32_t seqno; };
struct SweetRenderOwner {
 uint64_t generation=0, serial=0, errors=0, issued=0, identity=0;
 uint32_t seqno=0; SweetSubmitProof *proof=nullptr; bool closed=false;
};
struct SweetRenderTicket {
 SweetRenderOwner *owner=nullptr;
 uint64_t generation=0, epoch=0, serial=0, issued=0, errors=0, identity=0;
 uint32_t seqno=0, status=0; OSArray *backing=nullptr;
 SweetRenderTicket *next=nullptr; bool listed=false, cancelled=false;
 int refs=1;
 void retain() { ++refs; }
 void release() { assert(!locked); assert(refs > 0); --refs; }
};
struct SweetSurface {
 uint32_t id=1, displayWriters=0; unsigned state=0;
 SweetRenderTicket *renderTicket=nullptr;
};
struct AppleCLCD {
 int mutex=0; int *fLock=&mutex; char fQueueRec[1];
 bool fQueueActive=true, fPowerOff=false, dead=false; uint32_t fEpoch=1;
 unsigned fDrops=0, fDropReason[16]={}, fallbacks=0;
 bool terminal() { return dead; }
 unsigned writeState(SweetSurface *s) { return s->state; }
 IOReturn rejectFrame(uint32_t, uint32_t, IOReturn);
 void queueFallback(uint32_t) { assert(locked); fQueueActive=false; ++fallbacks; }
};
static AppleCLCD fb;
static AppleCLCD *sweet_fb_main = &fb;
static SweetRenderTicket *sweet_ticket_list;
static uint64_t sweet_render_epoch=1, sweet_render_owner;
static bool sweet_ticket_suspended;
static unsigned sweet_tickets_on=1;
bool sweet_tickets_enabled() { return sweet_tickets_on != 0; }
static uint64_t sweet_ticket_begins, sweet_ticket_seals, sweet_ticket_aborts;
static uint64_t sweet_ticket_stale, sweet_ticket_errors, sweet_ticket_live, sweet_ticket_high;
void sweet_ticket_metadata(SweetRenderTicket *) {}
void sweet_bench_event(unsigned, uint32_t, uint32_t, uint32_t, uint32_t) {}
'''

TESTS = r'''
static SweetSubmitProof proofs[SWEET_TICKET_PROOFS];
static SweetRenderOwner owner;
static OSArray backing;
static SweetSurface surface;
static void begin(SweetRenderTicket &t) {
 sweet_ticket_suspended=false; fb.fPowerOff=false;
 SweetSurface *s[]={&surface};
 assert(sweet_ticket_begin(&owner, &t, s, 1, sweet_render_epoch)==kIOReturnSuccess);
 t.backing=&backing;
}
static void submit(uint32_t seq) {
 auto issued=sweet_ticket_submit_enter(&owner);
 sweet_ticket_submit(&owner, issued, seq, true);
}
int main() {
 owner.proof=proofs;
 uint32_t seq=0;
 // Normal submission: unsealed / unfinished work never becomes ready.
 SweetRenderTicket normal; begin(normal);
 assert(sweet_ticket_ready(&normal, 100, &seq)==kIOReturnNotReady);
 submit(10);
 assert(sweet_ticket_end(&owner,&normal,normal.epoch,false,10)==kIOReturnSuccess);
 assert(sweet_ticket_ready(&normal,9,&seq)==kIOReturnNotReady);
 assert(sweet_ticket_ready(&normal,10,&seq)==kIOReturnSuccess && seq==10);
 // Epoch moves after BEGIN, before submit. Backing prevents reuse until ACK.
 SweetRenderTicket cancelled; begin(cancelled);
 sweet_ticket_cancel(nullptr);
 assert(cancelled.cancelled && cancelled.status==2 && cancelled.backing);
 sweet_ticket_suspended=false;
 SweetRenderTicket reuse; SweetSurface *s[]={&surface};
 assert(sweet_ticket_begin(&owner,&reuse,s,1,sweet_render_epoch)==kIOReturnBusy);
 SweetRenderOwner stranger;
 assert(sweet_ticket_end(&stranger,&cancelled,cancelled.epoch,false,11)==kIOReturnAborted);
 assert(sweet_ticket_end(&owner,&cancelled,cancelled.epoch+1,false,11)==kIOReturnAborted);
 assert(cancelled.backing && cancelled.listed);
 submit(11);
 assert(sweet_ticket_end(&owner,&cancelled,cancelled.epoch,false,11)==kIOReturnSuccess);
 assert(!cancelled.backing && !cancelled.listed && cancelled.status==2 && cancelled.seqno==11);
 // ACK never resurrects a cancelled generation, even after GPU completion.
 assert(sweet_ticket_ready(&cancelled,10,&seq)==kIOReturnAborted);
 assert(sweet_ticket_ready(&cancelled,11,&seq)==kIOReturnAborted);
 auto n=releases;
 assert(sweet_ticket_end(&owner,&cancelled,cancelled.epoch,false,11)==kIOReturnSuccess);
 assert(releases==n);
 assert(sweet_ticket_end(&owner,&cancelled,cancelled.epoch,false,12)!=kIOReturnSuccess);
 // Display-owned and retiring surfaces remain protected after the ACK.
 for (unsigned state=1;state<=4;state++) {
  surface.state=state;
  assert(sweet_ticket_begin(&owner,&reuse,s,1,sweet_render_epoch)==kIOReturnBusy);
 }
 surface.state=0;
 begin(reuse); submit(12);
 assert(sweet_ticket_end(&owner,&reuse,reuse.epoch,false,12)==kIOReturnSuccess);
 assert(sweet_ticket_ready(&reuse,12,&seq)==kIOReturnSuccess);
 // Epoch after submit, before seal, with an evicted/error proof: retain backing.
 SweetRenderTicket bad; begin(bad); submit(13); sweet_ticket_cancel(nullptr);
 ++owner.errors;
 assert(sweet_ticket_end(&owner,&bad,bad.epoch,false,13)!=kIOReturnSuccess);
 assert(bad.backing && bad.listed);
 // ABORT is the explicit no-more-writes acknowledgement, still idempotent.
 assert(sweet_ticket_end(&owner,&bad,bad.epoch,true,0)==kIOReturnSuccess);
 assert(!bad.backing);
 assert(sweet_ticket_end(&owner,&bad,bad.epoch,true,0)==kIOReturnSuccess);
 // A query/BEGIN epoch race and suspended/closed ownership reject before writes.
 SweetRenderTicket refused; auto old_epoch=sweet_render_epoch;
 sweet_ticket_cancel(nullptr);
 assert(sweet_ticket_begin(&owner,&refused,s,1,old_epoch)==kIOReturnAborted);
 assert(sweet_ticket_begin(&owner,&refused,s,1,sweet_render_epoch)==kIOReturnAborted);
 sweet_ticket_suspended=false; owner.closed=true;
 assert(sweet_ticket_begin(&owner,&refused,s,1,sweet_render_epoch)==kIOReturnAborted);
 owner.closed=false;
 assert(!sweet_ticket_live && !locked && sweet_ticket_list==nullptr);
 puts("PASS: normal fences; epoch before/after submit; cancelled ACK; reuse; ownership; proof errors; idempotence");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--emit', type=Path, required=True)
    parser.add_argument('--framebuffer', type=Path,
                        help='also exercise actual reason-16 rejection policy')
    args = parser.parse_args()
    source = args.source.read_text()
    names = ['sweet_ticket_unlink', 'sweet_ticket_begin', 'sweet_ticket_proof',
             'sweet_ticket_end', 'sweet_ticket_submit_enter', 'sweet_ticket_submit',
             'sweet_ticket_cancel', 'sweet_ticket_ready']
    definitions = STUBS + '\n'.join(function(source, n) for n in names)
    tests = TESTS
    if args.framebuffer:
        definitions += function(args.framebuffer.read_text(), 'AppleCLCD::rejectFrame')
        tests = tests.replace(' puts("PASS:', '''
 assert(fb.rejectFrame(1,16,kIOReturnAborted)==kIOReturnAborted);
 assert(fb.fQueueActive && !fb.fallbacks && fb.fDrops==1);
 sweet_tickets_on=0;
 assert(fb.rejectFrame(2,16,kIOReturnAborted)==kIOReturnAborted);
 assert(!fb.fQueueActive && fb.fallbacks==1);
 puts("PASS:''')
    args.emit.write_text(definitions + tests)


if __name__ == '__main__':
    main()
