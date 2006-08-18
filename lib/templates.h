#ifndef TEMPLATE_H
#define TEMPLATE_H

#include <stdio.h>
#include <string.h>
#include "memory.h"

#undef assert
   /* gcc-3.0 sucks */

#if defined(DEBUG) && defined(NDEBUG)
#error "Can't debug and notdebug both"
#endif

#if !defined(DEBUG) && !defined(NDEBUG)
#define NDEBUG
#endif

#ifdef NDEBUG
# define DEBUG_ONLY( stmt )
# define assert(x) (void)0
#else
# define DEBUG_ONLY( stmt ) stmt
# define assert(x) ((x) ? 1 : _myassertbug(__LINE__, __FILE__, #x))

extern int _myassertbug(int line, char *file, char *err);

#endif

#ifdef __STRICT_ANSI__
#define inline __inline__
#endif

static inline unsigned long strhash(const char *x, unsigned char pow) {
    unsigned long i = 0;
    while (*x) {
        i = (i * 39 + *x) % (1UL << pow);
        x++;
    }
    return i;
}

#define KEEP(TYPE)  ((void(*)(TYPE))NULL)

#define LIST(NAME,TYPE)                                            \
    typedef struct NAME NAME;                                      \
    struct NAME { TYPE value; struct NAME *next; };                \
    void insert_##NAME(NAME **where, TYPE v);                      \
    void insert_l_##NAME(NAME **where, TYPE v, int line);          \
    TYPE remove_##NAME(NAME **where);                              \
    void delete_##NAME(NAME **where);                              \
    void free_##NAME(NAME *l)


#define LIST_IMPL_2(NAME,TYPE,FREE,LFREE)                          \
    TYPE remove_##NAME(NAME **where) {                             \
        NAME *next;                                                \
        TYPE res;                                                  \
        assert(*where != NULL);                                    \
        next = (*where)->next;                                     \
        res = (*where)->value;                                     \
        LFREE(*where, sizeof(NAME));                               \
        *where = next;                                             \
        return res;                                                \
    }                                                              \
    void delete_##NAME(NAME **where) {                             \
        NAME *next;                                                \
        assert(*where != NULL);                                    \
        next = (*where)->next;                                     \
        if (FREE != NULL) (FREE)((*where)->value);                 \
        LFREE(*where, sizeof(NAME));                               \
        *where = next;                                             \
    }                                                              \
    void free_##NAME(NAME *l) {                                    \
	NAME *n;                                                   \
	while (l != NULL) {                                        \
	    n = l->next;                                           \
	    if (FREE != NULL) (FREE)(l->value);                    \
	    LFREE(l, sizeof(NAME));                                \
	    l = n;                                                 \
	}                                                          \
    }

#define LIST_IMPL(NAME,TYPE,FREE,LMALLOC,LFREE)                    \
    void insert_##NAME(NAME **where, TYPE v) {                     \
	NAME *n = *where;                                          \
	*where = LMALLOC(sizeof(NAME));                            \
	if (*where == NULL)                                        \
		die("insert_" #NAME " malloc:");                   \
	(*where)->value = v;                                       \
	(*where)->next = n;                                        \
    }                                                              \
    LIST_IMPL_2(NAME,TYPE,FREE,LFREE)

#define LIST_IMPLX(NAME,TYPE,FREE)                                 \
    void insert_l_##NAME(NAME **where, TYPE v, int line) {         \
	NAME *n = *where;                                          \
	*where = block_malloc2(sizeof(NAME), line);                \
	if (*where == NULL)                                        \
		die("insert_" #NAME " malloc:");                   \
	(*where)->value = v;                                       \
	(*where)->next = n;                                        \
    }                                                              \
    LIST_IMPL_2(NAME,TYPE,FREE,block_free)

#define HASH(TYPE, KEY, VALUE)                                     \
    typedef struct TYPE TYPE;                                      \
    typedef struct TYPE##_iter TYPE##_iter;                        \
    struct TYPE##_iter {                                           \
        unsigned long i; TYPE *h; KEY k; VALUE v;                  \
    };                                                             \
    TYPE *new_##TYPE(void);                                        \
    void free_##TYPE(TYPE *h);                                     \
    TYPE##_iter first_##TYPE(TYPE *h);                             \
    TYPE##_iter next_##TYPE(TYPE##_iter i);                        \
    int done_##TYPE(TYPE##_iter i);                                \
                                                                   \
    void iterate_##TYPE(TYPE *h, void (*itf)(TYPE*,VALUE,void*),   \
                        void *data);                               \
    VALUE lookup_##TYPE(TYPE *h, KEY k);                           \
    void add_##TYPE(TYPE *h, KEY k, VALUE v);                      \
    VALUE replace_##TYPE(TYPE *h, KEY k, VALUE v);                 \
    VALUE remove_##TYPE(TYPE *h, KEY k)

#define HASH_MAGIC (0x22DEAD22)

