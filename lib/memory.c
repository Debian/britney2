#include <stdio.h>
#include <stdlib.h>

#include "memory.h"
#include "templates.h"
#include "freelist.h"

/**** THEORY
 * 

So, we have blocks with a freelist

        XXX............XXXXXXX..XXXXX.....XXXXXX......
        
Within a block, we work with segments. A segment is...

	   ^..........|

Every now and then we make sure we've got a decent sized segment.

We have multiple blocks. They're kept ordered by the size of their
current segment.

 **********************************************/

#define ALIGN 4

#define FLBT_BITS (sizeof(flb_t)*8)
#define MEMBLOCKSIZE (1 << 22)
#define ALIGNEDSIZE(s) (((s) + ALIGN - 1) / ALIGN * ALIGN)

struct memblock {
    struct memblock *next;

    size_t          n_bytes;          /* index of free char */
    size_t          size;             /* size of block after char */

    unsigned        n_used_chunks;    /* number of unfreed blocks */
    size_t          n_used_bytes;     /* number of bytes actually used */
    size_t          n_productive_bytes; /* number of bytes used usefully */

    flb_t           free[MEMBLOCKSIZE/ALIGN/FLBT_BITS + 1];
    unsigned char   mem[MEMBLOCKSIZE];
};
typedef struct memblock memblock;

static memblock *base = NULL;

#ifdef MDEBUG1
static int valid_memblock_mdebug1(struct memblock *mb) {
    size_t cnt, i;
    static int rarity = 0;

    assert(mb->n_bytes + mb->size <= sizeof(mb->mem));

    if (mb->n_used_chunks == 0) assert(mb->n_bytes == 0);
    assert(((unsigned long)mb->mem + mb->n_bytes) % ALIGN == 0);

    assert(mb->n_productive_bytes <= mb->n_used_bytes);
    assert(mb->n_used_bytes + mb->size <= sizeof(mb->mem));

#define TWO(k)    (1ul << (k))
#define CYCL(k)   (~0ul / (1 + TWO(TWO(k))))

    rarity++; rarity %= 25000;
    if (rarity != 0) {
	cnt = mb->n_used_bytes;
    } else {
        cnt = 0;
        for (i = 0; i < sizeof(mb->mem)/ALIGN/FLBT_BITS+1; i++) {
    	unsigned long x = mb->free[i];
            size_t s;
    	    x = (x & CYCL(0)) + ((x >> TWO(0)) & CYCL(0));
    	    x = (x & CYCL(1)) + ((x >> TWO(1)) & CYCL(1));
            for (s = 2; (2u << s) <= FLBT_BITS; s++) {
    		x += x >> TWO(s);
    		x &= CYCL(s);
    	    }
	    cnt += x * ALIGN;
        }
    }
#undef TWO
#undef CYCL

    assert(cnt == mb->n_used_bytes);

    return 1;
}
#endif

#if MDEBUG3
static int valid_memblock_mdebug3(struct memblock *mb) {
    size_t offset, step, used;
    unsigned chunk = 0;

    offset = 0;
    used = 0;
    if ((unsigned long)mb->mem % ALIGN != 0)
        offset = ALIGN - ((unsigned long)mb->mem % ALIGN);

    while(offset < mb->n_bytes) {
        step = *(size_t*)(mb->mem + offset);
        assert(step % ALIGN == 0 || step % ALIGN == 1);
        if (step % ALIGN == 1) step--; /* freed */
        else used += step;
        assert(step > 0);
        offset += step;
        chunk++;
    }

    assert(used == mb->n_used_bytes);

    return 1;
}
#endif

inline static int valid_memblock(struct memblock *mb) {
    (void)mb;

    MDEBUG1_ONLY( if (!valid_memblock_mdebug1(mb)) return 0; )
    MDEBUG3_ONLY( if (!valid_memblock_mdebug3(mb)) return 0; )

    return 1;
}

