
#ifndef FREELIST_H
#define FREELIST_H

#include <stdlib.h>

typedef unsigned long flb_t;

void mark_bits(flb_t *bits, flb_t s, size_t size, int setp);
size_t count_free_bits_back(flb_t *bits, size_t s);
size_t count_free_bits_after(flb_t *bits, size_t s, size_t end);
void find_long_freebits(flb_t *bits, flb_t s, flb_t *start, size_t *size);

#endif
