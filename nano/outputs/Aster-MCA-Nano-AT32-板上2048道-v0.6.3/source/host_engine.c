#include <stdlib.h>
#include "engine.h"
void *engine_new(unsigned threshold) {histogram_t *s=malloc(sizeof(*s));if(s)histogram_init(s,threshold);return s;}
void engine_free(void *s) {free(s);}
void engine_feed(void *p,const uint16_t *y,unsigned n) {
  histogram_t *s=p;if(n%64) {s->fault=3;return;}
  for(unsigned i=0;i<n;i+=64)histogram_feed(s,y+i);
}
void engine_counts(void *p,uint32_t *out) {memcpy(out,((histogram_t*)p)->histogram,HIST_N*4);}
void engine_stats(void *p,uint32_t *out) {histogram_t *s=p;uint32_t v[]={s->candidates,s->accepted,s->rejected,s->underflow,s->overflow,s->active,s->fault,s->blocks,s->fine_blocks,s->minimum,s->maximum,s->reasons[0],s->reasons[1],s->reasons[2],s->reasons[3],s->reasons[4]};memcpy(out,v,sizeof(v));}
