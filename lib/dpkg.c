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
static void free_package(dpkg_package *pkg);
static void free_collected_package(dpkg_collected_package *pkg);
static dpkg_paragraph *read_paragraph( FILE *f );
static dpkg_package *read_package( FILE *f );
static collpackagelist **get_matching_low(collpackagelist **addto, 
		                          dpkg_packages *pkgs, dependency *dep, int line);
static collpackagelist *get_matching(dpkg_packages *pkgs, deplist *depopts, int line);
deplist *read_dep_and(char *buf);
deplistlist *read_dep_andor(char *buf);
ownedpackagenamelist *read_packagenames(char *buf);
static dpkg_sources *read_sources_file(char *filename, int n_arches);
static dpkg_source *new_source(dpkg_sources *owner);
static dpkg_source *read_source(FILE *f, dpkg_sources *owner);
static deplist *read_deplist(char **buf, char sep, char end);
static dependency *read_dependency(char **buf, char *end);
static void add_virtualpackage(virtualpkgtbl *vpkgs, char *package, 
                               char *version, dpkg_collected_package *cpkg);
static void remove_virtualpackage(virtualpkgtbl *vpkgs, char *pkgname,
			          dpkg_collected_package *cpkg);
static char *read_packagename(char **buf, char *end);
static char *read_until_char(char **buf, char *end);
void add_package(dpkg_packages *pkgs, dpkg_package *pkg);
void remove_package(dpkg_packages *pkgs, dpkg_collected_package *pkg);
static dpkg_source_note *copy_source_note(dpkg_source_note *srcn);

#if 0
static inline void *bm(size_t s, int n) { void *res = block_malloc(s); fprintf(stderr, "ALLOCED: %d %p %lu\n", n, res, s); return res; }
static inline void bf(void *p, size_t s, int n) { block_free(p,s); fprintf(stderr, "FREED: %d %p %lu\n", n, p, s); }

#define block_malloc(s) bm(s,__LINE__)
#define block_free(p,s) bf(p,s,__LINE__)
#endif

#define block_malloc(s) block_malloc2(s, __LINE__)

static char *priorities[] = {
    "required",
    "important",
    "standard",
    "optional",
    "extra",
    NULL
};

static char *dependency_title[] = {
    "Pre-Depends", "Depends", "Recommends", "Suggests", NULL
};

static int dependency_counts[] = { 1, 1, 0, 0 };

char *dependency_relation_sym[] = {"*", "<<", "<=", "=", ">=", ">>"};

#define SMB_SIZE (1<<22)
struct stringmemblock {
	struct stringmemblock *next;
	size_t last;
	char mem[SMB_SIZE];
};
static struct stringmemblock *stringmemory = NULL;
static int stringmemorycount = 0;
static const unsigned long stringmemblocksizekib = (unsigned long) sizeof(struct stringmemblock) / 1024;

