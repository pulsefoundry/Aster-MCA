/* Integer equivalent of host-pulse-4M-burst-v0.1, with conservative block
 * skipping. Each accepted 8 us area increments one of 2048 hardware bins.
 * No division, floating point or square root in the per-sample loop. */
#ifndef ASTER_HIST_ENGINE_H
#define ASTER_HIST_ENGINE_H
#include <stdint.h>
#include <string.h>
#define HIST_N 2048u
#define CHUNK 64u
#if defined(__arm__)
#define FAST __attribute__((section(".ramfunc"),noinline,optimize("O3")))
#else
#define FAST
#endif
typedef struct {
  uint16_t ring[512], pulse[64];
  uint32_t maxima[6], blocks, fine_blocks, threshold, active, armed, len;
  uint32_t baseline, pre_bad, pileup, released;
  uint32_t candidates, accepted, rejected, reasons[5], underflow, overflow;
  uint32_t histogram[HIST_N], minimum, maximum, fault;
} histogram_t;
static void histogram_init(histogram_t *s,uint32_t threshold) {
  memset(s,0,sizeof(*s));s->threshold=threshold;s->armed=1;s->minimum=4095;
}

static FAST uint32_t histogram_copy(histogram_t *s,const uint16_t *input) {
  uint32_t lo=4095,hi=0;
  uint16_t *dest=s->ring+((s->blocks&7u)*64u);
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
  /* Baseline is an average of samples within these six blocks. This bound
   * can overselect, but cannot skip an eligible negative threshold crossing. */
  return hi-lo>=s->threshold;
}

static FAST void histogram_finish_event(histogram_t *s) {
  int32_t peak=0,first=64,last=-1,area=0,tail=0;
  uint32_t flags=s->pre_bad?1u:0u;int32_t threshold=(int32_t)s->threshold*256;
  if(s->pileup)flags|=2u;
  for(int q=0;q<64;q++) {
    int32_t v=(int32_t)s->baseline-(int32_t)s->pulse[q]*256;
    if(q>=4 && (peak<4 || s->pulse[q]<s->pulse[peak]))peak=q;
    if(q<32)area+=v;
    if(q>=52)tail+=v;
    if(s->pulse[q]==0 || s->pulse[q]>=4095)flags|=4u;
    if(v>=threshold) {if(first==64)first=q;last=q;}
  }
  if(last-first+1>32 || peak>20)flags|=8u;
  if(tail>=threshold*12)flags|=16u;
  ++s->candidates;
  for(unsigned i=0;i<5;i++)if(flags&(1u<<i))++s->reasons[i];
  if(flags)++s->rejected;
  else {
    ++s->accepted;
    if(area<0)++s->underflow;
    else if(area>=(int32_t)HIST_N*1024)++s->overflow;
    else {uint32_t bin=(uint32_t)area/1024u;
      if(s->histogram[bin]==UINT32_MAX)s->fault=2;else ++s->histogram[bin];}
  }
}

static FAST void histogram_feed(histogram_t *s,const uint16_t *input) {
  uint32_t hit=histogram_copy(s,input),base=s->blocks*64u;
  uint32_t warm=s->blocks<5u;
  ++s->blocks;
  if(s->blocks<=4u)return;
  if(!hit && s->armed && !s->active)return;
  ++s->fine_blocks;
  uint32_t j=warm?16u:0u,k=base+j,sum=0;
  for(unsigned q=0;q<256;q++)sum+=s->ring[(k-272u+q)&511u];
  for(;j<64;j++,k++) {
    uint32_t raw=s->ring[k&511u];
    int32_t delta=(int32_t)sum-(int32_t)raw*256;
    int32_t threshold=(int32_t)s->threshold*256;
    if(s->active) {
      s->pulse[s->len++]=(uint16_t)raw;
      int32_t fixed_delta=(int32_t)s->baseline-(int32_t)raw*256;
      if(fixed_delta<threshold/2)s->released=1;
      if(s->released && fixed_delta>=threshold)s->pileup=1;
      if(s->len==64) {
        histogram_finish_event(s);s->active=0;s->armed=delta<threshold/2;
      }
    } else {
      if(delta<threshold/2)s->armed=1;
      if(s->armed && delta>=threshold) {
        uint32_t sq=0,early=0,late=0;
        for(unsigned q=0;q<256;q++) {uint32_t v=s->ring[(k-272u+q)&511u];sq+=v*v;
          if(q<64)early+=v;
          if(q>=192)late+=v;}
        uint64_t variance=(uint64_t)sq*256u-(uint64_t)sum*sum;
        uint32_t drift=early>late?early-late:late-early;
        s->baseline=sum;s->pre_bad=variance>64u*65536u || drift>256u;
        for(unsigned q=0;q<4;q++)s->pulse[q]=s->ring[(k-4u+q)&511u];
        s->pulse[4]=(uint16_t)raw;s->len=5;s->active=1;s->armed=0;s->pileup=s->released=0;
      }
    }
    sum+=s->ring[(k-16u)&511u];sum-=s->ring[(k-272u)&511u];
  }
}
#endif
