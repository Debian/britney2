#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>

#include "dpkg.h"
#include "memory.h"

// enlarge this if britney has issues parsing packages
// (e.g. very slow installability checks)
#define SIZEOFHASHMAP 16

/* #define DIAGNOSE 1 */

#define insert_packagenamelist(x,y) insert_l_packagenamelist(x,y,__LINE__)

static void free_dependency(dependency *dep);
static void free_collected_package(dpkg_collected_package *pkg);
static collpackagelist **get_matching_low(collpackagelist **addto, 
		                          dpkg_packages *pkgs, dependency *dep, int line);
static collpackagelist *get_matching(dpkg_packages *pkgs, deplist *depopts, int line);

static deplist *read_deplist(char **buf, char sep, char end);
static dependency *read_dependency(char **buf, char *end);
static void add_virtualpackage(virtualpkgtbl *vpkgs, char *package, 
                               char *version, dpkg_collected_package *cpkg);
static void remove_virtualpackage(virtualpkgtbl *vpkgs, char *pkgname,
			          dpkg_collected_package *cpkg);
static char *read_packagename(char **buf, char *end);
static char *read_until_char(char **buf, char *end);
static int checkinstallable(dpkg_packages *pkgs, collpackagelist *instoneof);

// implemented in dpkg-lib.c
int cmpversions(char *left, int op, char *right);


#define block_malloc(s) block_malloc2(s, __LINE__)

static int dependency_counts[] = { 1, 1, 0, 0 };

#define SMB_SIZE (1<<22)
struct stringmemblock {
	struct stringmemblock *next;
	size_t last;
	char mem[SMB_SIZE];
};
static struct stringmemblock *stringmemory = NULL;
static int stringmemorycount = 0;
static const unsigned long stringmemblocksizekib = (unsigned long) sizeof(struct stringmemblock) / 1024;

static char *my_strdup(char *foo) {
	struct stringmemblock *which;
	size_t len;

	if (!foo) return NULL;

	len = strlen(foo) + 1;

	if (len > SMB_SIZE) return strdup(foo);

	for (which = stringmemory; which; which = which->next) {
		if (SMB_SIZE - which->last > len + 1) {
			break;
		}
	}
	if (!which) {
		which = malloc(sizeof(struct stringmemblock));
		if (!which) return NULL;
		MDEBUG1_ONLY(fprintf(stderr, 
			"ALLOC: string memblock %d (%lu KiB, %lu KiB total)\n", 
			stringmemorycount, stringmemblocksizekib,
                        (stringmemorycount+1) * stringmemblocksizekib));
		memset(which->mem, 0, SMB_SIZE);
		which->last = 0;
		which->next = stringmemory;
		stringmemory = which;
		stringmemorycount++;
	}
	strcpy(&which->mem[which->last], foo);
	foo = &which->mem[which->last];
	which->last += len;
	return foo;
}

/* DIE **/

static void die(char *orig_msg) {
        char *msg = my_strdup(orig_msg);
        if (*msg && msg[strlen(msg)-1] == ':') {
                msg[strlen(msg)-1] = '\0';
                perror(msg);
        } else {
                printf("%s\n", msg);
        }
        abort();
}


/*************************************************************************
 * Basic Package Operations
 */

static dpkg_collected_package *new_collected_package(dpkg_package *pkg) {
    dpkg_collected_package *result;

    result = block_malloc(sizeof(dpkg_collected_package));
    if (result == NULL) die("new_collected_package alloc:");

    result->pkg = pkg;

    result->installed  = 0;
    result->conflicted = 0;

    result->installable = UNKNOWN;
    result->mayaffect = NULL;

    return result;
}

static void free_collected_package(dpkg_collected_package *cpkg) {
    if (cpkg == NULL) return;
    cpkg->pkg = NULL;
    free_packagenamelist(cpkg->mayaffect);
    cpkg->mayaffect = NULL;
    block_free(cpkg, sizeof(dpkg_collected_package));
}   

LIST_IMPL(deplist, dependency*, free_dependency, block_malloc, block_free);
LIST_IMPL(deplistlist, deplist*, free_deplist, block_malloc, block_free);

LIST_IMPLX(packagenamelist, char*, KEEP(char*));

LIST_IMPL(ownedpackagenamelist, char*, KEEP(char*), block_malloc, block_free);
	/* ownedpackagenamelist stores the packagename in the string store */