void print_memblock_summary(void) {
    struct memblock *mb;
    unsigned long tused = 0, talloc = 0, tprod = 0, tavail = 0, nb = 0;

    for (mb = base; mb != NULL; mb = mb->next) {
        assert(valid_memblock(mb));

	MDEBUG3_ONLY(
            fprintf(stderr, "%p: [%d,%lu/%lu,%p,%p]\n", mb,
               mb->n_used_chunks, (unsigned long)mb->n_used_bytes, 
               (unsigned long)mb->n_bytes, mb->next, mb->mem);
	)

	if (mb != base && mb->size * 50 < sizeof(mb->mem) - mb->n_used_bytes) {
		flb_t k; size_t s;
		k = mb->n_bytes / ALIGN;
		s = mb->size / ALIGN;
		find_long_freebits(mb->free,MEMBLOCKSIZE/ALIGN/FLBT_BITS+1,&k,&s);
		k *= ALIGN; s *= ALIGN;
		fprintf(stderr, "%p %lu: Wasted block "
                                "[%d chunks, %lu free bytes, %lu avail bytes, %2.2f%%], suggested [%ld,%ld] -> [%ld,%ld]\n",
			mb->mem, nb, mb->n_used_chunks, 
			(unsigned long) sizeof(mb->mem) - mb->n_used_bytes,
			(unsigned long) mb->size,
			(float) 100.0 * mb->size / (sizeof(mb->mem) - mb->n_used_bytes),
			(unsigned long) mb->n_bytes, (unsigned long) mb->size, 
			(unsigned long) k, (unsigned long) s);
		if (s > mb->size * 4 || s * 25 > sizeof(mb->mem) - mb->n_used_bytes) {
			mb->n_bytes = k;
			mb->size = s;
		}
	}
	nb++;
	tprod += mb->n_productive_bytes; 
	tused += mb->n_used_bytes; 
	tavail += mb->size;
	talloc += sizeof(memblock);
    }
    fprintf(stderr, "TOTAL: %lu %lu KiB alloc"
		 "(%lu/%lu available, %2.2f%%) (%lu KiB used, %2.2f%%) (%lu KiB useful, %2.2f%%)\n", 
	nb, talloc / 1024, 
	(unsigned long) (base ? base->size / 1024 : 0), 
	  tavail / 1024, (talloc > 0 ? 100.0*tavail/talloc : 0.0),
	tused / 1024, (talloc > 0 ? 100.0*tused/talloc : 0.0), 
	tprod / 1024, (talloc > 0 ? 100.0*tprod/talloc : 0.0));
}

MDEBUG1_ONLY(static int first_malloc = 0;)

#ifdef MDEBUG3
static void print_memblock_stats(void) {
    struct memblock *mb;
    size_t offset;
   
    for (mb = base; mb != NULL; mb = mb->next) {
        assert(valid_memblock(mb));

        printf("%p: [%d,%lu/%lu/%lu,%p,%p:\n", mb,
               mb->n_used_chunks, (unsigned long)mb->n_productive_bytes, 
	       (unsigned long)mb->n_used_bytes, (unsigned long)mb->n_bytes,
               mb->next, mb->mem);

        offset = 0;
        if ((unsigned long)mb->mem % ALIGN != 0)
             offset = ALIGN - ((unsigned long)mb->mem % ALIGN);
        while(offset < mb->n_bytes) {
             size_t step = *(size_t*)(mb->mem + offset);
             if (step % ALIGN == 1) {
                 step--;
                 printf(" (%d)", (int) step);
             } else {
                 printf(" %d", (int) step);
             }
             offset += step;
        }
        printf("\n");
    }
    printf("\n");
    return;
}
#endif

void *block_malloc(size_t size) {
    memblock *where = base;
    void *result;
    size_t realsize = size;

    MDEBUG3_ONLY( if (first_malloc) print_memblock_stats(); )
    MDEBUG3_ONLY( first_malloc = 0; )

    (void)assert(ALIGN >= sizeof(size_t)); /* ALIGN is set too small! */

    MDEBUG2_ONLY(size += ALIGN;) 
	/* for the size, so the caller can be checked */

    size = ALIGNEDSIZE(size);
 
    assert(size > 0 && size < sizeof(where->mem)); 
    assert(!where || ((unsigned long)where->mem + where->n_bytes) % ALIGN == 0);
     
    if ( !where || where->size < size ) {
        MDEBUG1_ONLY(print_memblock_summary();)
        where = malloc(sizeof(memblock));
        if (where == NULL) {
	    int i;
            fprintf(stderr, "block_malloc: failed trying to allocate memblock\n");
            i = 0; where = base; while(where) {i++; where = where->next;}
	    fprintf(stderr, "(had allocated %d blocks, each %lu bytes)\n", i, 
		(unsigned long)sizeof(memblock));
            return NULL;
        }

        where->n_used_chunks = 0;
	memset(where->free, 0, sizeof(where->free));
        where->n_bytes = 0;
	where->size = sizeof(where->mem);

	assert( (unsigned long)where->mem % ALIGN == 0);
		/* XXX: should be able to cope with this :( */

        where->n_used_bytes = where->n_bytes;
        where->n_productive_bytes = 0;
        (where)->next = base;
	base = where;
	
        MDEBUG2_ONLY(memset(where->mem, 0xDD, sizeof(where->mem));)
    }

    result = where->mem + where->n_bytes;

    assert( (unsigned long)where->mem % ALIGN == where->n_bytes % ALIGN );
    assert( size % ALIGN == 0 );
    mark_bits(where->free, 
	(unsigned long)((unsigned char*)result - where->mem) / ALIGN,
	size / ALIGN, 1);

    where->n_bytes += size;
    where->size -= size;
    where->n_used_bytes += size;
    where->n_productive_bytes += realsize;
    where->n_used_chunks++;

    MDEBUG2_ONLY( memset(result, 0xEE, size); )

    MDEBUG2_ONLY( *(size_t *)result = realsize; )
    MDEBUG2_ONLY( result += ALIGN; )

    assert(((unsigned long)where->mem + where->n_bytes) % ALIGN == 0);

    assert(valid_memblock(where));

    return result;
}

