/* Trigger only: no energy cuts or histogram. Raw 512-sample event windows. */
#ifndef ASTER_EVENT_ENGINE_H
#define ASTER_EVENT_ENGINE_H
#include <stdint.h>
#include <string.h>
#define EVENT_N 512u
#define EVENT_PRE 320u
#define EVENT_POST (EVENT_N-EVENT_PRE)
#define EVENT_HOLDOFF 64u
#define PENDING_N 8u
#if defined(__arm__)
#define FAST __attribute__((section(".ramfunc"),noinline,optimize("O3")))
#else
#define FAST
#endif
typedef int (*event_emit)(void *,uint32_t,uint32_t,const uint16_t *,uint32_t);
typedef struct {
  uint16_t ring[1024];
  uint32_t maxima[6],blocks,fine_blocks,threshold,armed,next_allowed;
  uint32_t triggers[PENDING_N],baselines[PENDING_N],head,tail;
  uint32_t candidates,emitted,holdoff_crossings,minimum,maximum,fault;
} event_engine;
static void event_init(event_engine *s,uint32_t threshold) {
  memset(s,0,sizeof(*s));s->threshold=threshold;s->armed=1;s->minimum=4095;
}
static FAST uint32_t event_copy(event_engine *s,const uint16_t *input) {
  uint32_t lo=4095,hi=0;uint16_t *dest=s->ring+((s->blocks&15u)*64u);
#if defined(__arm__)
  uint32_t lo2=0x0fff0fff,hi2=0;
  for(unsigned i=0;i<64;i+=2) {
    uint32_t v,tmp;__builtin_memcpy(&v,input+i,4);__builtin_memcpy(dest+i,&v,4);
    __asm__ volatile("usub16 %[tmp], %[v], %[lo]\n\t"
                     "sel %[lo], %[lo], %[v]\n\t"
                     "usub16 %[tmp], %[v], %[hi]\n\t"
                     "sel %[hi], %[v], %[hi]"
      : [lo] "+&r"(lo2),[hi] "+&r"(hi2),[tmp] "=&r"(tmp):[v] "r"(v):"cc");
  }
  lo=(lo2&65535u)<(lo2>>16)?(lo2&65535u):(lo2>>16);
  hi=(hi2&65535u)>(hi2>>16)?(hi2&65535u):(hi2>>16);
#else
  for(unsigned i=0;i<64;i++) {uint32_t v=input[i];dest[i]=(uint16_t)v;if(v<lo)lo=v;if(v>hi)hi=v;}
#endif
  if(lo<s->minimum)s->minimum=lo;
  if(hi>s->maximum)s->maximum=hi;
  if(hi>4095)s->fault=1;
  s->maxima[s->blocks%6u]=hi;
  for(unsigned i=0;i<6;i++)if(s->maxima[i]>hi)hi=s->maxima[i];
  return hi-lo>=s->threshold;
}
static FAST int event_feed(event_engine *s,const uint16_t *input,event_emit emit,void *context) {
  uint32_t base=s->blocks*64u,hit=event_copy(s,input);++s->blocks;
  if(s->blocks<=5u)return !s->fault; /* full 320-sample pretrigger context */
  if(hit || !s->armed) {
    ++s->fine_blocks;uint32_t sum=0;
    for(unsigned q=0;q<256;q++)sum+=s->ring[(base-272u+q)&1023u];
    for(uint32_t j=0;j<64;j++) {
      uint32_t k=base+j;int32_t delta=(int32_t)sum-(int32_t)s->ring[k&1023u]*256;
      int32_t threshold=(int32_t)s->threshold*256;
      if(delta<threshold/2)s->armed=1;
      if(s->armed && delta>=threshold) {
        s->armed=0;
        if(k>=s->next_allowed) {
          if(s->head-s->tail>=PENDING_N) {s->fault=2;return 0;}
          s->triggers[s->head%PENDING_N]=k;s->baselines[s->head%PENDING_N]=sum;
          ++s->head;++s->candidates;s->next_allowed=k+EVENT_HOLDOFF;
        } else ++s->holdoff_crossings;
      }
      sum+=s->ring[(k-16u)&1023u];sum-=s->ring[(k-272u)&1023u];
    }
  }
  /* Ring already contains this whole chunk. Delayed windows may overlap. */
  while(s->tail<s->head) {
    uint32_t i=s->tail%PENDING_N,k=s->triggers[i];
    if(k+EVENT_POST>base+64u)break;
    if(!emit(context,k,s->baselines[i],s->ring,(k-EVENT_PRE)&1023u)) {s->fault=3;return 0;}
    ++s->emitted;++s->tail;
  }
  return !s->fault;
}
#endif
