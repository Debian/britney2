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

/**************************************************************************
 * Coping with a source package (and collections thereof) as an abstract 
 * entity, owning a bunch of binary packages 
 */


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


// Used by britney-py.c

void add_package(dpkg_packages *pkgs, dpkg_package *pkg);
void remove_package(dpkg_packages *pkgs, dpkg_collected_package *pkg);
dpkg_packages *new_packages(char *arch);
void free_packages(dpkg_packages *pkgs);

deplistlist *read_dep_andor(char *buf);
deplist *read_dep_and(char *buf);
ownedpackagenamelist *read_packagenames(char *buf);

int checkinstallable2(dpkg_packages *pkgs, char *pkgname);



#endif
