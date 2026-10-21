/* 4M pulse estimator copied unchanged from host-pulse-4M-v0.2.
 * Each burst resets its state; USB gaps are never passed as samples. */
#include <stdint.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#define BASE 256u
#define GUARD 16u
#define WARM (BASE+GUARD)
#define WIN 64
#define PRE 4
#define MASK 511u
typedef struct {
  uint64_t trigger;
  double baseline,peak,area4,area8,area16,pre_rms;
  uint32_t flags,half_width;
} event_t;
typedef struct {
  uint16_t ring[512];uint64_t index;
  int64_t sum,sumsq;
  int active,armed,len,pileup,released;
  double threshold,baseline,pre_rms,pre_drift,values[WIN];
  uint64_t trigger;
} processor_t;
void *processor_new(double threshold) {
  processor_t *s=calloc(1,sizeof(*s));
  if(s) {s->threshold=threshold;s->armed=1;} return s;
}
void processor_free(void *p) {free(p);}
int processor_pending(void *p) {return ((processor_t*)p)->active;}
void processor_reset(void *p) {
  processor_t *s=p; double t=s->threshold;memset(s,0,sizeof(*s));s->threshold=t;s->armed=1;
}
size_t processor_feed(void *p,const uint16_t *y,size_t n,event_t *events) {
  processor_t *s=p;size_t out=0;
  for(size_t j=0;j<n;j++,s->index++) {
    uint64_t k=s->index;double value=y[j];
    if(k==WARM) {
      for(unsigned i=0;i<BASE;i++) {int64_t v=s->ring[i];s->sum+=v;s->sumsq+=v*v;}
    } else if(k>WARM) {
      int64_t add=s->ring[(k-GUARD-1)&MASK],sub=s->ring[(k-WARM-1)&MASK];
      s->sum+=add-sub;s->sumsq+=add*add-sub*sub;
    }
    double b=(double)s->sum/BASE,delta=b-value;
    if(s->active) {
      s->values[s->len++]=s->baseline-value;
      if(s->baseline-value<s->threshold/2) s->released=1;
      if(s->released && s->baseline-value>=s->threshold) s->pileup=1;
      if(s->len==WIN) {
        event_t *e=&events[out++];memset(e,0,sizeof(*e));
        e->trigger=s->trigger;e->baseline=s->baseline;e->pre_rms=s->pre_rms;
        int peak=PRE,clipped=0,first=WIN,last=-1;
        for(int q=0;q<WIN;q++) {
          double v=s->values[q];
          if(q>=PRE && v>s->values[peak]) peak=q;
          if(q<16)e->area4+=v/4;
          if(q<32)e->area8+=v/4;
          e->area16+=v/4;
          if(s->baseline-v<=0 || s->baseline-v>=4095) clipped=1;
          if(v>=s->threshold) {if(first==WIN) first=q;last=q;}
        }
        e->peak=s->values[peak];int left=peak,right=peak;
        while(left && s->values[left-1]>=e->peak/2) --left;
        while(right<WIN-1 && s->values[right+1]>=e->peak/2) ++right;
        e->half_width=(uint32_t)(right-left+1);
        if(s->pre_rms>8 || fabs(s->pre_drift)>4)e->flags|=1;
        if(s->pileup)e->flags|=2;
        if(clipped)e->flags|=4;
        if(last-first+1>32 || peak>20)e->flags|=8;
        double tail=0;for(int q=52;q<64;q++)tail+=s->values[q];
        if(tail/12>=s->threshold)e->flags|=16;
        s->active=0;s->armed=delta<s->threshold/2;
      }
    } else if(k>=WARM) {
      if(delta<s->threshold/2)s->armed=1;
      if(s->armed && delta>=s->threshold) {
        s->baseline=b;s->pre_rms=sqrt(fmax(0,(double)s->sumsq/BASE-b*b));
        double early=0,late=0;
        for(unsigned q=0;q<64;q++) {early+=s->ring[(k-WARM+q)&MASK];late+=s->ring[(k-80+q)&MASK];}
        s->pre_drift=(late-early)/64;s->trigger=k;
        for(unsigned q=0;q<PRE;q++)s->values[q]=b-s->ring[(k-PRE+q)&MASK];
        s->values[PRE]=delta;s->len=PRE+1;s->active=1;s->armed=0;s->pileup=s->released=0;
      }
    }
    s->ring[k&MASK]=(uint16_t)value;
  }
  return out;
}