static int packagecmp(dpkg_package *l, dpkg_package *r) {
    if (l->priority < r->priority) return -1;
    if (l->priority > r->priority) return +1;
    return strcmp(l->package, r->package);
}

/* container for existing pkgs */
LIST_IMPL(packagelist, dpkg_package *, KEEP(dpkg_package *), block_malloc, block_free);

LIST_IMPLX(collpackagelist, dpkg_collected_package *, 
	  KEEP(dpkg_collected_package *))
#define insert_collpackagelist(x,y) insert_l_collpackagelist(x,y,__LINE__)

/*************************************************************************
 * Operations on distributions (collections of packages)
 */

dpkg_packages *new_packages(char *arch) {
    dpkg_packages *result;

    result = block_malloc(sizeof(dpkg_packages));
    if (result == NULL) die("new_packages alloc:");
    
    result->arch = my_strdup(arch);
    result->packages = new_packagetbl();
    result->virtualpkgs = new_virtualpkgtbl();

    return result;
}

void add_package(dpkg_packages *pkgs, dpkg_package *pkg) 
{
    ownedpackagenamelist *v;
    dpkg_collected_package *cpkg;

    if (lookup_packagetbl(pkgs->packages, pkg->package) != NULL) 
	return;

    cpkg = new_collected_package(pkg);

    add_packagetbl(pkgs->packages, cpkg->pkg->package, cpkg);
	
    add_virtualpackage(pkgs->virtualpkgs, cpkg->pkg->package, 
		       cpkg->pkg->version, cpkg);
    for (v = cpkg->pkg->provides; v != NULL; v = v->next) {
	add_virtualpackage(pkgs->virtualpkgs, v->value, NULL, cpkg);
    }
}

void remove_package(dpkg_packages *pkgs, dpkg_collected_package *cpkg) {
    ownedpackagenamelist *v;
    packagenamelist *aff;
    dpkg_collected_package *p;

    for (aff = cpkg->mayaffect; aff != NULL; aff = aff->next) {
	p = lookup_packagetbl(pkgs->packages, aff->value);
	if (p == NULL) continue;
	p->installable = UNKNOWN;
    }

    p = remove_packagetbl(pkgs->packages, cpkg->pkg->package);
    if (p != cpkg) return;
	
    remove_virtualpackage(pkgs->virtualpkgs, cpkg->pkg->package, cpkg);
    for (v = cpkg->pkg->provides; v != NULL; v = v->next) {
	remove_virtualpackage(pkgs->virtualpkgs, v->value, cpkg);
    }

    free_collected_package(cpkg);
}

void free_packages(dpkg_packages *pkgs) {
    if (pkgs == NULL) return;
    /* block_free(pkgs->arch); */
    free_packagetbl(pkgs->packages);
    free_virtualpkgtbl(pkgs->virtualpkgs);
    block_free(pkgs, sizeof(dpkg_packages));
}


HASH_IMPL(packagetbl, char *, dpkg_collected_package *, SIZEOFHASHMAP, strhash, strcmp,
	  KEEP(char*),free_collected_package);
HASH_IMPL(virtualpkgtbl, char *, virtualpkg *, SIZEOFHASHMAP, strhash, strcmp,
	  KEEP(char*), free_virtualpkg);

/* dpkg_provision refers to memory allocated elsewhere */
LIST_IMPL(virtualpkg, dpkg_provision, KEEP(dpkg_provision), block_malloc, block_free);

static void remove_virtualpackage(virtualpkgtbl *vpkgs, char *pkgname,
			          dpkg_collected_package *cpkg)
{
    virtualpkg *list;
    virtualpkg **where;
    list = lookup_virtualpkgtbl(vpkgs, pkgname);
    assert(list != NULL);

    where = &list;
    while((*where)->value.pkg != cpkg) {
	where = &(*where)->next;
	assert(*where != NULL);
    }
    
    delete_virtualpkg(where);

    if (list == NULL) {
	remove_virtualpkgtbl(vpkgs, pkgname);
    } else {
	replace_virtualpkgtbl(vpkgs, pkgname, list);
    }
}