char *my_strdup(char *foo) {
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

char *my_rep_strdup(char *foo) {
    static char *repeats[1000] = {0};
    int i;

    for (i = 0; i < 1000; i++) {
	if (repeats[i] == NULL) {
	    DEBUG_ONLY(fprintf(stderr, "REPEAT NR %d\n", i+1); )
	    return repeats[i] = my_strdup(foo);
	}
	if (strcmp(repeats[i], foo) == 0) return repeats[i];
    }

    return my_strdup(foo);
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
 * Dpkg Control/Packages/etc Operations
 */

static dpkg_paragraph *read_paragraph( FILE *f ) {
    dpkg_paragraph *result;
    static int line_size = 0;
    static char *line = NULL;
    char *pch;
   
    dpkg_entry *c_entry = NULL;
    char *c_value = NULL;
   
    if (line == NULL) {
        line_size = 10;
	line = malloc(line_size);
	if (line == NULL) die("read_paragraph alloc 0:");
    }
 
    result = block_malloc( sizeof(dpkg_paragraph) );
    if (result == NULL) die("read_paragraph alloc 1:");
    
    result->n_entries = 0;
    result->entry = NULL;
    result->n_allocated = 0;
    
    while(fgets(line, line_size, f)) {
	while (!feof(f) && *line && line[strlen(line)-1] != '\n') {
	    line = realloc(line, line_size * 2);
	    if (!line) die("read_paragraph realloc:");
	    fgets(line + strlen(line), line_size, f);
	    line_size *= 2;
        }

	if (line[0] == '\n') break;
	
	if (isspace(line[0])) {
	    if (c_value == NULL)
		die("read_paragraph early spaces");

	    if (c_entry == NULL) {
		/* no need to bother */
	    } else {
	        /* extend the line */
	        c_value = realloc(c_value, strlen(c_value) + strlen(line) + 1);
	        if (c_value == NULL)
		    die("read_paragraph realloc c_value:");
	    
	        strcat(c_value, line);
	    }
	} else {
	    if (c_entry) {
		    c_entry->value = my_strdup(c_value);
		    c_value[0] = '\0';
		    free(c_value); 
		    c_value = NULL;
	    } else if (c_value) {
		    free(c_value);
		    c_value = NULL;
	    }
	    pch = strchr(line, ':');
	    if (pch == NULL) {
                fprintf(stderr, "the line was: \"%s\"\n", line);
		die("read_paragraph: no colon");
            }
	    
	    *pch = '\0';
	    while(isspace(*++pch));

	    if (strcmp(line, "Description") == 0) {
		c_value = strdup(pch);
		c_entry = NULL;
	    } else {
	        assert(result->n_entries <= result->n_allocated);
	        if (result->n_entries >= result->n_allocated) {
		    result->n_allocated += 10;
		    result->entry = realloc( result->entry,
					     sizeof(dpkg_entry)
					     * result->n_allocated);
		    if (result->entry == NULL)
		        die("read_paragraph realloc entry:");
	        }

	        c_entry = &result->entry[result->n_entries++];
	        c_entry->name = my_rep_strdup(line);
	        c_value = strdup(pch);
	    }
	}
    }

    if (c_entry) {
	c_entry->value = my_strdup(c_value);
	c_value[0] = '\0';
	free(c_value);
	c_value = NULL;
    }

    if (result->n_entries == 0) {
	if (result->entry) free(result->entry);
	block_free(result, sizeof(dpkg_paragraph));
	return NULL;
    } else {
        result->entry = realloc(result->entry, 
	    sizeof(result->entry[0]) * result->n_entries);
	result->n_allocated = result->n_entries;
    }

    return result;
}

static void write_paragraph(FILE *f, dpkg_paragraph *p) {
    int i;

    for (i = 0; i < p->n_entries; i++) {
	fprintf(f, "%s: %s", p->entry[i].name, p->entry[i].value);
    }
    fprintf(f, "\n");
}


static void free_paragraph(dpkg_paragraph *p) {
    int i;
    
    if (p == NULL) return;
    
    for (i = 0; i < p->n_entries; i++) {
	/* block_free(p->entry[i].name); */
	/* block_free(p->entry[i].value); */
    }
    free(p->entry);
    block_free(p, sizeof(dpkg_paragraph));
}

/*************************************************************************
 * Basic Package Operations
 */

static dpkg_package *new_package(void) {
    dpkg_package *result;
    
    result = block_malloc(sizeof(dpkg_package));
    if (result == NULL) die("new_package alloc:");
    
    result->package    = NULL;
    result->version    = NULL;

    result->priority   = 0;
    result->arch_all   = 0;
    
    result->source     = NULL;
    result->source_ver = NULL;
    
    result->depends[0] = NULL;
    result->depends[1] = NULL;
    result->depends[2] = NULL;
    result->depends[3] = NULL;
    
    result->conflicts  = NULL;
    
    result->provides   = NULL;
    result->details    = NULL;
    
    return result;
}

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

static void free_package(dpkg_package *pkg) {
    int i;
    if (pkg == NULL) return;
    
    /* block_free(pkg->package);
     * block_free(pkg->version);
     * block_free(pkg->source);
     * block_free(pkg->source_ver); */

    for (i = 0; i < 4; i++)
	free_deplistlist(pkg->depends[i]);

    free_deplist(pkg->conflicts);
    free_ownedpackagenamelist(pkg->provides);
    
    free_paragraph(pkg->details);
    
    block_free(pkg, sizeof(dpkg_package));
}

static dpkg_package *read_package( FILE *f ) {
    dpkg_package *result;
    dpkg_paragraph *para;
    dpkg_entry *e;
    int i;

    para = read_paragraph(f);
    if (para == NULL) return NULL;
    
    result = new_package();
    result->details = para;
    
    for (e = &para->entry[0]; e < &para->entry[para->n_entries]; e++) {
	if (strcasecmp("Package", e->name) == 0) {
	    result->package = my_strdup(e->value);
	    if (result->package == NULL)
		die("read_package my_strdup:");
	    result->package[strlen(result->package)-1] = '\0';
	}
	
	if (strcasecmp("Version", e->name) == 0) {
	    result->version = my_strdup(e->value);
	    if (result->version == NULL)
		die("read_package my_strdup:");
	    result->version[strlen(result->version)-1] = '\0';
	}
	
	if (strcasecmp("Priority", e->name) == 0) {
	    int i;
	    for (i = 0; priorities[i] != NULL; i++) {
		if (strcasecmp(priorities[i], e->value))
		    break;
	    }
	    result->priority = i;
	    if (priorities[i] == NULL) {
		die("read_package: unknown priority");
	    }
	}

	if (strcasecmp("Architecture", e->name) == 0) {
	    if (strncasecmp(e->value, "all", 3) == 0) {
		if (!e->value[3] || isspace(e->value[3])) {
	            result->arch_all = 1;
		}
	    }
	}
	
	for (i = 0; dependency_title[i] != NULL; i++) {
	    if (strcasecmp(dependency_title[i], e->name) == 0) {
		result->depends[i] = read_dep_andor(e->value);
	    }
	}
	
	if (strcasecmp("Conflicts", e->name) == 0)
	    result->conflicts = read_dep_and(e->value);
	
	if (strcasecmp("Provides", e->name) == 0)
	    result->provides = read_packagenames(e->value);
	
	if (strcasecmp("source", e->name) == 0) {
	    char *pch = e->value;
	    
	    assert(result->source == NULL);
	    assert(result->source_ver == NULL);
	    
	    result->source = my_strdup(read_packagename(&pch, "("));
	    if (result->source == NULL)
		die("read_package: bad source header");
	    
	    while(isspace(*pch)) pch++;
	    if (*pch == '(') {
		pch++;
		result->source_ver = my_strdup(read_until_char(&pch, ")"));
		if (result->source_ver == NULL)
		    die("read_package: bad source version");
		while(isspace(*pch)) pch++;
		if (*pch != ')')
		    die("read_package: unterminated ver");
	    }
	}
    }

    if (result->source == NULL) {
	assert(result->source_ver == NULL);
	result->source = my_strdup(result->package);
    }
    if (result->source_ver == NULL) {
	result->source_ver = my_strdup(result->version);
    }
    
    return result;
}

static void freesize(void *p, size_t s) { (void)s; free(p); }

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

/* container for owned pkgs */
LIST_IMPL(ownedpackagelist, dpkg_package *, free_package, 
		block_malloc, block_free);

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

dpkg_packages *get_architecture(dpkg_sources *srcs, char *arch) {
    int i, arch_index;
    dpkg_packages *result;
    sourcetbl_iter srci;
    ownedpackagelist *p;
    
    arch_index = -1;
    for (i = 0; i < srcs->n_arches; i++) {
	if (strcmp(srcs->archname[i], arch) == 0) {
	    arch_index = i;
	    break;
	}
    }
    if (arch_index == -1) die("get_architecture: unknown arch");
    
    result = new_packages(arch);

    for (srci = first_sourcetbl(srcs->sources);
	 !done_sourcetbl(srci);
	 srci = next_sourcetbl(srci))
    {
	for (p = srci.v->packages[arch_index]; p != NULL; p = p->next) {
	    add_package(result, p->value);
	}
    }
    
    return result;
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

satisfieddep *new_satisfieddep(void) {
	satisfieddep *sd = block_malloc(sizeof(satisfieddep));
	if (!sd) die("new_satisfieddep alloc:");
	return sd;
}

void free_satisfieddep(satisfieddep *sd) {
	if (!sd) return;
	free_packagelist(sd->pkgs);
	block_free(sd, sizeof(satisfieddep));
}

LIST_IMPL(satisfieddeplist, satisfieddep *, free_satisfieddep, block_malloc, block_free);

packagelist *collpkglist2pkglist(collpackagelist *l) {
	packagelist *r = NULL;
	packagelist **addto = &r;

	for (; l != NULL; l = l->next) {
		insert_packagelist(addto, l->value->pkg);
		addto = &(*addto)->next;
	}

	return r;
}

satisfieddeplist *checkunsatisfiabledeps(dpkg_packages *pkgs, 
					 deplistlist *deps) {
	satisfieddeplist *unsatisfiable = NULL;
	satisfieddeplist **addto = &unsatisfiable;
	satisfieddep *sd;
	collpackagelist *deppkgs;

	for (; deps != NULL; deps = deps->next) {
		/* deplist *dep; */
		/* for (dep = deps->value; dep != NULL; dep = dep->next) { */
			sd = new_satisfieddep();
			/* sd->dep = dep->value; */
			sd->depl = deps->value;

			deppkgs = NULL;
			/* get_matching_low(&deppkgs, pkgs, dep->value); */
			deppkgs = get_matching(pkgs, deps->value, __LINE__);
			sd->pkgs = collpkglist2pkglist(deppkgs);
			free_collpackagelist(deppkgs);

			insert_satisfieddeplist(addto, sd);
			addto = &(*addto)->next;
		/* } */
	}

	return unsatisfiable;
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

int checkinstallable(dpkg_packages *pkgs, collpackagelist *instoneof) {
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
	    fprintf(stderr, " %s%s", 
		(I1INSTONE(pointer)->next == NULL ? "" : "|"),
		I1CUR(pointer)->value->pkg->package);
	    uninstall(pkgs, I1CUR(pointer)->value);
	}	
	fprintf(stderr, ".\n");
	free_instonelist(list);
	return 0;
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

/******************/

HASH_IMPL(sourcetbl, char *, dpkg_source *, SIZEOFHASHMAP, strhash, strcmp,
	  KEEP(char*), free_source);

static dpkg_sources *read_sources_file(char *filename, int n_arches) {
    FILE *f; 
    dpkg_sources *result;
    dpkg_source *src;
    int i;

    f = fopen(filename, "r");
    if (f == NULL && errno != ENOENT) {
	die("read_sources_file: couldn't open file:");
    }

    result = block_malloc(sizeof(dpkg_sources));
    if (result == NULL) die("read_sources_file alloc 1:");

    result->n_arches = n_arches;
    result->archname = block_malloc(sizeof(char*) * n_arches);
    if (result->archname == NULL) die("read_sources_file alloc 2:");
    for (i = 0; i < n_arches; i++) result->archname[i] = NULL;
    result->unclaimedpackages = block_malloc(sizeof(ownedpackagelist*) 
					     * n_arches);
    if (result->unclaimedpackages == NULL) die("read_sources_file alloc 3:");
    for (i = 0; i < n_arches; i++) result->unclaimedpackages[i] = NULL;

    result->sources = new_sourcetbl();

    if (f != NULL) {
        while ((src = read_source(f, result))) {
	    dpkg_source *old = lookup_sourcetbl(result->sources, src->package);
	    if (old == NULL) {
	        add_sourcetbl(result->sources, src->package, src);
            } else {
                if (versioncmp(old->version, src->version) || 1) {
                    int i;
		    old = replace_sourcetbl(result->sources, src->package, src);
                    for (i = 0; i < old->owner->n_arches; i++) {
	                assert(old->packages[i] == NULL);
                    }
		    free_source(old);
		} else {
                    int i;
                    for (i = 0; i < src->owner->n_arches; i++) {
	                assert(src->packages[i] == NULL);
                    }
		    free_source(src);
		}
	    }
        }
        fclose(f);
    }
    
    return result;    
}

void free_sources(dpkg_sources *s) {
    int i;
    if (s == NULL) return;
    free_sourcetbl(s->sources);
    for (i = 0; i < s->n_arches; i++) {
	/* block_free(s->archname[i]); */
	free_ownedpackagelist(s->unclaimedpackages[i]);
    }
    block_free(s->archname, s->n_arches * sizeof(char*));
    block_free(s->unclaimedpackages, s->n_arches * sizeof(ownedpackagelist*));
    block_free(s, sizeof(dpkg_sources));
}

static dpkg_source *new_source(dpkg_sources *owner) {
    dpkg_source *result;
    int i;
    
    result = block_malloc(sizeof(dpkg_source));
    if (result == NULL) die("new_source alloc 1:");
    
    result->package = NULL;
    result->version = NULL;
    result->details = NULL;
    result->fake = 0;

    result->owner = owner;
    result->packages = block_malloc(sizeof(packagelist*) * owner->n_arches);
    if (result->packages == NULL) die("new_source alloc 2:");
    for (i = 0; i < owner->n_arches; i++) {
	result->packages[i] = NULL;
    }

    return result;
}

static dpkg_source *read_source(FILE *f, dpkg_sources *owner) {
    dpkg_source *result;
    dpkg_paragraph *para;
    dpkg_entry *e;

    para = read_paragraph(f);
    if (para == NULL) return NULL;
    
    result = new_source(owner);
    result->details = para;
    
    for (e = &para->entry[0]; e < &para->entry[para->n_entries]; e++) {
	if (strcmp("Package", e->name) == 0) {
	    result->package = my_strdup(e->value);
	    if (result->package == NULL)
		die("read_source strdup:");
	    result->package[strlen(result->package)-1] = '\0';
	}
	
	if (strcmp("Version", e->name) == 0) {
	    result->version = my_strdup(e->value);
	    if (result->version == NULL)
		die("read_source strdup:");
	    result->version[strlen(result->version)-1] = '\0';
	}
    }

    return result;
}

void free_source(dpkg_source *s) {
    int i;
    if (s == NULL) return;
    assert(s->owner != NULL); /* shouldn't have allocated it */
    /* block_free(s->package); */
    /* block_free(s->version); */
    free_paragraph(s->details);
    for (i = 0; i < s->owner->n_arches; i++) {
	free_ownedpackagelist(s->packages[i]);
    }
    block_free(s->packages, s->owner->n_arches * sizeof(ownedpackagelist*));
    block_free(s, sizeof(dpkg_source));
}

/******************************/

dpkg_sources *read_directory(char *dir, int n_arches, char *archname[]) {
    char buf[1000];
    dpkg_sources *srcs;
    int i;
    
    snprintf(buf, 1000, "%s/Sources", dir);
    srcs = read_sources_file(buf, n_arches);

    for (i = 0; i < n_arches; i++) {
	FILE *f;
	dpkg_package *pkg;

	srcs->archname[i] = my_strdup(archname[i]);

	snprintf(buf, 1000, "%s/Packages_%s", dir, archname[i]);
	f = fopen(buf, "r");
	if (f == NULL && errno != ENOENT) die("load_dirctory fopen:");
        if (f != NULL) {
	    while ((pkg = read_package(f))) {
	        dpkg_source *src = lookup_sourcetbl(srcs->sources, pkg->source);
	        if (src == NULL) {
		    src = new_source(srcs);
		    src->fake = 1;
		    src->package = my_strdup(pkg->source);
		    src->version = my_strdup(pkg->source_ver);
		    add_sourcetbl(srcs->sources, src->package, src);
		} 
                insert_ownedpackagelist(&src->packages[i], pkg);
	    }
	    fclose(f);
	}
    }	

    return srcs;
}

void write_directory(char *dir, dpkg_sources *srcs) {
    FILE *src;
    FILE *archfile[100];
    char buf[1000];
    int i;
    sourcetbl_iter srciter;

    snprintf(buf, 1000, "%s/Sources", dir);
    src = fopen(buf, "w");
    if (!src) die("write_directory: Couldn't open Sources file for output");

    for (i = 0; i < srcs->n_arches; i++) {
	snprintf(buf, 1000, "%s/Packages_%s", dir, srcs->archname[i]);
	archfile[i] = fopen(buf, "w");
    }

    for (srciter = first_sourcetbl(srcs->sources);
	 !done_sourcetbl(srciter);
	 srciter = next_sourcetbl(srciter))
    {
	ownedpackagelist *p;
	int i;

	if (!srciter.v->fake) 
		write_paragraph(src, srciter.v->details);
	
	for (i = 0; i < srcs->n_arches; i++) {
	    for (p = srciter.v->packages[i]; p != NULL; p = p->next) {
		write_paragraph(archfile[i], p->value->details);
	    }
	}
    }
    
    fclose(src);
    for (i = 0; i < srcs->n_arches; i++) {
	fclose(archfile[i]);
    }
}

/*********************/

HASH_IMPL(sourcenotetbl, char *, dpkg_source_note *, SIZEOFHASHMAP, strhash, strcmp,
	  KEEP(char*), free_source_note);

dpkg_source_note *new_source_note(dpkg_source *src, int n_arches) {
    dpkg_source_note *result = block_malloc(sizeof(dpkg_source_note));
    int i;

    if (result == NULL) die("new_source_note alloc 1:");    
    result->source = src;
    result->n_arches = n_arches;
    result->binaries = block_malloc(n_arches * sizeof(packagelist*));
    if (result->binaries == NULL) die("new_source_note alloc 2:");
    for (i = 0; i < n_arches; i++) {
	result->binaries[i] = NULL;
    }
    return result;
} 

void free_source_note(dpkg_source_note *srcn) {
    int i;
    
    if (srcn == NULL) return;

    if (srcn->binaries != NULL) {
	for (i = 0; i < srcn->n_arches; i++) {
	    free_packagelist(srcn->binaries[i]);
	}
	block_free(srcn->binaries, sizeof(packagelist*) * srcn->n_arches);
    }
    block_free(srcn, sizeof(dpkg_source_note));
}    

#ifdef DEBUG
static int is_sources_note(dpkg_sources_note *srcsn) {
    int i;

    assert(srcsn != NULL);
    assert(srcsn->magic == 0xa1eebabe);
    assert(srcsn->pkgs != NULL);
    for (i = 0; i < srcsn->n_arches; i++) {
        assert(srcsn->pkgs[i] != NULL && srcsn->archname[i] != NULL);
        assert(strcmp(srcsn->archname[i], srcsn->pkgs[i]->arch) == 0);
    }

    return 1;
}
#endif

dpkg_sources_note *new_sources_note(int n_arches, char **archname) {
    dpkg_sources_note *result = block_malloc(sizeof(dpkg_sources_note));
    int i;

    if (result == NULL) die("new_sources_note alloc 1:");
    result->magic = 0xA1EEBABE;
    result->sources = new_sourcenotetbl();
    result->pkgs = block_malloc(n_arches * sizeof(dpkg_packages*));
    if (result->pkgs == NULL) die("new_sources_note alloc 2:");
    result->archname = block_malloc(n_arches * sizeof(char*));
    if (result->archname == NULL) die("new_sources_note alloc 3:");

    result->n_arches = n_arches;
    for (i = 0; i < n_arches; i++) {
	result->archname[i] = my_strdup(archname[i]);
	result->pkgs[i] = new_packages(result->archname[i]);
    }
    result->undo = NULL;
    return result;
}

void free_sources_note(dpkg_sources_note *srcsn) {
    int i;
    if (srcsn == NULL) return;
    assert(is_sources_note(srcsn));
    srcsn->magic = 0xBABEA1EE;
    free_sourcenotetbl(srcsn->sources);
    for (i = 0; i < srcsn->n_arches; i++) {
	free_packages(srcsn->pkgs[i]);
	/* block_free(srcsn->archname[i]); */
    } 
    block_free(srcsn->pkgs, sizeof(dpkg_packages*) * srcsn->n_arches);
    block_free(srcsn->archname, sizeof(char*) * srcsn->n_arches);
    free_source_note_listlist(srcsn->undo);
    block_free(srcsn, sizeof(dpkg_sources_note));
}

static void new_op(dpkg_sources_note *srcsn) {
    assert(is_sources_note(srcsn));
    insert_source_note_listlist(&srcsn->undo, NULL);
}
static void save_source_note(dpkg_sources_note *srcsn, dpkg_source_note *srcn) {
    source_note_list **where;
    assert(is_sources_note(srcsn));
    assert(srcsn->undo != NULL);

    for (where = &srcsn->undo->value; 
	 *where != NULL;
	 where = &(*where)->next) 
    {
        if ((*where)->value->source == srcn->source) 
	    return; 	/* already saved */
    }

    insert_source_note_list(where, copy_source_note(srcn));
}
static void save_empty_source_note(dpkg_sources_note *srcsn, dpkg_source *src) {
    dpkg_source_note *srcn;
    source_note_list **where;

    for (where = &srcsn->undo->value; 
	 *where != NULL; 
	 where = &(*where)->next)
    {
        if ((*where)->value->source == src) 
	    return; 	/* already saved */
    }

    srcn = block_malloc(sizeof(dpkg_source_note));
    if (srcn == NULL) die("save_empty_source_note alloc:");
    assert(is_sources_note(srcsn));

    srcn->source = src;
    srcn->n_arches = 0;
    srcn->binaries = NULL;

    insert_source_note_list(where, srcn);
}

typedef enum { DO_ARCHALL = 0, SKIP_ARCHALL = 1 } do_this;
static void remove_binaries_by_arch(dpkg_sources_note *srcsn,
				    dpkg_source_note *srcn, int archnum,
				    do_this arch_all) 
{
    packagelist *p;
    packagelist *leftovers = NULL, **addto = &leftovers;
    assert(is_sources_note(srcsn));

    assert(arch_all == SKIP_ARCHALL || NULL == lookup_sourcenotetbl(srcsn->sources,srcn->source->package));
	/* if we're removing the entire binary, we should already have
	 * removed the source. if we're removing just the binaries on this
	 * arch (not arch:all) then we may be keeping the source
	 *
	 * really a logical XOR, I think. we don't rely on this assertion
	 * here 
	 */

    for (p = srcn->binaries[archnum]; p != NULL; p = p->next) {
	dpkg_collected_package *cpkg;
	if (arch_all == SKIP_ARCHALL && p->value->arch_all) {
		insert_packagelist(addto, p->value);
		addto = &(*addto)->next;
		continue;
	}
	cpkg = lookup_packagetbl(srcsn->pkgs[archnum]->packages,
				 p->value->package);
	remove_package(srcsn->pkgs[archnum], cpkg);
    }
    free_packagelist(srcn->binaries[archnum]);
    srcn->binaries[archnum] = leftovers;
}

typedef enum { NOTUNDOABLE = 0, UNDOABLE = 1 } undoable;
static void add_binaries_by_arch(dpkg_sources_note *srcsn,
				 dpkg_source_note *srcn, dpkg_source *src,
				 int archnum, undoable undoop, do_this arch_all) 
{
    ownedpackagelist *p;
    const char *archname = srcsn->archname[archnum];
    int origarchnum = -1;
    int i;

    assert(is_sources_note(srcsn));
    assert(srcn == lookup_sourcenotetbl(srcsn->sources,srcn->source->package));
    for (i = 0; i < src->owner->n_arches; i++) {
	if (strcmp(archname, src->owner->archname[i]) == 0) {
	    origarchnum = i;
	    break;
	}
    }
    if (origarchnum == -1) return; /* nothing to add, no biggie */

    for (p = src->packages[origarchnum]; p != NULL; p = p->next) {
	dpkg_collected_package *cpkg;

	if (arch_all == SKIP_ARCHALL && p->value->arch_all) continue;

	if ((cpkg = lookup_packagetbl(srcsn->pkgs[archnum]->packages, 
				      p->value->package)))
        {
	    dpkg_source_note *srcnB;
	    packagelist **p;

	    if (!undoop) {
		printf("conflict w/o undo: binary %s, owned by %s, replaced by %s\n", cpkg->pkg->package, cpkg->pkg->source, src->package);
                fflush(stdout);
            }
	    srcnB = lookup_sourcenotetbl(srcsn->sources, cpkg->pkg->source);
            assert(srcnB != NULL);
                
            for (p = &srcnB->binaries[archnum]; *p != NULL; p = &(*p)->next) {
                if ((*p)->value == cpkg->pkg) break;
            }
            assert(*p != NULL); /* binary should be from source */

	    assert(undoop);
            save_source_note(srcsn, srcnB);
	    remove_package(srcsn->pkgs[archnum], cpkg);
            remove_packagelist(p);
	}

	add_package(srcsn->pkgs[archnum], p->value);
	insert_packagelist(&srcn->binaries[archnum], p->value);
    }
}    

void upgrade_source(dpkg_sources_note *srcsn, dpkg_source *src) {
    dpkg_source_note *srcn;
    int i;
   
    new_op(srcsn);
 
    assert(is_sources_note(srcsn));
    /* first, find the old source, if it exists */
    srcn = remove_sourcenotetbl(srcsn->sources, src->package);
    if (srcn != NULL) {
        save_source_note(srcsn, srcn);
	for (i = 0; i < srcn->n_arches; i++) {
	    remove_binaries_by_arch(srcsn, srcn, i, DO_ARCHALL);
	}
	free_source_note(srcn);
    } else {
        save_empty_source_note(srcsn, src);
    }
    
    /* then add the new one */    
    srcn = new_source_note(src, srcsn->n_arches);   
    add_sourcenotetbl(srcsn->sources, src->package, srcn);
    for (i = 0; i < srcsn->n_arches; i++) {
	add_binaries_by_arch(srcsn, srcn, src, i, UNDOABLE, DO_ARCHALL);
    }
    assert(is_sources_note(srcsn));
}

void upgrade_arch(dpkg_sources_note *srcsn, dpkg_source *src, char *arch) {
    dpkg_source_note *srcn;
    int archnum = -1;
    int i;

    assert(is_sources_note(srcsn));
    /* first, find the old source */
    srcn = lookup_sourcenotetbl(srcsn->sources, src->package);

    assert(srcn != NULL);
    new_op(srcsn);
    save_source_note(srcsn, srcn);

    /* then lookup the archnum */
    for (i = 0; i < srcsn->n_arches; i++) {
	if (strcmp(arch, srcsn->archname[i]) == 0) {
	    archnum = i;
	    break;
	}
    }
    if (archnum == -1) die("upgrade_arch: unknown arch");
    
    /* then remove the old stuff and add the new */    
    remove_binaries_by_arch(srcsn, srcn, archnum, SKIP_ARCHALL);
    add_binaries_by_arch(srcsn, srcn, src, archnum, UNDOABLE, SKIP_ARCHALL);
    assert(is_sources_note(srcsn));
}

void remove_source(dpkg_sources_note *srcsn, char *name) {
    dpkg_source_note *srcn;
    int i;

    assert(is_sources_note(srcsn));
    srcn = remove_sourcenotetbl(srcsn->sources, name);
    assert(srcn != NULL);

    new_op(srcsn);
    save_source_note(srcsn, srcn);
    for (i = 0; i < srcn->n_arches; i++) {
        remove_binaries_by_arch(srcsn, srcn, i, DO_ARCHALL);
    }
    free_source_note(srcn);
    assert(is_sources_note(srcsn));
}

int can_undo(dpkg_sources_note *srcsn) {
    assert(is_sources_note(srcsn));
    return srcsn->undo != NULL;
}

void undo_change(dpkg_sources_note *srcsn) {
    dpkg_source_note *srcnO, *srcnC; /* old, current */
    source_note_list *srcnl;
    int i;

    assert(is_sources_note(srcsn));
    assert(can_undo(srcsn));

    srcnl = remove_source_note_listlist(&srcsn->undo);

    while(srcnl) {
        srcnO = remove_source_note_list(&srcnl);
        assert(srcnO != NULL); /* can_undo() implies this is true... */
	
        srcnC = remove_sourcenotetbl(srcsn->sources, srcnO->source->package);
        if (srcnC != NULL) {
	    for (i = 0; i < srcnC->n_arches; i++) {
	        remove_binaries_by_arch(srcsn, srcnC, i, DO_ARCHALL);
	    }
	    free_source_note(srcnC);
            assert(!lookup_sourcenotetbl(srcsn->sources, 
					 srcnO->source->package));
        }

        if (srcnO->binaries == NULL) {
            /* no original source */
            assert(srcnC != NULL); /* some sort of no-op? freaky. */
	    free_source_note(srcnO);
        } else {
            packagelist *p;
            /* original source */
            add_sourcenotetbl(srcsn->sources, srcnO->source->package, srcnO);
            for (i = 0; i < srcsn->n_arches; i++) {
                for (p = srcnO->binaries[i]; p != NULL; p = p->next) {
		    add_package(srcsn->pkgs[i], p->value);
                }
            }
        }
    }
}

LIST_IMPL(source_note_list, dpkg_source_note *, free_source_note, 
          block_malloc, block_free);
LIST_IMPL(source_note_listlist, source_note_list *, free_source_note_list, 
          block_malloc, block_free);

void commit_changes(dpkg_sources_note *srcsn) {
    assert(is_sources_note(srcsn));
    free_source_note_listlist(srcsn->undo);
    srcsn->undo = NULL;
}

dpkg_source_note *copy_source_note(dpkg_source_note *srcn) {
    dpkg_source_note *srcn2;
    packagelist *src, **dest;
    int i;

    assert(srcn->binaries != NULL);

    srcn2 = block_malloc(sizeof(dpkg_source_note));
    if (srcn2 == NULL) die("copy_source_note alloc:");

    srcn2->source = srcn->source;
    srcn2->n_arches = srcn->n_arches;
    srcn2->binaries = block_malloc(sizeof(packagenamelist*) * srcn2->n_arches);
    if (srcn2->binaries == NULL) die("copy_source_note alloc:");

    for (i = 0; i < srcn2->n_arches; i++) {
        dest = &(srcn2->binaries[i]);
        *dest = NULL;
        for (src = srcn->binaries[i]; src; src = src->next) {
            insert_packagelist(dest, src->value);
            dest = &((*dest)->next);
        }
    }

    return srcn2;
}

void write_notes(char *dir, dpkg_sources_note *srcsn) {
    FILE *src;
    FILE *archfile[100];
    char buf[1000];
    int i;
    sourcenotetbl_iter srciter;

    assert(is_sources_note(srcsn));
    snprintf(buf, 1000, "%s/Sources", dir);
    src = fopen(buf, "w");
    for (i = 0; i < srcsn->n_arches; i++) {
	snprintf(buf, 1000, "%s/Packages_%s", dir, srcsn->archname[i]);
	archfile[i] = fopen(buf, "w");
    }

    for (srciter = first_sourcenotetbl(srcsn->sources);
	 !done_sourcenotetbl(srciter);
	 srciter = next_sourcenotetbl(srciter))
    {
	packagelist *p;
	int i;

	if (!srciter.v->source->fake)
		write_paragraph(src, srciter.v->source->details);
	
	for (i = 0; i < srcsn->n_arches; i++) {
	    for (p = srciter.v->binaries[i]; p != NULL; p = p->next) {
		write_paragraph(archfile[i], p->value->details);
	    }
	}
    }
    
    fclose(src);
    for (i = 0; i < srcsn->n_arches; i++) {
	fclose(archfile[i]);
    }
}

