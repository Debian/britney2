#include <stdlib.h>
#include <unistd.h>

#include <assert.h>

#include "dpkg.h"

#if 0
static void checknewsrc(sourcetbl *srcstbl, dpkg_source *cur, void *data) {
    dpkg_sources *oldsrc = data;
    dpkg_source *old;
    old = lookup_sourcetbl(oldsrc->sources, cur->package);
    if (old == NULL) {
	printf("New: %s (%s)\n", cur->package, cur->version );
    } else if (strcmp(old->version, cur->version) != 0) {
	printf("Updated: %s (%s, was %s)\n",
	       cur->package, cur->version, old->version );
    } else {
	dpkg_source *src2;
	src2 = remove_sourcetbl(srcstbl, cur->package);
	assert(cur == src2);
	free_source(cur);
    }	
}

static void checkoldsrc(sourcetbl *oldsrctbl, dpkg_source *old, void *data) {
    dpkg_sources *src = data;
    dpkg_source *cur;
    (void)oldsrctbl;
    cur = lookup_sourcetbl(src->sources, old->package);
    if (cur == NULL) {
	printf("Removed: %s (was %s)\n", old->package, old->version );
    }
}

static void checkuptodate(sourcetbl *srctbl, dpkg_source *src, void *data) {
    int i;
    int remove;
    ownedpackagelist **p;
    dpkg_sources *srcs = data;

    (void)srctbl;

    remove = 0;
    for (i = 0; i < srcs->n_arches; i++) {
	p = &src->packages[i];
	while(*p != NULL) {
	    if (strcmp((*p)->value->source_ver, src->version) != 0) {
		if (cmpversions((*p)->value->source_ver, GT, src->version)) {
		    printf("ALERT: old source: ");
		} else {
		    printf("WARN: out of date: ");
		}
		printf("%s %s: %s binary: %s %s from %s\n",
		       src->package, src->version, srcs->archname[i],
		       (*p)->value->package, (*p)->value->version,
		       (*p)->value->source_ver);
		delete_ownedpackagelist(p);
	    } else {
		p = &(*p)->next;
	    }
	}
	if (src->packages[i] == NULL) {
	    printf("%s missing uptodate binaries for %s\n",
		   src->package, srcs->archname[i]);
	    remove = 1;
	}
    }
    if (remove) {
	dpkg_source *src2;
	src2 = remove_sourcetbl(srcs->sources, src->package);
	assert(src == src2);
	free_source(src);
    }
}
#endif 

static void upgrade(sourcetbl *srctbl, dpkg_source *src, void *data) {
    static int i = 0;
    dpkg_sources_note *srcsn = data;
    (void)srctbl;
    i++; i %= 1000;
    if (can_undo(srcsn)) {
        if (i % 29 == 1 || i % 31 == 1 || i % 7 == 5)
            undo_change(srcsn);
        if (i % 33 == 0) commit_changes(srcsn);
    }
    upgrade_source(data, src);
}

static void checkpkgs(packagetbl *pkgtbl, dpkg_collected_package *cpkg, 
		      void *data) 
{
    dpkg_packages *pkgs = data;
    assert(pkgs->packages == pkgtbl);
    printf("Trying %s (%s, %s)\n", cpkg->pkg->package, cpkg->pkg->version, pkgs->arch);
    if (!checkinstallable2(pkgs, cpkg->pkg->package)) {
 	printf("Package: %s (%s, %s) is uninstallable\n",
	       cpkg->pkg->package, cpkg->pkg->version, pkgs->arch);
    }
}

void print_memblock_summary(void);

int main(int argc, char **argv) {
    dpkg_sources *src = NULL, *oldsrc = NULL;
    dpkg_sources_note *srcsn;
    dpkg_source *srcpkg;
    dpkg_packages *pkgs[10];
    int n_pkgs;
    int i,j;
    int reps;
    
    if (argc < 3) {
	printf("Usage: %s <reps> <arch>...\n", argv[0]);
	exit(EXIT_FAILURE);
    }

    reps = atoi(argv[1]);
    if (reps < 1) {
        printf("reps must be >= 1\n");
        exit(EXIT_FAILURE);
    }

    src = read_directory("cur", argc - 2, argv + 2);
    oldsrc = read_directory("old", argc - 2, argv + 2); 
    srcsn = new_sources_note(argc - 2, argv + 2);

    printf("FINISHED LOADING\n"); fflush(stdout); /* sleep(5); */

#if 0
    iterate_sourcetbl(oldsrc->sources, checkoldsrc, src);

    printf("FIRST\n");
    iterate_sourcetbl(src->sources, checkuptodate, src);
    printf("SECOND\n");
    iterate_sourcetbl(src->sources, checkuptodate, src);
    printf("END\n");

    iterate_sourcetbl(src->sources, checknewsrc, oldsrc);
#endif

    n_pkgs = 0;
    for (i = argc - 1; i > 1; i--) {
	pkgs[n_pkgs++] = get_architecture(oldsrc, argv[i]);
    }
    for (j = 0; j < reps; j++) {
	printf("Round %d/%d starting...\n", j + 1, reps);
        for (i = 0; i < n_pkgs; i++) {
            iterate_packagetbl(pkgs[i]->packages, checkpkgs, pkgs[i]);
        }
	printf("Round %d ended.\n", j+1);
    }
    iterate_sourcetbl(src->sources, upgrade, srcsn);
    iterate_sourcetbl(oldsrc->sources, upgrade, srcsn);

    for (i = 0; i < n_pkgs; i++) {
	free_packages(pkgs[i]);
    }

    srcpkg = lookup_sourcetbl(oldsrc->sources, "omirr");
    if (srcpkg != NULL) {
        printf("Adding old\n");
	upgrade_source(srcsn, srcpkg);
    }
    srcpkg = lookup_sourcetbl(src->sources, "omirr");
    if (srcpkg != NULL) {
        printf("Adding cur\n");
	upgrade_source(srcsn, srcpkg);
    }

    printf("FINISHED PROCESSING\n"); fflush(stdout); /* sleep(5); */

    write_directory("out", oldsrc);

    printf("FINISHED WRITING\n"); fflush(stdout); /* sleep(5); */

    free_sources_note(srcsn);
    free_sources(src);
    free_sources(oldsrc);

    DEBUG_ONLY( print_memblock_summary(); )

    return 0;
}