static void add_virtualpackage(virtualpkgtbl *vpkgs, char *package, 
                               char *version, dpkg_collected_package *cpkg)
{
    dpkg_provision value;
    virtualpkg *list, **addto;
    int shouldreplace;
   
    value.pkg = cpkg;
    value.version = version;
    
    list = lookup_virtualpkgtbl(vpkgs, package);
    shouldreplace = (list != NULL);

    addto = &list;
    while (*addto != NULL
	   && packagecmp(cpkg->pkg, (*addto)->value.pkg->pkg) >= 0) 
    {
	addto = &(*addto)->next;
    }
    insert_virtualpkg(addto, value);

    if (shouldreplace) {
	replace_virtualpkgtbl(vpkgs, package, list);
	/* old list is included in new list, so we don't need to free */
    } else {
	add_virtualpkgtbl(vpkgs, package, list);
    }
}

/*************************************************************************
 * Parsing Helper Functions
 */

ownedpackagenamelist *read_packagenames(char *buf) {
    ownedpackagenamelist *result = NULL;
    ownedpackagenamelist **addto = &result;

    DEBUG_ONLY( char *strend = buf + strlen(buf); )
    
    char *sub;
    
    while ((sub = my_strdup(read_packagename(&buf, ",")))) {
	insert_ownedpackagenamelist(addto, sub);
	addto = &(*addto)->next;
	
	while(isspace(*buf)) buf++;
	if (*buf == ',') {
	    buf++;
	    continue;
	}
	if (*buf == '\0') {
	    break;
	}
	
	die("read_packagenames no/bad seperator");
    }
    
    DEBUG_ONLY( assert(buf <= strend); )
    
    return result;
}

static char *read_until_char(char **buf, char *end) {
    static char *result = NULL;
    char *start;
    DEBUG_ONLY( char *strend = *buf + strlen(*buf); )
    int n;
    
    while(isspace(**buf)) (*buf)++;
    
    start = *buf;
    while (**buf && !isspace(**buf) && strchr(end, **buf) == NULL) {
	(*buf)++;
    }
    
    n = *buf - start;
    if (n == 0) return NULL;
    
    result = realloc(result, n + 1);
    if (result == NULL) die("read_until_char alloc:");
    
    strncpy(result, start, n);
    result[n] = '\0';
    
    while(isspace(**buf)) (*buf)++;
    
    DEBUG_ONLY( assert(*buf <= strend); )
    
    return result;
}

static char *read_packagename(char **buf, char *end) {
    return read_until_char(buf, end);
}

deplist *read_dep_and(char *buf) {
    return read_deplist(&buf, ',', '\0'); 
}

static deplist *read_deplist(char **buf, char sep, char end) {
    deplist *result = NULL;
    deplist **addto = &result;
    
    char separs[3] = { sep, end, '\0' };
    
    DEBUG_ONLY( char *strend = *buf + strlen(*buf); )
    
    dependency *sub;
    
    while ((sub = read_dependency(buf, separs))) {
	insert_deplist(addto, sub);
	addto = &(*addto)->next;
	
	while(isspace(**buf)) (*buf)++;
	if (**buf == sep) {
	    (*buf)++;
	    continue;
	}
	if (**buf == '\0' || **buf == end) {
	    break;
	}

	die("read_deplist no/bad seperator");
    }
    
    DEBUG_ONLY( assert(*buf <= strend); )
    
    return result;
}

deplistlist *read_dep_andor(char *buf) {
    deplistlist *result = NULL;
    deplistlist **addto = &result;
    
    deplist *sub;
    
    DEBUG_ONLY( char *strend = buf + strlen(buf); )
    
    while ((sub = read_deplist(&buf, '|', ','))) {
	insert_deplistlist(addto, sub);
	addto = &(*addto)->next;
	
	if (*buf == ',') buf++;
    }
    
    DEBUG_ONLY( assert(buf <= strend); )
    
    return result;
}