#define HASH_IMPL(TYPE, KEY, VALUE, POW2, HASH, CMP, FREEK, FREEV) \
    struct TYPE {                                                  \
        unsigned long magic;                                       \
        unsigned long size;                                        \
        unsigned long n_used;                                      \
        unsigned long n_collisions;                                \
        struct { KEY key; VALUE value; } *hash;                    \
    };                                                             \
    TYPE *new_##TYPE(void) {                                       \
        size_t i;                                                  \
        TYPE *h = malloc(sizeof(TYPE));                            \
        if (h == NULL) die("new_" #TYPE " malloc:");               \
                                                                   \
        h->magic = HASH_MAGIC;                                     \
        h->size = (1 << POW2);                                     \
        h->n_used = 0;                                             \
        h->n_collisions = 0;                                       \
        h->hash = malloc(sizeof(*h->hash) * h->size );             \
        if (h == NULL) die("new_" #TYPE " hash malloc:");          \
                                                                   \
        for (i = 0; i < h->size; i++) {                            \
            h->hash[i].key   = NULL;                               \
            h->hash[i].value = NULL;                               \
        }                                                          \
                                                                   \
        return h;                                                  \
    }                                                              \
                                                                   \
    void free_##TYPE(TYPE *h) {                                    \
        size_t i;                                                  \
        if (h == NULL) return;                                     \
        assert(h->magic == HASH_MAGIC);                            \
    /*  printf("Freeing: size: %lu used: %lu coll: %lu\n", */      \
    /*         h->size, h->n_used, h->n_collisions);       */      \
        h->magic = ~HASH_MAGIC;                                    \
        for (i = 0; i < h->size; i++) {                            \
            if (FREEK && h->hash[i].key)                           \
                (FREEK)(h->hash[i].key);                           \
            if (FREEV && h->hash[i].value)                         \
                (FREEV)(h->hash[i].value);                         \
        }                                                          \
        free(h->hash);                                             \
        free(h);                                                   \
    }                                                              \
                                                                   \
    void iterate_##TYPE(TYPE *h, void (*itf)(TYPE*,VALUE,void*),   \
                        void *data)                                \
    {                                                              \
        TYPE##_iter x;                                             \
        for (x = first_##TYPE(h);                                  \
             !done_##TYPE(x);                                      \
             x = next_##TYPE(x))                                   \
        {                                                          \
            itf(h, x.v, data);                                     \
        }                                                          \
    }                                                              \
                                                                   \
    TYPE##_iter first_##TYPE(TYPE *h) {                            \
        TYPE##_iter i;                                             \
        i.i = 0;                                                   \
        i.h = h;                                                   \
        return next_##TYPE(i);                                     \
    }                                                              \
                                                                   \
    TYPE##_iter next_##TYPE(TYPE##_iter i) {                       \
        assert(i.h->magic == HASH_MAGIC);                          \
        while(i.i < i.h->size) {                                   \
            if (i.h->hash[i.i].value != NULL) {                    \
                i.k = i.h->hash[i.i].key;                          \
                i.v = i.h->hash[i.i].value;                        \
                i.i++;                                             \
                return i;                                          \
            }                                                      \
            i.i++;                                                 \
        }                                                          \
        i.h = NULL;                                                \
        return i;                                                  \
    }                                                              \
                                                                   \
    int done_##TYPE(TYPE##_iter i) {                               \
        assert(i.h == NULL || i.h->magic == HASH_MAGIC);           \
        assert(i.h == NULL || (i.k != NULL && i.v != NULL));       \
        assert(i.h == NULL || (0 < i.i && i.i <= i.h->size));      \
        return i.h == NULL;                                        \
    }                                                              \
                                                                   \
    VALUE lookup_##TYPE(TYPE *h, KEY k) {                          \
        int i = HASH(k, POW2);                                     \
        assert(h->magic == HASH_MAGIC);                            \
        assert(h->n_used < h->size); /* ensure termination */      \
        while(h->hash[i].key) {                                    \
            if ((CMP)(h->hash[i].key, k) == 0) {                   \
                if (h->hash[i].value != NULL) {                    \
                    return h->hash[i].value;                       \
                }                                                  \
            }                                                      \
            i = (i + 1) % (1 << POW2);                             \
        }                                                          \
        return NULL;                                               \
    }                                                              \
                                                                   \
    void add_##TYPE(TYPE *h, KEY k, VALUE v) {                     \
        int i = HASH(k, POW2);                                     \
        assert(h->magic == HASH_MAGIC);                            \
        assert(h->n_used < h->size); /* ensure termination */      \
        assert(v != NULL);                                         \
        while(h->hash[i].value) {                                  \
            assert((CMP)(h->hash[i].key, k) != 0);                 \
            i = (i + 1) % (1 << POW2);                             \
            h->n_collisions++;                                     \
        }                                                          \
        if (FREEK != NULL && h->hash[i].key)                       \
            FREEK(h->hash[i].key);                                 \
        h->n_used++;                                               \
        h->hash[i].key = k;                                        \
        h->hash[i].value = v;                                      \
    }                                                              \
                                                                   \
    VALUE replace_##TYPE(TYPE *h, KEY k, VALUE v) {                \
        VALUE tmp;                                                 \
        int i = HASH(k,POW2);                                      \
        assert(h->magic == HASH_MAGIC);                            \
        assert(v != NULL);                                         \
        while(h->hash[i].key) {                                    \
            if ((CMP)(h->hash[i].key, k) == 0) break;              \
            i = (i + 1) % (1 << POW2);                             \
        }                                                          \
        assert(h->hash[i].value != NULL);                          \
        tmp = h->hash[i].value;                                    \
        h->hash[i].key = k;                                        \
        h->hash[i].value = v;                                      \
        return tmp;                                                \
    }                                                              \
                                                                   \
    VALUE remove_##TYPE(TYPE *h, KEY k) {                          \
        VALUE tmp;                                                 \
        int i = HASH(k, POW2);                                     \
        assert(h->magic == HASH_MAGIC);                            \
        while(h->hash[i].key) {                                    \
            if ((CMP)(h->hash[i].key, k) == 0) break;              \
            i = (i + 1) % (1 << POW2);                             \
        }                                                          \
        tmp = h->hash[i].value;                                    \
        h->hash[i].value = NULL;                                   \
        if (tmp != NULL) h->n_used--;                              \
        return tmp;                                                \
    }

#endif


