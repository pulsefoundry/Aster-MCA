#ifndef ASTER_SELECTOR_H
#define ASTER_SELECTOR_H
#include <stdint.h>
#include <string.h>
#define SELECT_BLOCK 64u
#define SELECT_PRE 5u
#define SELECT_HISTORY (SELECT_PRE+1u)
#define SELECT_RATE 4000000u
#define SELECT_PERIOD_BLOCKS (SELECT_RATE/SELECT_BLOCK)
/* Conservative raw-window gate: any host baseline k-272..k-17 fits
 * within the current and previous five 64-sample blocks. Its mean is <=
 * those blocks' maximum, so max(history)-min(current) >= threshold is
 * necessary for a host negative crossing. False positives are allowed.
 * Keep b-5..b+1 (112 us minimum), merging overlaps; baseline once a second.
 */
typedef struct {
  uint16_t history[SELECT_HISTORY][SELECT_BLOCK];
  uint32_t history_hits[SELECT_HISTORY], history_max[SELECT_HISTORY], history_min[SELECT_HISTORY], blocks, candidates, clipped_blocks;
  uint32_t scan_max_cycles;
  uint32_t emitted,last_emitted,keep_until,threshold,have_window;
} selector_t;
typedef int (*selector_emit_fn)(void*,uint64_t,const uint16_t*,uint32_t);
static inline void selector_init(selector_t *s,uint32_t threshold) {
  memset(s,0,sizeof(*s));s->threshold=threshold;
}
#if defined(__arm__)
__attribute__((section(".ramfunc"),noinline,optimize("O3")))
#endif
static uint32_t selector_scan(selector_t *s,const uint16_t *input) {
  uint32_t lo=4095,hi=0;
  uint16_t *dest=s->history[s->blocks%SELECT_HISTORY];
#if defined(__arm__)
  uint32_t lo2=0x0fff0fff,hi2=0;
  for(uint32_t i=0;i<SELECT_BLOCK;i+=2) {
    uint32_t v,tmp;__builtin_memcpy(&v,input+i,4);
    __builtin_memcpy(dest+i,&v,4);
    /* USUB16 sets two GE bits per unsigned halfword; SEL chooses bytes.
     * Keep each comparison/selection pair together; declare the APSR clobber. */
    __asm__ volatile(
      "usub16 %[tmp], %[v], %[lo]\n\t"
      "sel %[lo], %[lo], %[v]\n\t"
      "usub16 %[tmp], %[v], %[hi]\n\t"
      "sel %[hi], %[v], %[hi]"
      : [lo] "+&r" (lo2), [hi] "+&r" (hi2), [tmp] "=&r" (tmp)
      : [v] "r" (v) : "cc");
  }
  lo=(lo2&65535u)<(lo2>>16)?(lo2&65535u):(lo2>>16);
  hi=(hi2&65535u)>(hi2>>16)?(hi2&65535u):(hi2>>16);
#else
  for(uint32_t i=0;i<SELECT_BLOCK;i++) {
    uint32_t v=input[i];dest[i]=(uint16_t)v;
    if(v<lo)lo=v;
    if(v>hi)hi=v;
  }
#endif
  s->clipped_blocks+=(lo==0 || hi==4095);
  s->history_max[s->blocks%SELECT_HISTORY]=hi;s->history_min[s->blocks%SELECT_HISTORY]=lo;
  for(unsigned j=0;j<SELECT_HISTORY;j++)if(s->history_max[j]>hi)hi=s->history_max[j];
  uint32_t hit=hi-lo>=s->threshold;
  s->candidates+=hit;return hit;
}
static inline int selector_feed(selector_t *s,const uint16_t *input,
                                selector_emit_fn emit,void *context) {
  uint32_t b=s->blocks,slot=b%SELECT_HISTORY;
#if defined(__arm__)
  uint32_t begin=DWT->CYCCNT;
#endif
  uint32_t hits=selector_scan(s,input);
#if defined(__arm__)
  uint32_t elapsed=DWT->CYCCNT-begin;
  if(elapsed>s->scan_max_cycles)s->scan_max_cycles=elapsed;
#endif
  s->history_hits[slot]=hits;++s->blocks;
  int new_window=hits || (b%SELECT_PERIOD_BLOCKS==SELECT_PRE);
  if(new_window) {s->keep_until=b+1u;s->have_window=1;}
  if(new_window || (s->have_window && b<=s->keep_until)) {
    uint32_t first=new_window?(b>=SELECT_PRE?b-SELECT_PRE:0u):b;
    if(s->emitted && first<=s->last_emitted) first=s->last_emitted+1u;
    for(uint32_t q=first;q<=b;q++) {
      if(!emit(context,(uint64_t)q*SELECT_BLOCK,s->history[q%SELECT_HISTORY],s->history_hits[q%SELECT_HISTORY]))return 0;
      s->last_emitted=q;++s->emitted;
    }
  }
  return 1;
}
#endif