static dependency *read_dependency(char **buf, char *end) {
    dependency *dep;
    char *name;
    char newend[10];
    DEBUG_ONLY( char *strend = *buf + strlen(*buf); )
    
    assert(strlen(end) <= 8);
    newend[0] = '('; strcpy(newend + 1, end);
    
    name = my_strdup(read_until_char(buf, newend));
    if (name == NULL) return NULL;
    
    dep = block_malloc(sizeof(dependency));
    if (dep == NULL) die("read_dependency alloc 1:");
    
    dep->package = name;
    
    while(isspace(**buf)) (*buf)++;
    
    if (**buf != '(') {
	dep->op = dr_NOOP;
	dep->version = NULL;
    } else {
	(*buf)++;
	while(isspace(**buf)) (*buf)++;
	/* << , <= , = , >= , >> */
	if (**buf == '<') {
	    (*buf)++;
	    if (**buf == '<') {
		dep->op = dr_LT;
		(*buf)++;
	    } else if (**buf == '=') {
		dep->op = dr_LTEQ;
		(*buf)++;
	    } else {
		/* The forms `<' and `>' were used to mean earlier/later or 
		 * equal, rather than strictly earlier/later, so they should 
		 * not appear in new packages (though `dpkg' still supports 
		 * them).
		 */
		dep->op = dr_LTEQ;
	    }
	} else if (**buf == '>') {
	    (*buf)++;
	    if (**buf == '>') {
		dep->op = dr_GT;
		(*buf)++;
	    } else if (**buf == '=') {
		dep->op = dr_GTEQ;
		(*buf)++;
	    } else {
		dep->op = dr_GTEQ;
	    }
	} else if (**buf == '=') {
	    dep->op = dr_EQ;
	    (*buf)++;
	    if (**buf == '>') {
		dep->op = dr_GTEQ;
		(*buf)++;
	    } else if (**buf == '<') {
		dep->op = dr_LTEQ;
		(*buf)++;
	    }
	} else {
	    /* treat it as an implicit = :( */
	    dep->op = dr_EQ;
	    /* would prefer to: die("read_dependency unknown version op"); */
	}
	
	while (isspace(**buf)) (*buf)++;
	newend[0] = ')';
	dep->version = my_strdup(read_until_char(buf, newend));
	while (isspace(**buf)) (*buf)++;
	
	if (dep->version == NULL) die("read_dependency: no version");
	if (**buf != ')') die("read_dependency: unterminated version");
	(*buf)++;
    }
    
    DEBUG_ONLY( assert(*buf <= strend); )
    
    return dep;
}

static void free_dependency(dependency *dep) {
    if (dep == NULL) return;
    /* block_free(dep->package); */
    /* if (dep->version) block_free(dep->version); */
    block_free(dep, sizeof(dependency));
}

/*************************************************************************
 * Installability Checking
 */

static collpackagelist **get_matching_low(collpackagelist **addto, 
		                          dpkg_packages *pkgs, dependency *dep, int line)
{
    virtualpkg *vpkg;
    for (vpkg = lookup_virtualpkgtbl(pkgs->virtualpkgs, dep->package);
	 vpkg != NULL;
	 vpkg = vpkg->next)
    {
	int add;

	add = 0;
	if (dep->op == dr_NOOP) {
	    add = 1;
	} else if (vpkg->value.version != NULL) {
	    if (cmpversions(vpkg->value.version, dep->op, dep->version)) {
		add = 1;
	    }
	}

	if (add) {
	    insert_l_collpackagelist(addto, vpkg->value.pkg, line);
	    addto = &(*addto)->next;
	}
    }

    return addto;
}

static collpackagelist *get_matching(dpkg_packages *pkgs, deplist *depopts, int line) {
    collpackagelist *list = NULL;
    collpackagelist **addto = &list;
    
    for(; depopts != NULL; depopts = depopts->next) {
	addto = get_matching_low(addto, pkgs, depopts->value, line);
    }

    return list;
}

typedef struct instonelist instonelist;
struct instonelist {
    collpackagelist *curX;
    collpackagelist *instoneX;
    int expandedX;
    struct instonelist *nextX, *prevX, *cutoffX;
};

#define I1CUR(i1)      ((i1)->curX)
#define I1INSTONE(i1)  ((i1)->instoneX)
#define I1CUTOFF(i1)   ((i1)->cutoffX)
#define I1NEXT(i1)     ((i1)->nextX) /* can be modified ! */
#define I1PREV(i1)     ((i1)->prevX)
#define I1EXPANDED(i1) ((i1)->expandedX)

static instonelist *insert_instonelist(instonelist *where, collpackagelist *instone);
static void trim_instonelist_after(instonelist *first);
static void free_instonelist(instonelist *l);

