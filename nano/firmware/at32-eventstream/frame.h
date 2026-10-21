/* Same v1 wire format as v0.7.0. All callers provide word-aligned storage. */
#ifndef ASTER_EVENT_FRAME_H
#define ASTER_EVENT_FRAME_H
#include <stdint.h>
typedef uint32_t frame_word __attribute__((may_alias));
static FAST uint32_t hash_bytes(const void *data,uint32_t n) {
  const uint8_t *p=data;uint32_t h=2166136261u;
  while(n--)h=(h^*p++)*16777619u;
  return h;
}
static FAST uint32_t wire_frame(uint8_t *data,uint32_t kind,uint32_t session,
    uint32_t seq,uint32_t first,uint32_t trigger,uint32_t baseline,
    uint32_t length,uint32_t threshold,uint32_t errors) {
  frame_word *w=(frame_word *)(void *)data;
  /* Cortex-M4 and the supported wire format are little-endian. */
  w[0]=0x57545341u;w[1]=0x0a0d3730u; /* ASTW07\r\n */
  w[2]=1;w[3]=kind;w[4]=session;w[5]=seq;w[6]=first;w[7]=trigger;
  w[8]=kind==3?0:512;w[9]=4000000;w[10]=length;w[11]=baseline;
  w[12]=threshold;w[13]=errors;w[14]=hash_bytes(data+64,length);
  w[15]=hash_bytes(data,60);
  /* Terminal JSON length need not be word-aligned. */
  uint32_t trailer=~w[14];
  for(unsigned i=0;i<4;i++)data[64+length+i]=(uint8_t)(trailer>>(8*i));
  uint32_t size=64+length+4;if(!(size%64u))data[size++]=0;
  return size;
}
#endif
