#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#define MIN(x,y) ((x) < (y) ? (x) : (y))

#define M 16

void *block_malloc(size_t size) { return malloc(size); }
void block_free(void *vmem) { free(vmem); }
void *block_realloc(void *vmem, size_t newsize) { return realloc(vmem, newsize); }
char *block_strdup(char *from) {
	char *d; 
	if (!from) return 0;
	d = block_malloc(strlen(from+1));
	if (d) strcpy(d, from);
	return d; 
}

void print_memblock_summary(void) { }
