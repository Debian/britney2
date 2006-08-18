#ifndef DPKG_H
#define DPKG_H

#include "templates.h"
#include "memory.h"

#include <stdio.h>

/**************************************************************************
 * Coping with an rfc822-esque field 
 */

typedef struct dpkg_entry dpkg_entry;
struct dpkg_entry {
    char *name;
    char *value;
};

typedef struct dpkg_paragraph dpkg_paragraph;
struct dpkg_paragraph {
    int n_entries;
    int n_allocated;
    dpkg_entry *entry;
};

/**************************************************************************
 * Coping with a package (or many pkgs) as an abstract entity 
 */

typedef enum {dr_NOOP,dr_LT,dr_LTEQ,dr_EQ,dr_GTEQ,dr_GT} dependency_relation;
extern char *dependency_relation_sym[];

typedef struct dependency dependency;
struct dependency {
    char *package;
    dependency_relation op;
    char *version;
};

LIST(deplist, dependency*);
LIST(deplistlist, deplist*);

LIST(packagenamelist, char*);
LIST(ownedpackagenamelist, char*);

typedef struct dpkg_package dpkg_package;

struct dpkg_package {
    char *package;
    char *version;
    
    char *source;
    char *source_ver;
    
    int priority;

    int arch_all;
    
    deplistlist          *depends[4];
    deplist              *conflicts;    
    ownedpackagenamelist *provides;
	
    dpkg_paragraph *details;
};

LIST(packagelist, dpkg_package *);
LIST(ownedpackagelist, dpkg_package *);

typedef struct satisfieddep satisfieddep;

struct satisfieddep {
    /* dependency *dep; */
    deplist *depl;
    packagelist *pkgs;
};

LIST(satisfieddeplist, satisfieddep *);

/**************************************************************************
 * Coping with a source package (and collections thereof) as an abstract 
 * entity, owning a bunch of binary packages 
 */

typedef struct dpkg_source dpkg_source;
struct dpkg_source {
    char *package;
    char *version;

    int fake;

    struct dpkg_sources *owner;
    ownedpackagelist **packages; /* one for each architecture */

    dpkg_paragraph *details;
};

HASH(sourcetbl,char *,dpkg_source *);

typedef struct dpkg_sources dpkg_sources;
struct dpkg_sources {
    int n_arches;
    char **archname;
    sourcetbl *sources;
    ownedpackagelist **unclaimedpackages; /* one for each arch */
};

/**************************************************************************
 */

typedef struct dpkg_collected_package dpkg_collected_package;
struct dpkg_collected_package {
    dpkg_package *pkg;

    int installed, conflicted;

    enum { UNKNOWN, YES } installable;
    packagenamelist *mayaffect;

    /* on update, the installability_checked of each /mayaffect/ed package
     * is cleared, and the mayaffect list is cleared.
     * 
     * note that installable = NO couldn't be maintained over adding a package
     * to testing. installable = YES can be, thanks to the mayaffect list
     * (once a package is removed, everything it mayaffect must be set back
     * to unknown, but everything else is okay)
     */
};

LIST(collpackagelist, dpkg_collected_package *);

/**************************************************************************
 */

typedef struct dpkg_provision dpkg_provision;
struct dpkg_provision {
    char *version;
    dpkg_collected_package *pkg;
};

LIST(virtualpkg, dpkg_provision);

HASH(virtualpkgtbl,char *,virtualpkg *);
HASH(packagetbl,char *,dpkg_collected_package *);

typedef struct dpkg_packages dpkg_packages;
struct dpkg_packages {
    char *arch;
    packagetbl *packages;
    virtualpkgtbl *virtualpkgs;
};

typedef struct dpkg_source_note dpkg_source_note;
struct dpkg_source_note {
    dpkg_source *source;   /* unowned */
    int n_arches;
    packagelist **binaries; /* one for each arch */
};
HASH(sourcenotetbl, char *, dpkg_source_note *);

LIST(source_note_list, dpkg_source_note *);
	/* contains a copy of the previous source_note */
LIST(source_note_listlist, source_note_list *);
	/* contains a copy of all the source_notes modified by the last op */

typedef struct dpkg_sources_note dpkg_sources_note;
struct dpkg_sources_note {
    unsigned long magic;
    sourcenotetbl *sources;
    int n_arches;
    dpkg_packages **pkgs;
    char **archname;

    source_note_listlist *undo;
};

void free_packages(dpkg_packages *pkgs);
void free_sources(dpkg_sources *s);

dpkg_packages *get_architecture(dpkg_sources *srcs, char *arch);

/* parsing things */
int checkinstallable(dpkg_packages *pkgs, collpackagelist *instoneof);
int checkinstallable2(dpkg_packages *pkgs, char *pkgname);
satisfieddeplist *checkunsatisfiabledeps(dpkg_packages *pkgs, 
					    deplistlist *deps);

dpkg_sources *read_directory(char *dir, int n_arches, char *archname[]);
void write_directory(char *dir, dpkg_sources *srcs);

void free_source(dpkg_source *s);

/* adding and deleting and stuff */
dpkg_sources_note *new_sources_note(int n_arches, char **archname);
void remove_source(dpkg_sources_note *srcsn, char *name);
void upgrade_source(dpkg_sources_note *srcsn, dpkg_source *src);
void upgrade_arch(dpkg_sources_note *srcsn, dpkg_source *src, char *arch);
void write_notes(char *dir, dpkg_sources_note *srcsn);
void free_sources_note(dpkg_sources_note *srcsn);
void free_source_note(dpkg_source_note *srcn);
void undo_change(dpkg_sources_note *srcsn);
int can_undo(dpkg_sources_note *srcsn);
void commit_changes(dpkg_sources_note *srcsn);

int versioncmp(char *left, char *right);
int cmpversions(char *left, int op, char *right);

#endif
