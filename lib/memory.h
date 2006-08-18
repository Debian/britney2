#ifndef MEMORY_H
#define MEMORY_H

#if 1

void *block_malloc(size_t size);
void *block_malloc2(size_t size, int pool);
void block_free(void *vmem, size_t size);

#if defined(MDEBUG)
#define MDEBUG1
#endif

#define MDEBUG1_ONLY(x)
#define MDEBUG2_ONLY(x)
#define MDEBUG3_ONLY(x)

#ifdef MDEBUG3
#define MDEBUG1
#define MDEBUG2
#undef MDEBUG3_ONLY
#define MDEBUG3_ONLY(x) x
#endif

#ifdef MDEBUG2
#define MDEBUG1
#undef MDEBUG2_ONLY
#define MDEBUG2_ONLY(x) x
#endif

#ifdef MDEBUG1
#undef MDEBUG1_ONLY
#define MDEBUG1_ONLY(x) x
#endif

MDEBUG1_ONLY( void print_memblock_summary(void); )

#else

#define block_malloc(x) malloc(x)
#define block_free(x, s) free(x)

static void print_memblock_summary(void) {}

#endif

#endif /* MEMORY_H */
