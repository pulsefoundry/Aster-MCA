#ifndef ASTER_CODEC_H
#define ASTER_CODEC_H
#include <stdint.h>
#include <stddef.h>
#define ASTER_FNV_INIT 2166136261u
/* Word-wise FNV for decoded ADC samples, byte-wise FNV for wire bytes. */
static inline uint32_t hash_bytes(const void *p, size_t n) {
  const uint8_t *b=p; uint32_t h=ASTER_FNV_INIT;
  while(n--) h=(h^*b++)*16777619u;
  return h;
}
/* Low nibble first. 0..14 = delta -7..+7; 15 = next 3 nibbles absolute.
 * The predictor starts at zero for every block. Last unused nibble is zero.
 * At most 2*n bytes. Values must be 12 bit; no lossy clipping is performed. */
static inline void emit_value(uint8_t **cursor,unsigned *half,int delta,uint32_t value) {
  uint8_t *p=*cursor;
  if((unsigned)(delta+7)<=14u) {
    uint8_t d=(uint8_t)(delta+7);
    if(*half) {*p++|=(uint8_t)(d<<4);*half=0;}
    else {*p=d;*half=1;}
  } else {
    uint32_t bits=(value<<4)|15u;
    if(*half) {p[0]|=(uint8_t)(bits<<4);p[1]=(uint8_t)(bits>>4);p[2]=(uint8_t)(bits>>12);}
    else {p[0]=(uint8_t)bits;p[1]=(uint8_t)(bits>>8);}
    p+=2;
  }
  *cursor=p;
}
static inline size_t encode_adc(const volatile uint16_t *src,size_t n,uint8_t *out,uint32_t *raw_hash) {
  uint8_t *p=out;unsigned half=0;int prev=0;uint32_t h=ASTER_FNV_INIT;size_t i=0;
  for(;i+1<n;i+=2) {
    uint32_t a=src[i],b=src[i+1];int da=(int)a-prev,db=(int)b-(int)a;prev=(int)b;
    h=(h^a)*16777619u;h=(h^b)*16777619u;
    if((unsigned)(da+7)<=14u && (unsigned)(db+7)<=14u) {
      if(half) {p[0]|=(uint8_t)((da+7)<<4);p[1]=(uint8_t)(db+7);}
      else p[0]=(uint8_t)((da+7)|((db+7)<<4));
      ++p;
    } else {emit_value(&p,&half,da,a);emit_value(&p,&half,db,b);}
  }
  if(i<n) {uint32_t v=src[i];h=(h^v)*16777619u;emit_value(&p,&half,(int)v-prev,v);}
  *raw_hash=h;return (size_t)(p-out)+half;
}
#endif
