#include <stdio.h>
#include <stdlib.h>

#include "memory.h"
#include "templates.h"
#include "freelist.h"

typedef struct chunk chunk;
struct chunk {
    chunk *next; /* only used when in free_lists */
};

#define GRAN             (sizeof (struct chunk))
#define ALLOC_SIZE       (1 << 20)
#define MAX_CHUNK_SIZE   256
#define NUM_BLOCK_TYPES  (MAX_CHUNK_SIZE / GRAN)

#ifdef MDEBUG1
#define MAX_POOLS        100
#else
#define MAX_POOLS        1
#endif

#ifdef MDEBUG1
static void freesize(void *p, size_t s) { (void)s; free(p); }
static void die(char *blah) { perror(blah); abort(); }

LIST(alloclist, chunk *);
LIST_IMPL(alloclist, chunk *, KEEP(chunk *), malloc, freesize);

void print_memblock_summary2(int size);
#endif

struct chunkpool {
    chunk *ch;
    MDEBUG1_ONLY( int pool_id; )
    MDEBUG1_ONLY( alloclist *all; )
};

static struct chunkpool free_lists[NUM_BLOCK_TYPES][MAX_POOLS];

#ifdef MDEBUG1
static int total[NUM_BLOCK_TYPES][MAX_POOLS];
static int used[NUM_BLOCK_TYPES][MAX_POOLS];
static int allocs[NUM_BLOCK_TYPES][MAX_POOLS];
static int total_mallocs = 0;
static int total_alloc = 0;
#endif

void *block_malloc(size_t size) {
    return block_malloc2(size, -1);
}

void *block_malloc2(size_t size, int pool_id) {
    chunk **fl = NULL;
    void *result;
    int granmult;
    int pool = 0;
   
    if (size > MAX_CHUNK_SIZE || size % GRAN != 0) {
	MDEBUG1_ONLY( total_mallocs++; )
        return malloc(size);
    }

    granmult = size / GRAN;

#ifdef MDEBUG1
    for (pool = 0; pool + 1 < MAX_POOLS; pool++) {
	if (free_lists[granmult - 1][pool].pool_id == 0) {
		free_lists[granmult - 1][pool].pool_id = pool_id;
	} 
	if (free_lists[granmult - 1][pool].pool_id == pool_id) {
		break;
	}
    }
#endif

    fl = &free_lists[granmult - 1][pool].ch;
    if (*fl == NULL)
    {
        chunk *new_block = malloc(ALLOC_SIZE);
	chunk *p;
	MDEBUG1_ONLY( int old_size = total[granmult-1][pool]; )

	if (!new_block) return NULL;

	MDEBUG1_ONLY( insert_alloclist(&free_lists[granmult - 1][pool].all, new_block); )

        for (p = new_block; (char*)(p + granmult) <= ((char*)new_block) + ALLOC_SIZE; p += granmult) {
	    /* each iteration adds a new chunk to the list */
	    MDEBUG1_ONLY( total[granmult-1][pool]++; )
	    *fl = p;
	    fl = &p->next;
	}
	*fl = NULL;
        fl = &free_lists[granmult - 1][pool].ch;
	MDEBUG1_ONLY( assert((total[granmult-1][pool]-old_size)*size <= ALLOC_SIZE); )
	MDEBUG1_ONLY( assert(total[granmult-1][pool]*(int)size - old_size > ALLOC_SIZE - (int) size); )

#ifdef MDEBUG1
        // print some info
        MDEBUG2_ONLY(
	  fprintf(stderr, "ALLOC: for size %2ld (%d:line %d), %4ld B of %4ld B used, total alloced is %8ld KiB\n", (long int) size, pool, pool_id, (long int) used[granmult-1][pool] * size, (long int) total[granmult-1][pool] * size, (long int) total_alloc / 1024);
	)

        assert( used[granmult-1][pool] <= (signed long) total[granmult-1][pool] );

        total_alloc += ALLOC_SIZE;
#endif
    }

#ifdef MDEBUG1
    {
	static unsigned long cnt = 0, cnt2 = 0;
        if (++cnt % (1L << 20) == 0) {
            if (++cnt2 % 10 == 0) {
  	        print_memblock_summary2(0);
	    } else {
	        print_memblock_summary();
	    }
        }
    }
#endif

    MDEBUG1_ONLY( used[granmult-1][pool]++; )
    MDEBUG1_ONLY( allocs[granmult-1][pool]++; )

    result = *fl;
    *fl = (*fl)->next;
    *(int *)result = ~0;
    return result;
}

#ifdef MDEBUG1
static int find_closest(void *vmem, size_t size, chunk **ch, int *p) {
    int pool;
    *ch = NULL;

    for (pool = 0; pool < MAX_POOLS; pool++) {
	alloclist *a;
	if (!free_lists[size/GRAN - 1][pool].all) break;
	for (a = free_lists[size/GRAN - 1][pool].all; a; a = a->next) {
	    if (*ch < a->value && a->value <= (chunk*)vmem) {
		*ch = a->value;
		*p = pool;
	    }
	}
    }
    assert((char*)*ch <= (char*)vmem);
    if ((char*)vmem - (char*)*ch < ALLOC_SIZE) {
	return 1;
    } else {
	return 0;
    }
}
#endif

void block_free(void *vmem, size_t size) {
    int pool = 0;

    if (size > MAX_CHUNK_SIZE || size % GRAN != 0) {
        free(vmem);
	return;
    }

#if MDEBUG1
    { chunk *closest;
    if (!find_closest(vmem, size, &closest, &pool)) {
	fprintf(stderr, "AIEE: %p + %lx < %p\n", closest, (unsigned long) ALLOC_SIZE, vmem);
	assert(0);
    }
    }
#endif
		    
    MDEBUG1_ONLY( used[size/GRAN-1][pool]--; )

    {
	chunk **fl, *x;
        fl = &free_lists[size/GRAN - 1][pool].ch;
        x = (chunk *) vmem;
        x->next = *fl;
        *fl = x;
    }
}

#ifdef MDEBUG1

void print_memblock_summary(void) {
    print_memblock_summary2(5*1024*1024);
}
void print_memblock_summary2(int size) {
    unsigned int i, j;
    fprintf(stderr, "MEMORY SUMMARY:\n");
    for (i = 0; i < NUM_BLOCK_TYPES; i++) {
        for (j = 0; j < MAX_POOLS; j++) {
	    if (total[i][j] * GRAN * (i+1) < size) continue;
	    if (free_lists[i][j].all != NULL) {
	        fprintf(stderr, " pool %dB/%d:%d; %d used %d allocated (%0.1f%% of %d MiB, %0.2f%% current)\n",
				(i+1) * GRAN, j, free_lists[i][j].pool_id,
				used[i][j], total[i][j],
				(100.0 * used[i][j]) / total[i][j],
				total[i][j] * GRAN * (i+1) / 1024 / 1024,
				(100.0 * used[i][j]) / allocs[i][j]);
	    }
	}
    }
}
	
#endif