static instonelist *insert_instonelist(instonelist *old, collpackagelist *instone)
{
    instonelist *n = block_malloc(sizeof(instonelist));
    if (n == NULL)
        die("insert_instonelist alloc:");

    n->curX = NULL;
    n->instoneX = instone;
    n->cutoffX = NULL;
    n->nextX = (old ? old->nextX : NULL);
    n->prevX = old;
    n->expandedX = 0;

    if (old) old->nextX = n;
    if (n->nextX) n->nextX->prevX = n;

    return n;
}

static void trim_instonelist_after(instonelist *first) {
    if (!first->nextX) return;
    first->nextX->prevX = NULL;
    free_instonelist(first->nextX);
    first->nextX = NULL;
}

static void free_instonelist(instonelist *l) {
    instonelist *p, *k;
    if (!l) return;
    for (p = l; p->nextX; p = p->nextX);
    do {
        k = p;
        p = k->prevX;
        free_collpackagelist(k->instoneX);
        block_free(k, sizeof(instonelist));
    } while (k != l);
}

static int caninstall(dpkg_packages *pkgs, dpkg_collected_package *cpkg) {
    collpackagelist *conflicts;
    collpackagelist *conf;
    int okay;

    if (cpkg->installed > 0) return 1;
    if (cpkg->conflicted > 0) return 0;

    conflicts = get_matching(pkgs, cpkg->pkg->conflicts, __LINE__);

    okay = 1;
    for (conf = conflicts; conf != NULL; conf = conf->next) {
	if (conf->value->installed > 0) {
	    okay = 0;
	    break;
	}
    }
    free_collpackagelist(conflicts);
    return okay;
}

static void install(dpkg_packages *pkgs, dpkg_collected_package *cpkg) {
    if (cpkg->installed == 0) {
	collpackagelist *conflicts = get_matching(pkgs, cpkg->pkg->conflicts, __LINE__);
	collpackagelist *conf;
	for (conf = conflicts; conf != NULL; conf = conf->next) {
	    if (conf->value == cpkg) continue;
	    assert(conf->value->installed == 0);
	    conf->value->conflicted++;
	}
	free_collpackagelist(conflicts);
    }
    assert(cpkg->conflicted == 0);
    cpkg->installed++;
}

static void uninstall(dpkg_packages *pkgs, dpkg_collected_package *cpkg) {
    assert(cpkg->installed > 0);
    assert(cpkg->conflicted == 0);
    cpkg->installed--;
    if (cpkg->installed == 0) {
	collpackagelist *conflicts = get_matching(pkgs, cpkg->pkg->conflicts, __LINE__);
	collpackagelist *conf;
	for (conf = conflicts; conf != NULL; conf = conf->next) {
	    if (conf->value == cpkg) continue;
	    assert(conf->value->installed == 0);
	    assert(conf->value->conflicted > 0);
	    conf->value->conflicted--;
	}
	free_collpackagelist(conflicts);
    }
}


int checkinstallable2(dpkg_packages *pkgs, char *pkgname) {
    dpkg_collected_package *cpkg = lookup_packagetbl(pkgs->packages, pkgname);
    collpackagelist *cpl = NULL;

    if (cpkg == NULL) return 0;

    insert_collpackagelist(&cpl, cpkg);
    /* cpl gets freed in checkinstallable :-/ */
    return checkinstallable(pkgs, cpl);
}

static void debug_checkinstallable(FILE *out, instonelist *list, 
	instonelist *last, instonelist *pointer) 
{
    instonelist *l;
    fprintf(out, "Status:");

    /* codes:   | = multiple options here
     *          @ = no options can satisfy this dep
     *          + = dependencies that can be expanded have been
     *          * = nothing selected yet
     *          > = where pointer points
     *          ^ = the cut point for where we are
     */

    for (l = list; ; l = I1NEXT(l)) {
	fprintf(out, " ");
	if (l == pointer)           fprintf(out, ">");
	if (l == I1CUTOFF(pointer)) fprintf(out, "^");
	if (I1INSTONE(l) == NULL) {
	    fprintf(out, "@");
	} else {
	    if (I1INSTONE(l)->next != NULL) {
		fprintf(out, "|");
	    }
	    if (I1EXPANDED(l)) {
		fprintf(out, "+");
	    }
	    if (I1CUR(l) == NULL) {
	        fprintf(out, "*%s", I1INSTONE(l)->value->pkg->package);
	    } else {
		fprintf(out, "%s", I1CUR(l)->value->pkg->package);
	    }
	}
	if (l == last) break;
    }
    fprintf(out, " ###\n");
    fflush(out);
}    