static memblock **find_memblock(unsigned char *mem) {
    memblock **where;

    for (where = &base; *where != NULL; where = &(*where)->next) {
	memblock *mb = *where;
        assert(valid_memblock(mb));
        if (&mb->mem[0] <= mem && (size_t)(mem - mb->mem) < sizeof(mb->mem)) {
            return where;
        }
    }
    return NULL;
}

static void free_in_memblock(memblock *mb, unsigned char *mem, size_t size) {
    MDEBUG2_ONLY(size_t *stmem = ((size_t*)mem) - 1;)

    assert(mb && mem && size > 0);

    mb->n_used_chunks--;

    mb->n_used_bytes -= ALIGNEDSIZE(size);
    mark_bits(mb->free, (unsigned long)(mem - mb->mem) / ALIGN, 
		ALIGNEDSIZE(size) / ALIGN, 0);

#ifdef MDEBUG2
    mark_bits(mb->free, (unsigned long)(mem - mb->mem) / ALIGN - 1, 1, 0);
    mb->n_used_bytes -= ALIGN;
#endif

    if ((size_t)(mem - mb->mem) + ALIGNEDSIZE(size) == mb->n_bytes) {
	size_t k = count_free_bits_back(mb->free, mb->n_bytes / ALIGN) * ALIGN;
	mb->n_bytes -= k;
	mb->size += k;
    }
    if ((size_t)(mem - mb->mem) == mb->n_bytes + mb->size) {
	mb->size += count_free_bits_after(mb->free, 
			(mb->n_bytes + mb->size) / ALIGN,
			sizeof(mb->mem) / ALIGN) * ALIGN;
    }

    mb->n_productive_bytes -= size;

    if (mb->n_used_chunks == 0) {
        assert(mb->n_productive_bytes == 0);
        assert(mb->n_used_bytes == 0);

        mb->n_bytes = 0;
	mb->size = sizeof(mb->mem);
        mb->n_used_bytes = 0;
        mb->n_productive_bytes = 0;
    }

    MDEBUG2_ONLY( memset(mem, 0xAA, size); )

#ifdef MDEBUG2
    assert((unsigned char*)stmem >= mb->mem && (unsigned char*)stmem < mb->mem + sizeof(mb->mem));
    assert(*stmem % ALIGN == 0);
    assert(*stmem == size);
#endif

    assert(valid_memblock(mb));
}

void block_free(void *vmem, size_t size) {
    memblock **where;
    MDEBUG1_ONLY(static int free_count = 0;)

    if (vmem == NULL) return;

    MDEBUG1_ONLY(first_malloc = 1;)

    where = find_memblock(vmem);
    assert(where);
    free_in_memblock(*where, vmem, size);
    if ((*where)->n_used_chunks == 0 && *where != base) {
        memblock *mb = *where;
        MDEBUG1_ONLY( print_memblock_summary(); )
        *where = (*where)->next;
        free(mb);
        MDEBUG1_ONLY( fprintf(stderr, "Freed memblock\n"); )
    }
    MDEBUG1_ONLY( free_count++; free_count %= 10000; )
    MDEBUG1_ONLY( if (!free_count) print_memblock_summary(); )
}

void *block_realloc(void *vmem, size_t oldsize, size_t newsize) {
    void *vnewmem;

    if (vmem == NULL && newsize == 0) abort();
    if (vmem == NULL) return block_malloc(newsize);
    if (newsize == 0) {
        block_free(vmem, oldsize);
        return NULL;
    }

    vnewmem = block_malloc(newsize);
    if (vnewmem) {
        memcpy(vnewmem, vmem, (oldsize < newsize ? oldsize : newsize));
        block_free(vmem, oldsize);
    }
    return vnewmem;
}

char *block_strdup(char *from) {
    char *result;
    if (!from) return NULL;
    result = block_malloc(strlen(from) + 1);
    strcpy(result, from);
    return result;
}
