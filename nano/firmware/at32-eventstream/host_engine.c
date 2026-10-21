#include <stdlib.h>
#include "engine.h"
#include "frame.h"
uint32_t host_frame(uint8_t *data,uint32_t kind,uint32_t session,uint32_t seq,
    uint32_t first,uint32_t trigger,uint32_t baseline,uint32_t length,uint32_t threshold,uint32_t errors) {
  return wire_frame(data,kind,session,seq,first,trigger,baseline,length,threshold,errors);
}
typedef struct {uint32_t trigger,baseline;uint16_t samples[EVENT_N];} host_event;
typedef struct {event_engine engine;host_event *out;uint32_t capacity,count;} host_state;
void *event_new(uint32_t threshold) {
  host_state *s=calloc(1,sizeof(*s));if(s)event_init(&s->engine,threshold);return s;
}
void event_free(void *p) {free(p);}
static int emit(void *p,uint32_t trigger,uint32_t baseline,const uint16_t *ring,uint32_t first) {
  host_state *s=p;if(s->count>=s->capacity)return 0;
  host_event *e=&s->out[s->count++];e->trigger=trigger;e->baseline=baseline;
  for(unsigned i=0;i<EVENT_N;i++)e->samples[i]=ring[(first+i)&1023u];return 1;
}
uint32_t event_run(void *p,const uint16_t *data,uint32_t n,host_event *out,uint32_t capacity) {
  host_state *s=p;s->out=out;s->capacity=capacity;s->count=0;
  if(n%64)return UINT32_MAX;
  for(unsigned i=0;i<n;i+=64)if(!event_feed(&s->engine,data+i,emit,s))return UINT32_MAX;
  return s->count;
}
uint32_t event_counter(void *p,uint32_t which) {
  event_engine *s=&((host_state*)p)->engine;
  switch(which) {case 0:return s->candidates;case 1:return s->emitted;
    case 2:return s->head-s->tail;case 3:return s->holdoff_crossings;case 4:return s->fault;default:return s->blocks;}
}
