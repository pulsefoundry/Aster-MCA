/* Native host build of the same lossless codec, plus independent decoder. */
#include "codec.h"
#include <stdlib.h>
#include <math.h>
#include <string.h>
size_t host_encode(const uint16_t *in,size_t n,uint8_t *out,uint32_t *hash) {
  return encode_adc(in,n,out,hash);
}
int host_decode(const uint8_t *in,size_t bytes,uint16_t *out,size_t n,
                uint32_t *hash) {
  size_t nib=0;int value=0;uint32_t h=ASTER_FNV_INIT;
  for(size_t i=0;i<n;i++) {
    if(nib>=bytes*2) return -1;
    uint32_t code=(in[nib>>1]>>((nib&1)*4))&15; ++nib;
    if(code==15) {
      if(nib+3>bytes*2) return -2;
      value=0;
      for(unsigned k=0;k<3;k++,nib++)
        value|=((in[nib>>1]>>((nib&1)*4))&15)<<(k*4);
    } else value+=(int)code-7;
    if(value<0||value>4095) return -3;
    out[i]=(uint16_t)value;h=(h^(uint32_t)value)*16777619u;
  }
  if((nib+1)/2!=bytes) return -4;
  if((nib&1) && (in[nib>>1]&0xf0)) return -5;
  *hash=h;return 0;
}
uint32_t host_hash(const uint8_t *data,size_t n) {return hash_bytes(data,n);}

/* HOST ONLY pulse extraction. No part of this processor is linked to MCU code.
 * Absolute indices and state span all USB/DMA boundaries. */
typedef struct {
  uint64_t trigger;
  double baseline,peak,area4,area8,area16,pre_rms;
  uint32_t flags,half_width;
} event_t;
typedef struct {
  uint16_t ring[128];uint64_t index;
  int64_t sum,sumsq;
  int active,armed,len,pileup,released;
  double threshold,baseline,pre_rms,pre_drift,values[16];
  uint64_t trigger;
} processor_t;
void *processor_new(double threshold) {
  processor_t *s=calloc(1,sizeof(*s));
  if(s) {s->threshold=threshold;s->armed=1;} return s;
}
void processor_free(void *p) {free(p);}
int processor_pending(void *p) {return ((processor_t*)p)->active;}
size_t processor_feed(void *p,const uint16_t *y,size_t n,event_t *events) {
  processor_t *s=p;size_t out=0;
  for(size_t j=0;j<n;j++,s->index++) {
    uint64_t k=s->index;double value=y[j];
    if(k==68) {
      for(unsigned i=0;i<64;i++) {int64_t v=s->ring[i];s->sum+=v;s->sumsq+=v*v;}
    } else if(k>68) {
      int64_t add=s->ring[(k-5)&127],sub=s->ring[(k-69)&127];
      s->sum+=add-sub;s->sumsq+=add*add-sub*sub;
    }
    double b=(double)s->sum/64,delta=b-value;
    if(s->active) {
      s->values[s->len++]=s->baseline-value;
      if(s->baseline-value<s->threshold/2) s->released=1;
      if(s->released && s->baseline-value>=s->threshold) s->pileup=1;
      if(s->len==16) {
        event_t *e=&events[out++];memset(e,0,sizeof(*e));
        e->trigger=s->trigger;e->baseline=s->baseline;e->pre_rms=s->pre_rms;
        int peak=1,clipped=0,first=16,last=-1;
        for(int q=0;q<16;q++) {
          double v=s->values[q];
          if(q && v>s->values[peak]) peak=q;
          if(q<4)e->area4+=v;if(q<8)e->area8+=v;e->area16+=v;
          if(s->baseline-v<=0 || s->baseline-v>=4095) clipped=1;
          if(v>=s->threshold) {if(first==16) first=q;last=q;}
        }
        e->peak=s->values[peak];int left=peak,right=peak;
        while(left && s->values[left-1]>=e->peak/2) --left;
        while(right<15 && s->values[right+1]>=e->peak/2) ++right;
        e->half_width=(uint32_t)(right-left+1);
        if(s->pre_rms>8 || fabs(s->pre_drift)>4)e->flags|=1;
        if(s->pileup)e->flags|=2;
        if(clipped)e->flags|=4;
        if(last-first+1>8 || peak>5)e->flags|=8;
        if((s->values[13]+s->values[14]+s->values[15])/3>=s->threshold)e->flags|=16;
        s->active=0;s->armed=delta<s->threshold/2;
      }
    } else if(k>=68) {
      if(delta<s->threshold/2)s->armed=1;
      if(s->armed && delta>=s->threshold) {
        s->baseline=b;
        s->pre_rms=sqrt(fmax(0,(double)s->sumsq/64-b*b));
        double early=0,late=0;
        for(unsigned q=0;q<16;q++) {early+=s->ring[(k-68+q)&127];late+=s->ring[(k-20+q)&127];}
        s->pre_drift=(late-early)/16;
        s->trigger=k;s->values[0]=b-s->ring[(k-1)&127];s->values[1]=delta;
        s->len=2;s->active=1;s->armed=0;s->pileup=s->released=0;
      }
    }
    s->ring[k&127]=(uint16_t)value;
  }
  return out;
}