static int checkinstallable(dpkg_packages *pkgs, collpackagelist *instoneof) {
    /* We use pkg->installed, pkg->conflicted to note how many
     * times we've used this pkg to satisfy a dependency or installed
     * a package that conflicts with it.
     *    Thus: pkg->installed == 0, or pkg->conflicted == 0
     *
     * We assume these are okay initially, aren't being played with
     * concurrently elsewhere, and make sure they're still okay when
     * we return.
     */
   
    instonelist *list;
    instonelist *last;
    
    instonelist *pointer;

    unsigned long counter = 10000000;

    {
	collpackagelist *cpkg;
        for (cpkg = instoneof; cpkg; cpkg = cpkg->next) {
	    if (cpkg->value->installable == YES) {
		free_collpackagelist(instoneof);
		return 1;
	    }
	}
    }
    
    list = insert_instonelist(NULL, instoneof);

    last = list;
    pointer = list;
    
    while(--counter > 0 && pointer) {
	deplistlist *dep;
	dpkg_collected_package *instpkg; /* convenient alias */
	int i;

#ifndef NDEBUG
	{
	    instonelist *p;
	    for (p = list; p != pointer; p = I1NEXT(p)) {
		assert(p != NULL);
		assert(I1CUR(p) != NULL);
		assert(I1CUR(p)->value != NULL);
		assert(I1CUR(p)->value->installed > 0);
		assert(I1CUR(p)->value->conflicted == 0);
	    }
	    if (I1NEXT(pointer) == NULL) {
		assert(pointer == last);
	    } else {
		for (p = I1NEXT(pointer); p; p = I1NEXT(p)) {
		    if (I1NEXT(p) == NULL) {
 			assert(p == last);
		    }
		    assert(I1CUR(p) == NULL);
		}
	    }
	}
#endif

#ifdef DIAGNOSE
        debug_checkinstallable(stdout, list, last, pointer);
#endif

	if (I1CUR(pointer) == NULL) {
	    I1CUR(pointer) = I1INSTONE(pointer);
	    /* try to choose an already installed package if there is one */
	    while (I1CUR(pointer) != NULL) {
		if (I1CUR(pointer)->value->installed != 0) {
		    break;
		}
		I1CUR(pointer) = I1CUR(pointer)->next;
	    }
	    if (I1CUR(pointer) == NULL) {
		I1CUR(pointer) = I1INSTONE(pointer);
	    }
	    assert(I1CUR(pointer) || !I1INSTONE(pointer));

	    I1CUTOFF(pointer) = last;
	} else {
	    uninstall(pkgs, I1CUR(pointer)->value);
	    trim_instonelist_after(I1CUTOFF(pointer));
	    last = I1CUTOFF(pointer);
	    
	    if (I1CUR(pointer)->value->installed > 0) {
		/* this dependency isn't the issue -- even doing
		 * nothing to satisfy it (ie, using an already
		 * installed package) doesn't do any good. So give up.  
		 */
		I1CUR(pointer) = NULL;
	    } else {
		I1CUR(pointer) = I1CUR(pointer)->next;
	    }
	}
	
	while(I1CUR(pointer) && !caninstall(pkgs, I1CUR(pointer)->value)) {
	    I1CUR(pointer) = I1CUR(pointer)->next;
	}
	
	if (I1CUR(pointer) == NULL) {
	    if (I1PREV(pointer) == NULL) break;
	    pointer = I1PREV(pointer);
	    continue;
	}
	
	instpkg = I1CUR(pointer)->value;
	
	install(pkgs, instpkg);
	
	assert(instpkg->installed > 0);
	if (instpkg->installed == 1) {
            /* if it's been installed exactly once, then this must've been
	     * the first time it was touched, so we need to look at the 
	     * dependencies. If it's the second or later, then we don't care 
	     * about them.
	     */

	    /* if any of the deps can't be satisfied, don't move on */
	    int bother = 1;

	    int expanded = I1EXPANDED(pointer);

	    for (i = 0; i < 4; i++) {
		if (!dependency_counts[i]) continue;
		for (dep = instpkg->pkg->depends[i];
		     dep != NULL; dep = dep->next)
		{
		    collpackagelist *thisdep = get_matching(pkgs, dep->value, __LINE__);

		    if (thisdep == NULL)  {
			bother = 0;

		    } else if (thisdep != NULL && thisdep->next == NULL) {
			collpackagelist *x;

			/* if there's only one way of fulfilling this dep,
			 * do it "ASAP"
			 */

			/* optimisation: if thisdep == foo, but the parent
			 * was foo|bar, then we already know "foo" is not going
			 * to work in this combination, and we can skip it.
			 *
			 * This deals with cases like X deps: Y|bar, bar deps: Y
			 * where bar is a virtual package; cf xlibs
			 */
			for (x = I1INSTONE(pointer); x != I1CUR(pointer); x = x->next) {
			    if (x->value == thisdep->value) {
			        bother = 0;
			        break;
			    }
			}

		        if (I1INSTONE(pointer)->next == NULL) {
		            /* the parent of this entry essentially depends 
			     * on this too, so we'll get it out of the way 
			     * ASAP, to reduce the degree of exponentiation 
			     * in bad cases.
			     *
			     * _However_ we only want to do this _once_ for
			     * any particular node.
			     */
			    if (expanded) {
				/* thisdep isn't used! */
				free_collpackagelist(thisdep);
			    } else {
				insert_instonelist(pointer, thisdep);
	    			I1EXPANDED(pointer) = 1;
			    }
			} else {
			    insert_instonelist(I1CUTOFF(pointer), thisdep);
			}
			if (I1NEXT(last)) last = I1NEXT(last);
			assert(!I1NEXT(last));

		    } else {
			/* otherwise it's a multi possibility dep, so do it
			 * at the end
			 */

		        last = insert_instonelist(last, thisdep);
		    }
		}
	    }
	    if (!bother) {
		/* stay where we are, and try the next possibility */
		continue;
	    }
	}
	
	pointer = I1NEXT(pointer);
    }

    if (counter == 0) {
	unsigned int package_count = 0;
	fprintf(stderr, "AIEEE: counter overflow:");
	assert(pointer != NULL);
	if (I1CUR(pointer) == NULL || I1CUR(pointer)->value == NULL) {
	    /* we're not guaranteed that pointer will make sense here */
	    pointer = I1PREV(pointer);
	}
	for (; pointer != NULL; pointer = I1PREV(pointer)) {
	    if (I1CUR(pointer) == NULL) {
		/* should only happen at pointer, so not here */
		fprintf(stderr, " >> eep, no packages at pointer <<");
		continue;
	    }
	    if (I1CUR(pointer)->value == NULL) {
		/* should never happen */
		fprintf(stderr, " >> eep, no package selected <<");
		continue;
	    }
	    /* the full list is no as interesting as the "guilty" package,
	     * display the number of involved packages instead */
#if 0
	    fprintf(stderr, " %s%s", 
		(I1INSTONE(pointer)->next == NULL ? "" : "|"),
		I1CUR(pointer)->value->pkg->package);
#endif
	    package_count++;
	    uninstall(pkgs, I1CUR(pointer)->value);
	}	
	fprintf(stderr, " %u involved packages.\n", package_count);
	free_instonelist(list);
	/* let the caller know we hit a bad failure */
	return -1;
    }

    if (pointer == NULL) {
	dpkg_collected_package *cpkg = I1CUR(list)->value;
	assert(cpkg->installable != YES);
	cpkg->installable = YES;
	for (pointer = last; pointer != NULL; pointer = I1PREV(pointer)) {
	    if (I1CUR(pointer)->value->installed == 1) {
		packagenamelist **p = &I1CUR(pointer)->value->mayaffect;
#if 0
		while ( *p && (*p)->value < cpkg->pkg->package ) {
		    p = &(*p)->next;
		}
                if (*p == NULL || (*p)->value > cpkg->pkg->package)
#endif
		{
		    insert_packagenamelist(p, cpkg->pkg->package);
		}
	    }
	    uninstall(pkgs, I1CUR(pointer)->value);
	}
	free_instonelist(list);
	return 1;
    } else {
	assert(I1CUR(list) == NULL);
	free_instonelist(list);
	return 0;
    }
}
