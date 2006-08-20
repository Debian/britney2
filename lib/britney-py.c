#include <python2.3/Python.h>

#include "dpkg.h"

#define MAKE_PY_LIST(L,S,E,I,V)                 \
	do {                                    \
		L = PyList_New(0);              \
		if (!L) break;                  \
		for (S; E; I) {                 \
			PyObject *EL;           \
			EL = Py_BuildValue V;   \
			if (!EL) {              \
				Py_DECREF(L);   \
				L = NULL;       \
				break;          \
			}                       \
			PyList_Append(L, EL);   \
			Py_DECREF(EL);          \
		}                               \
		if (L) PyList_Sort(L);          \
	} while(0)

/**************************************************************************
 * britney.Packages -- dpkg_packages wrapper
 *******************************************/

typedef enum { DONTFREE, FREE } dpkgpackages_freeme;
typedef struct {
	PyObject_HEAD
	dpkg_packages		*pkgs;
	PyObject 		*ref; /* object packages are "in" */
	dpkgpackages_freeme	freeme; /* free pkgs when deallocing? */
} dpkgpackages;

staticforward PyTypeObject Packages_Type;

static PyObject *dpkgpackages_new(dpkg_packages *pkgs, 
                                  dpkgpackages_freeme freeme, PyObject *ref) 
{
	dpkgpackages *res;

	res = PyObject_NEW(dpkgpackages, &Packages_Type);
	if (res == NULL) return NULL;

	res->pkgs = pkgs;
	res->ref = ref;	Py_INCREF(res->ref);
	res->freeme = freeme;

	return (PyObject *) res;
}

static void dpkgpackages_dealloc(dpkgpackages *self) {
	if (self->freeme == FREE) free_packages(self->pkgs);
	Py_XDECREF(self->ref);
	self->pkgs = NULL;
	self->ref = NULL;
	PyMem_DEL(self);
}


static dpkg_collected_package *dpkgpackages_lookuppkg(dpkgpackages *self,
                                                      char *pkgname)
{
	dpkg_collected_package *cpkg = NULL;
	cpkg = lookup_packagetbl(self->pkgs->packages, pkgname);
	if (!cpkg) {
		PyErr_SetString(PyExc_ValueError, "Not a valid package");
	}
	return cpkg;
}

static PyObject *dpkgpackages_ispresent(dpkgpackages *self, PyObject *args) {
	dpkg_collected_package *cpkg;
	char *pkgname;
	if (!PyArg_ParseTuple(args, "s", &pkgname)) return NULL;
	cpkg = lookup_packagetbl(self->pkgs->packages, pkgname);
	return cpkg ? Py_BuildValue("i", 1) : Py_BuildValue("i", 0);
}

static PyObject *dpkgpackages_getversion(dpkgpackages *self, PyObject *args) {
	dpkg_collected_package *cpkg;
	char *pkgname;
	if (!PyArg_ParseTuple(args, "s", &pkgname)) return NULL;
	cpkg = lookup_packagetbl(self->pkgs->packages, pkgname);
	if (cpkg) return Py_BuildValue("s", cpkg->pkg->version);
	else return Py_BuildValue("");
}
static PyObject *dpkgpackages_getsource(dpkgpackages *self, PyObject *args) {
	dpkg_collected_package *cpkg;
	char *pkgname;
	if (!PyArg_ParseTuple(args, "s", &pkgname)) return NULL;
	cpkg = lookup_packagetbl(self->pkgs->packages, pkgname);
	if (cpkg) return Py_BuildValue("s", cpkg->pkg->source);
	else return Py_BuildValue("");
}
static PyObject *dpkgpackages_getsourcever(dpkgpackages *self, PyObject *args) {
	dpkg_collected_package *cpkg;
	char *pkgname;
	if (!PyArg_ParseTuple(args, "s", &pkgname)) return NULL;
	cpkg = lookup_packagetbl(self->pkgs->packages, pkgname);
	if (cpkg) return Py_BuildValue("s", cpkg->pkg->source_ver);
	else return Py_BuildValue("");
}
static PyObject *dpkgpackages_isarchall(dpkgpackages *self, PyObject *args) {
	dpkg_collected_package *cpkg;
	char *pkgname;
	if (!PyArg_ParseTuple(args, "s", &pkgname)) return NULL;
	cpkg = lookup_packagetbl(self->pkgs->packages, pkgname);
	if (cpkg) return Py_BuildValue("i", cpkg->pkg->arch_all);
	else return Py_BuildValue("");
}
static PyObject *dpkgpackages_isntarchall(dpkgpackages *self, PyObject *args) {
	dpkg_collected_package *cpkg;
	char *pkgname;
	if (!PyArg_ParseTuple(args, "s", &pkgname)) return NULL;
	cpkg = lookup_packagetbl(self->pkgs->packages, pkgname);
	if (cpkg) return Py_BuildValue("i", !cpkg->pkg->arch_all);
	else return Py_BuildValue("");
}
static PyObject *dpkgpackages_getfield(dpkgpackages *self, PyObject *args) {
	char *field;
	char *pkgname;
	int i;
	dpkg_collected_package *cpkg;
	dpkg_paragraph *para;
	if (!PyArg_ParseTuple(args, "ss", &pkgname, &field)) return NULL;
	cpkg = dpkgpackages_lookuppkg(self, pkgname);
	if (!cpkg) return NULL;
	para = cpkg->pkg->details;
	for (i = 0; i < para->n_entries; i++) {
		if (strcasecmp(para->entry[i].name, field) == 0) {
			return Py_BuildValue("s", para->entry[i].value);
		}
	}
	return Py_BuildValue("");
}
static PyObject *dpkgpackages_isinstallable(dpkgpackages *self, PyObject *args)
{
	char *pkgname;
	if (!PyArg_ParseTuple(args, "s", &pkgname)) return NULL;
	if (checkinstallable2(self->pkgs, pkgname)) {
		return Py_BuildValue("i", 1);
	} else {
		return Py_BuildValue("");
	}
}
static PyObject *dpkgpackages_isuninstallable(dpkgpackages *self, 
                                              PyObject *args)
{
	char *pkgname;
	if (!PyArg_ParseTuple(args, "s", &pkgname)) return NULL;
	if (!checkinstallable2(self->pkgs, pkgname)) {
		return Py_BuildValue("i", 1);
	} else {
		return Py_BuildValue("");
	}
}
static PyObject *dpkgpackages_unsatdeps(dpkgpackages *self, PyObject *args) {
	/* arguments are:
	 * 	testingpkgs[arch].unsatisfiable_deps(unstablepkgs[arch], "netbase", "Depends")
	 * exciting, huh?
	 */

	dpkgpackages *pkgpkgs;
	char *pkgname, *fieldname;
	dpkg_collected_package *cpkg;
	int fieldidx;
	int buflen = 100;
	char *buf = malloc(buflen);
	const char *fields[] = { "Pre-Depends", "Depends", "Recommends", 
				"Suggests", NULL };
	satisfieddeplist *unsatdeps, *dl;
	PyObject *res = Py_BuildValue("[]");

	if (!PyArg_ParseTuple(args, "O!ss", &Packages_Type, &pkgpkgs, &pkgname, &fieldname)) return NULL;

	cpkg = lookup_packagetbl(pkgpkgs->pkgs->packages, pkgname);
	if (!cpkg) {
		PyErr_SetString(PyExc_ValueError, "Not a valid package");
		return NULL;
	}

	for (fieldidx = 0; fields[fieldidx]; fieldidx++) {
		if (strcmp(fields[fieldidx], fieldname) == 0) break;
	}
	if (!fields[fieldidx]) {
		PyErr_SetString(PyExc_ValueError, "Not a valid dependency field");
		return NULL;
	}

	unsatdeps = checkunsatisfiabledeps(self->pkgs, 
	                                   cpkg->pkg->depends[fieldidx]);
	for (dl = unsatdeps; dl != NULL; dl = dl->next) {
		int len;
		packagelist *it;
		PyObject *pkglist;
		deplist *depl;
		dependency *dep;

		len = 0;
		buf[0] = '\0';
		for (depl = dl->value->depl; depl; depl = depl->next) {
			dep = depl->value;
			len += strlen(dep->package) + 4;
			/* 4 = strlen(" | ") + 1 */
			if (dep->op != dr_NOOP) {
				len += strlen(dep->version) + 6;
				/* 6 = strlen(" (>= )") */
			}
			if (len >= buflen) {
				char *newbuf;
				newbuf = realloc(buf, len + 100);
				if (newbuf == NULL) {
					free_satisfieddeplist(unsatdeps);
					free(buf);
					Py_DECREF(res);
					PyErr_SetFromErrno(PyExc_MemoryError);
					return NULL;
				}
				buf = newbuf;
				buflen = len + 100;
			}
			if (buf[0] != '\0') strcat(buf, " | ");
			strcat(buf, dep->package);
			if (dep->op != dr_NOOP) {
				sprintf(buf + strlen(buf), " (%s %s)",
					dependency_relation_sym[dep->op],
					dep->version);
			}
		}

		MAKE_PY_LIST(pkglist, it = dl->value->pkgs, it, it = it->next, 
				("s", it->value->package)
			    );

		{
			PyObject *depel = Py_BuildValue("(sN)", buf, pkglist);
			PyList_Append(res, depel);
			Py_DECREF(depel);
		}
	}

	free_satisfieddeplist(unsatdeps);
	free(buf);

	return res;
}


static PyObject *dpkgpackages_remove_binary(dpkgpackages *self, PyObject *args) {
    char *pkg_name;

	(void)self; /* unused */

    if (!PyArg_ParseTuple(args, "s", &pkg_name))
        return NULL;

    dpkg_collected_package *cpkg = lookup_packagetbl(self->pkgs->packages, pkg_name);
    if (cpkg == NULL) return Py_BuildValue("i", 0);

    remove_package(self->pkgs, cpkg);
    return Py_BuildValue("i", 1);
}

static PyObject *dpkgpackages_add_binary(dpkgpackages *self, PyObject *args) {
    char *pkg_name;
	PyObject *value, *pyString;

	(void)self; /* unused */

    if (!PyArg_ParseTuple(args, "sO", &pkg_name, &value) ||
        !PyList_Check(value)) return NULL;

    /* initialize the new package */
    dpkg_package *pkg;
    pkg = block_malloc(sizeof(dpkg_package));
    pkg->package = strdup(pkg_name);
    pkg->priority = 0;
    pkg->details    = NULL;
    pkg->depends[2] = NULL;
    pkg->depends[3] = NULL;

    pyString = PyList_GetItem(value, 0);
    if (pyString == NULL) return NULL;
    pkg->version = PyString_AsString(pyString);

    pyString = PyList_GetItem(value, 2);
    if (pyString == NULL) return NULL;
    pkg->source = PyString_AsString(pyString);

    pyString = PyList_GetItem(value, 3);
    if (pyString == NULL) return NULL;
    pkg->source_ver = PyString_AsString(pyString);

    pyString = PyList_GetItem(value, 4);
    if (pyString == NULL) return NULL;
    pkg->arch_all = (!strcmp(PyString_AsString(pyString), "all") ? 1 : 0);

    pyString = PyList_GetItem(value, 5);
    if (pyString == NULL) return NULL;
    if (pyString != Py_None) {
        pkg->depends[0] = read_dep_andor(PyString_AsString(pyString));
    } else pkg->depends[0] = NULL;

    pyString = PyList_GetItem(value, 6);
    if (pyString == NULL) return NULL;
    if (pyString != Py_None) {
        pkg->depends[1] = read_dep_andor(PyString_AsString(pyString));
    } else pkg->depends[1] = NULL;

    pyString = PyList_GetItem(value, 7);
    if (pyString == NULL) return NULL;
    if (pyString != Py_None) {
        pkg->conflicts = read_dep_and(PyString_AsString(pyString));
    } else pkg->conflicts = NULL;

    pyString = PyList_GetItem(value, 8);
    if (pyString == NULL) return NULL;
    if (pyString != Py_None) {
        pkg->provides = read_packagenames(PyString_AsString(pyString));
    } else pkg->provides = NULL;

    add_package(self->pkgs, pkg);

    return Py_BuildValue("i", 1);
}

static PyObject *dpkgpackages_getattr(dpkgpackages *self, char *name) {
	static struct PyMethodDef dpkgsources_methods[] = {
		{ "is_present", (binaryfunc) dpkgpackages_ispresent, 
			METH_VARARGS, NULL },
		{ "get_version", (binaryfunc) dpkgpackages_getversion, 
			METH_VARARGS, NULL },
		{ "get_source", (binaryfunc) dpkgpackages_getsource, 
			METH_VARARGS, NULL },
		{ "get_sourcever", (binaryfunc) dpkgpackages_getsourcever, 
			METH_VARARGS, NULL },
		{ "is_arch_all", (binaryfunc) dpkgpackages_isarchall, 
			METH_VARARGS, NULL },
		{ "isnt_arch_all", (binaryfunc) dpkgpackages_isntarchall, 
			METH_VARARGS, NULL },
		{ "get_field", (binaryfunc) dpkgpackages_getfield, 
			METH_VARARGS, NULL },
		{ "is_installable", (binaryfunc) dpkgpackages_isinstallable, 
			METH_VARARGS, NULL },
		{ "is_uninstallable", (binaryfunc)dpkgpackages_isuninstallable, 
			METH_VARARGS, NULL },
		{ "unsatisfiable_deps", (binaryfunc) dpkgpackages_unsatdeps, 
			METH_VARARGS, NULL },

	    { "remove_binary", (binaryfunc) dpkgpackages_remove_binary,
            METH_VARARGS, NULL },
	    { "add_binary", (binaryfunc) dpkgpackages_add_binary,
            METH_VARARGS, NULL },

		{ NULL, NULL, 0, NULL }
	};

	if (strcmp(name, "packages") == 0) {
		PyObject *packages;
		packagetbl_iter it;
		MAKE_PY_LIST(packages, 
		             it = first_packagetbl(self->pkgs->packages),
		             !done_packagetbl(it), it = next_packagetbl(it),
			     ("s", it.k)
			    );
		return packages;
	}

	return Py_FindMethod(dpkgsources_methods, (PyObject *)self, name);
}

static PyTypeObject Packages_Type = {
	PyObject_HEAD_INIT(&PyType_Type)

	0,                     /* ob_size (0) */
	"Packages",            /* type name */
	sizeof(dpkgpackages),  /* basicsize */
	0,                     /* itemsize (0) */

	(destructor)  dpkgpackages_dealloc,
	(printfunc)   0,
	(getattrfunc) dpkgpackages_getattr,
	(setattrfunc) 0,
	(cmpfunc)     0,
	(reprfunc)    0,

	0,                     /* number methods */
	0,                     /* sequence methods */
	0,                     /* mapping methods */

	(hashfunc)    0,       /* dict[x] ?? */
	(ternaryfunc) 0,       /* x() */
	(reprfunc)    0        /* str(x) */
};

/**************************************************************************
 * britney.Sources -- dpkg_sources wrapper
 *****************************************/

typedef struct {
	PyObject_HEAD
	dpkg_sources	*srcs;
} dpkgsources;

staticforward PyTypeObject Sources_Type;

static PyObject *dpkgsources_new(PyObject *self, PyObject *args) {
	dpkgsources *res = NULL;
	char *dir;
	PyObject *arches;
	char **archesStr = NULL;
	int i, count;

	(void)self; /* unused */

	if (!PyArg_ParseTuple(args, "sO!", &dir, &PyList_Type, &arches)) {
		goto end;
	}

	count = PyList_Size(arches);
	if (count <= 0) {
		PyErr_SetString(PyExc_TypeError, "No architectures specified");
		goto end;
	}

	archesStr = malloc(sizeof(char *) * count);
	if (!archesStr) {
		PyErr_SetFromErrno(PyExc_MemoryError);
		goto end;
	}

	for (i = 0; i < count; i++) {
		PyObject *arch = PyList_GetItem(arches, i);
		if (!PyString_Check(arch)) {
			goto end;
		}
		archesStr[i] = PyString_AsString(arch);
	}

	res = PyObject_NEW(dpkgsources, &Sources_Type);
	if (res == NULL) goto end;

	res->srcs = read_directory(dir, count, archesStr);
	if (!res->srcs) {
		Py_DECREF(res);
		res = NULL;
		goto end;
	}

end:
	if (archesStr) free(archesStr);
	return (PyObject *) res;
}

static void dpkgsources_dealloc(dpkgsources *self) {
	free_sources(self->srcs);
	self->srcs = NULL;
	PyMem_DEL(self);
}

static PyObject *dpkgsources_packages(dpkgsources *self, PyObject *args)
{
	char *arch;
	dpkg_packages *pkgs;
	if (!PyArg_ParseTuple(args, "s", &arch)) return NULL;
	pkgs = get_architecture(self->srcs, arch);
	return dpkgpackages_new(pkgs, FREE, (PyObject *) self);
}

static PyObject *dpkgsources_isfake(dpkgsources *self, PyObject *args) {
	char *srcname;
	dpkg_source *src;

	if (!PyArg_ParseTuple(args, "s", &srcname)) return NULL;
	src = lookup_sourcetbl(self->srcs->sources, srcname);
	if (src) return Py_BuildValue("i", src->fake);
	else return Py_BuildValue("");
}

static PyObject *dpkgsources_getversion(dpkgsources *self, PyObject *args) {
	char *srcname;
	dpkg_source *src;

	if (!PyArg_ParseTuple(args, "s", &srcname)) return NULL;
	src = lookup_sourcetbl(self->srcs->sources, srcname);
	if (src) return Py_BuildValue("s", src->version);
	else return Py_BuildValue("");
}

static PyObject *dpkgsources_getfield(dpkgsources *self, PyObject *args) {
	char *srcname, *field;
	dpkg_source *src;
	int i;
	dpkg_paragraph *para;

	if (!PyArg_ParseTuple(args, "ss", &srcname, &field)) return NULL;
	src = lookup_sourcetbl(self->srcs->sources, srcname);
	if (!src) {
		PyErr_SetString(PyExc_ValueError, "Not a valid source package");
		return NULL;
	}
	para = src->details;
	if (para) {
		for (i = 0; i < para->n_entries; i++) {
			if (strcasecmp(para->entry[i].name, field) == 0) {
				return Py_BuildValue("s", para->entry[i].value);
			}
		}
	}
	return Py_BuildValue("");
}

static PyObject *dpkgsources_ispresent(dpkgsources *self, PyObject *args) {
	char *srcname;
	if (!PyArg_ParseTuple(args, "s", &srcname)) return NULL;
	if (lookup_sourcetbl(self->srcs->sources, srcname)) {
		return Py_BuildValue("i", 1);
	} else {
		return Py_BuildValue("i", 0);
	}
}

static PyObject *dpkgsources_binaries(dpkgsources *self, PyObject *args) {
	char *srcname, *arch;
	int archnum;
	dpkg_source *src;
	PyObject *res;
	ownedpackagelist *p;

	if (!PyArg_ParseTuple(args, "ss", &srcname, &arch)) return NULL;

	for (archnum = 0; archnum < self->srcs->n_arches; archnum++) {
		if (strcmp(arch, self->srcs->archname[archnum]) == 0) break;
	}
	if (archnum == self->srcs->n_arches) {
		PyErr_SetString(PyExc_ValueError, "Not a valid architecture");
		return NULL;
	}

	src = lookup_sourcetbl(self->srcs->sources, srcname);
	if (src == NULL) {
		PyErr_SetString(PyExc_ValueError, "Not a valid source package");
		return NULL;
	}

	MAKE_PY_LIST(res, p = src->packages[archnum], p, p = p->next,
		     ("s", p->value->package)
		    );
	return res;
}

static PyObject *dpkgsources_getattr(dpkgsources *self, char *name) {
	static struct PyMethodDef dpkgsources_methods[] = {
		{ "Packages", (binaryfunc) dpkgsources_packages, 
			METH_VARARGS, NULL },
		{ "is_fake", (binaryfunc) dpkgsources_isfake, 
			METH_VARARGS, NULL },
		{ "get_version", (binaryfunc) dpkgsources_getversion, 
			METH_VARARGS, NULL },
		{ "get_field", (binaryfunc) dpkgsources_getfield, 
			METH_VARARGS, NULL },
		{ "is_present", (binaryfunc) dpkgsources_ispresent, 
			METH_VARARGS, NULL },
		{ "binaries", (binaryfunc) dpkgsources_binaries, 
			METH_VARARGS, NULL },
		{ NULL, NULL, 0, NULL }
	};

	if (strcmp(name, "arches") == 0) {
		PyObject *arches;
		int i;
		MAKE_PY_LIST(arches, i = 0, i < self->srcs->n_arches, i++, 
			     ("s", self->srcs->archname[i])
			    );
		return arches;
	} else if (strcmp(name, "sources") == 0) {
		PyObject *sources;
		sourcetbl_iter it;
		MAKE_PY_LIST(sources, 
		             it = first_sourcetbl(self->srcs->sources),
		             !done_sourcetbl(it), it = next_sourcetbl(it),
			     ("s", it.k)
			    );
		return sources;
	}

	return Py_FindMethod(dpkgsources_methods, (PyObject *)self, name);
}

static PyTypeObject Sources_Type = {
	PyObject_HEAD_INIT(&PyType_Type)

	0,                     /* ob_size (0) */
	"Sources",             /* type name */
	sizeof(dpkgsources),   /* basicsize */
	0,                     /* itemsize (0) */

	(destructor)  dpkgsources_dealloc,
	(printfunc)   0,
	(getattrfunc) dpkgsources_getattr,
	(setattrfunc) 0,
	(cmpfunc)     0,
	(reprfunc)    0,

	0,                     /* number methods */
	0,                     /* sequence methods */
	0,                     /* mapping methods */

	(hashfunc)    0,       /* dict[x] ?? */
	(ternaryfunc) 0,       /* x() */
	(reprfunc)    0        /* str(x) */
};

/**************************************************************************
 * britney.SourcesNote -- dpkg_sourcesnote wrapper
 *************************************************/

typedef struct {
	PyObject_HEAD
	dpkg_sources_note	*srcsn;
	PyObject 		*refs; /* list of referenced dpkgsources */
} dpkgsrcsn;

staticforward PyTypeObject SourcesNote_Type;

static PyObject *dpkgsrcsn_new(PyObject *self, PyObject *args) {
	dpkgsrcsn *res = NULL;
	PyObject *arches;
	char **archesStr = NULL;
	int i, count;

	(void)self; /* unused */

	if (!PyArg_ParseTuple(args, "O!", &PyList_Type, &arches)) {
		goto end;
	}

	count = PyList_Size(arches);
	if (count <= 0) {
		PyErr_SetString(PyExc_TypeError, "No architectures specified");
		goto end;
	}

	archesStr = malloc(sizeof(char *) * count);
	if (!archesStr) {
		PyErr_SetFromErrno(PyExc_MemoryError);
		goto end;
	}

	for (i = 0; i < count; i++) {
		PyObject *arch = PyList_GetItem(arches, i);
		if (!PyString_Check(arch)) {
			goto end;
		}
		archesStr[i] = PyString_AsString(arch);
	}

	res = PyObject_NEW(dpkgsrcsn, &SourcesNote_Type);
	if (res == NULL) goto end;

	res->refs = PyList_New(0);
	res->srcsn = new_sources_note(count, archesStr);
	if (!res->refs || !res->srcsn) {
		Py_DECREF(res);
		res = NULL;
		goto end;
	}

end:
	if (archesStr) free(archesStr);
	return (PyObject *) res;
}

static void dpkgsrcsn_dealloc(dpkgsrcsn *self) {
	if (self->srcsn) free_sources_note(self->srcsn);
	self->srcsn = NULL;
	Py_XDECREF(self->refs);
	self->refs = NULL;

	PyMem_DEL(self);
}

static PyObject *dpkgsrcsn_removesource(dpkgsrcsn *self, PyObject *args) {
	char *name;
	if (!PyArg_ParseTuple(args, "s", &name)) return NULL;
	remove_source(self->srcsn, name);
	return Py_BuildValue("");
}
static PyObject *dpkgsrcsn_upgradesource(dpkgsrcsn *self, PyObject *args) {
	char *name;
	dpkgsources *srcs;
	dpkg_source *src;
	if (!PyArg_ParseTuple(args, "O!s", &Sources_Type, &srcs, &name)) 
		return NULL;
	src = lookup_sourcetbl(srcs->srcs->sources, name);
	if (!src) {
		PyErr_SetString(PyExc_ValueError, "Source does not exist");
		return NULL;
	}
	if (!PySequence_In(self->refs, (PyObject *)srcs))
		PyList_Append(self->refs, (PyObject *)srcs);
	upgrade_source(self->srcsn, src);
	return Py_BuildValue("");
}
static PyObject *dpkgsrcsn_upgradearch(dpkgsrcsn *self, PyObject *args) {
	char *name, *arch;
	dpkgsources *srcs;
	dpkg_source *src;
	if (!PyArg_ParseTuple(args, "O!ss", &Sources_Type, &srcs, &name, &arch))
		return NULL;
	src = lookup_sourcetbl(srcs->srcs->sources, name);
	if (!src) {
		PyErr_SetString(PyExc_ValueError, "Source does not exist");
		return NULL;
	}
	if (!PySequence_In(self->refs, (PyObject *)srcs))
		PyList_Append(self->refs, (PyObject *)srcs);
	upgrade_arch(self->srcsn, src, arch);
	return Py_BuildValue("");
}

static PyObject *dpkgsrcsn_undochange(dpkgsrcsn *self, PyObject *args) {
	if (!PyArg_ParseTuple(args, "")) return NULL;
	undo_change(self->srcsn);
	return Py_BuildValue("");
}

static PyObject *dpkgsrcsn_commitchanges(dpkgsrcsn *self, PyObject *args) {
	if (!PyArg_ParseTuple(args, "")) return NULL;
	commit_changes(self->srcsn);
	return Py_BuildValue("");
}

static PyObject *dpkgsrcsn_writenotes(dpkgsrcsn *self, PyObject *args) {
	char *dir;
	if (!PyArg_ParseTuple(args, "s", &dir)) return NULL;
	write_notes(dir, self->srcsn);
	return Py_BuildValue("");
}

static PyObject *dpkgsrcsn_packages(dpkgsrcsn *self, PyObject *args) {
	char *arch;
	int archnum;
	if (!PyArg_ParseTuple(args, "s", &arch)) return NULL;
	for (archnum = 0; archnum < self->srcsn->n_arches; archnum++) {
		if (strcmp(arch, self->srcsn->archname[archnum]) == 0) break;
	}
	if (archnum == self->srcsn->n_arches) {
		PyErr_SetString(PyExc_ValueError, "Not a valid architecture");
		return NULL;
	}
	return dpkgpackages_new(self->srcsn->pkgs[archnum], DONTFREE,
	                        (PyObject *) self);
}

static PyObject *dpkgsrcsn_getversion(dpkgsrcsn *self, PyObject *args) {
	char *srcname;
	dpkg_source_note *srcn;

	if (!PyArg_ParseTuple(args, "s", &srcname)) return NULL;
	srcn = lookup_sourcenotetbl(self->srcsn->sources, srcname);
	if (srcn) return Py_BuildValue("s", srcn->source->version);
	else return Py_BuildValue("");
}
static PyObject *dpkgsrcsn_getfield(dpkgsrcsn *self, PyObject *args) {
	char *srcname, *field;
	dpkg_source_note *srcn;
	int i;
	dpkg_paragraph *para;

	if (!PyArg_ParseTuple(args, "ss", &srcname, &field)) return NULL;
	srcn = lookup_sourcenotetbl(self->srcsn->sources, srcname);
	if (!srcn) {
		PyErr_SetString(PyExc_ValueError, "Not a valid source package");
		return NULL;
	}
	para = srcn->source->details;
	if (para) {
		for (i = 0; i < para->n_entries; i++) {
			if (strcasecmp(para->entry[i].name, field) == 0) {
				return Py_BuildValue("s", para->entry[i].value);
			}
		}
	}
	return Py_BuildValue("");
}
static PyObject *dpkgsrcsn_ispresent(dpkgsrcsn *self, PyObject *args) {
	char *srcname;
	if (!PyArg_ParseTuple(args, "s", &srcname)) return NULL;
	if (lookup_sourcenotetbl(self->srcsn->sources, srcname)) {
		return Py_BuildValue("i", 1);
	} else {
		return Py_BuildValue("i", 0);
	}
}

static PyObject *dpkgsrcsn_isfake(dpkgsrcsn *self, PyObject *args) {
	char *srcname;
	dpkg_source_note *srcn;

	if (!PyArg_ParseTuple(args, "s", &srcname)) return NULL;
	srcn = lookup_sourcenotetbl(self->srcsn->sources, srcname);
	if (srcn) return Py_BuildValue("i", srcn->source->fake);
	else return Py_BuildValue("");
}

static PyObject *dpkgsrcsn_binaries(dpkgsrcsn *self, PyObject *args) {
	char *srcname, *arch;
	int archnum;
	dpkg_source_note *srcn;
	PyObject *res;
	packagelist *p;

	if (!PyArg_ParseTuple(args, "ss", &srcname, &arch)) return NULL;

	for (archnum = 0; archnum < self->srcsn->n_arches; archnum++) {
		if (strcmp(arch, self->srcsn->archname[archnum]) == 0) break;
	}
	if (archnum == self->srcsn->n_arches) {
		PyErr_SetString(PyExc_ValueError, "Not a valid architecture");
		return NULL;
	}

	srcn = lookup_sourcenotetbl(self->srcsn->sources, srcname);
	if (srcn == NULL) {
		PyErr_SetString(PyExc_ValueError, "Not a valid source package");
		return NULL;
	}

	MAKE_PY_LIST(res, p = srcn->binaries[archnum], p, p = p->next,
		     ("s", p->value->package)
		    );
	return res;
}

static PyObject *dpkgsrcsn_getattr(dpkgsrcsn *self, char *name) {
	static struct PyMethodDef dpkgsrcsn_methods[] = {
		{ "remove_source", (binaryfunc) dpkgsrcsn_removesource, 
			METH_VARARGS, NULL },
		{ "upgrade_source", (binaryfunc) dpkgsrcsn_upgradesource, 
			METH_VARARGS, NULL },
		{ "upgrade_arch", (binaryfunc) dpkgsrcsn_upgradearch, 
			METH_VARARGS, NULL },

		{ "undo_change", (binaryfunc) dpkgsrcsn_undochange, 
			METH_VARARGS, NULL },
		{ "commit_changes", (binaryfunc) dpkgsrcsn_commitchanges, 
			METH_VARARGS, NULL },

		{ "write_notes", (binaryfunc) dpkgsrcsn_writenotes, 
			METH_VARARGS, NULL },

		{ "Packages", (binaryfunc) dpkgsrcsn_packages, 
			METH_VARARGS, NULL },

		{ "get_version", (binaryfunc) dpkgsrcsn_getversion, 
			METH_VARARGS, NULL },
		{ "get_field", (binaryfunc) dpkgsrcsn_getfield, 
			METH_VARARGS, NULL },
		{ "is_present", (binaryfunc) dpkgsrcsn_ispresent, 
			METH_VARARGS, NULL },
		{ "is_fake", (binaryfunc) dpkgsrcsn_isfake, 
			METH_VARARGS, NULL },
		{ "binaries", (binaryfunc) dpkgsrcsn_binaries, 
			METH_VARARGS, NULL },
		{ NULL, NULL, 0, NULL }
	};

	if (strcmp(name, "arches") == 0) {
		PyObject *arches;
		int i;
		MAKE_PY_LIST(arches, i = 0, i < self->srcsn->n_arches, i++, 
			     ("s", self->srcsn->archname[i])
			    );
		return arches;
	} else if (strcmp(name, "sources") == 0) {
		PyObject *sources;
		sourcenotetbl_iter it;
		MAKE_PY_LIST(sources, 
		             it = first_sourcenotetbl(self->srcsn->sources),
		             !done_sourcenotetbl(it),
			     it = next_sourcenotetbl(it),
			     ("s", it.k)
			    );
		return sources;
	} else if (strcmp(name, "can_undo") == 0) {
		if (can_undo(self->srcsn)) {
			return Py_BuildValue("i", 1);
		} else {
			return Py_BuildValue("");
		}
	}

	return Py_FindMethod(dpkgsrcsn_methods, (PyObject *)self, name);
}

static PyTypeObject SourcesNote_Type = {
	PyObject_HEAD_INIT(&PyType_Type)

	0,                     /* ob_size (0) */
	"SourcesNote",         /* type name */
	sizeof(dpkgsrcsn), /* basicsize */
	0,                     /* itemsize (0) */

	(destructor)  dpkgsrcsn_dealloc,
	(printfunc)   0,
	(getattrfunc) dpkgsrcsn_getattr,
	(setattrfunc) 0,
	(cmpfunc)     0,
	(reprfunc)    0,

	0,                     /* number methods */
	0,                     /* sequence methods */
	0,                     /* mapping methods */

	(hashfunc)    0,       /* dict[x] ?? */
	(ternaryfunc) 0,       /* x() */
	(reprfunc)    0        /* str(x) */
};

/**************************************************************************
 * britney.versioncmp() -- apt version compare function
 ******************************************************/

static PyObject *apt_versioncmp(PyObject *self, PyObject *args) {
	char *l, *r;
	int res;

	(void)self; /* unused */

	if (!PyArg_ParseTuple(args, "ss", &l, &r)) {
		return NULL;
	}

	res = versioncmp(l,r);
	return Py_BuildValue("i", res);
}

/**************************************************************************
 * britney.buildSystem() -- build a fake package system, with the only purpose of
 *                          calling the is_installable method on the packages.
 ******************************************************/

static PyObject *build_system(PyObject *self, PyObject *args) {
    int pos = 0;
    char *arch;
	PyObject *pkgs, *key, *value, *pyString;

	(void)self; /* unused */

    if (!PyArg_ParseTuple(args, "sO", &arch, &pkgs) ||
        !PyDict_Check(pkgs)) return NULL;

    /* Fields and positions for the binary package:
       # VERSION = 0
       # SECTION = 1
       # SOURCE = 2
       # SOURCEVER = 3
       # ARCHITECTURE = 4
       # PREDEPENDS = 5
       # DEPENDS = 6
       # CONFLICTS = 7
       # PROVIDES = 8
       # RDEPENDS = 9
       # RCONFLICTS = 10
    */

    dpkg_packages *dpkg_pkgs = new_packages(arch);

    /* loop on the dictionary keys to build the packages */
    while (PyDict_Next(pkgs, &pos, &key, &value)) {

        /* initialize the new package */
        dpkg_package *pkg;
        pkg = block_malloc(sizeof(dpkg_package));
        pkg->package = strdup(PyString_AsString(key));
        pkg->priority = 0;
        pkg->details    = NULL;
        pkg->depends[2] = NULL;
        pkg->depends[3] = NULL;

        pyString = PyList_GetItem(value, 0);
        if (pyString == NULL) continue;
        pkg->version = PyString_AsString(pyString);

        pyString = PyList_GetItem(value, 2);
        if (pyString == NULL) continue;
        pkg->source = PyString_AsString(pyString);

        pyString = PyList_GetItem(value, 3);
        if (pyString == NULL) continue;
        pkg->source_ver = PyString_AsString(pyString);

        pyString = PyList_GetItem(value, 4);
        if (pyString == NULL) continue;
        pkg->arch_all = (!strcmp(PyString_AsString(pyString), "all") ? 1 : 0);

        pyString = PyList_GetItem(value, 5);
        if (pyString == NULL) continue;
        if (pyString != Py_None) {
            pkg->depends[0] = read_dep_andor(PyString_AsString(pyString));
        } else pkg->depends[0] = NULL;

        pyString = PyList_GetItem(value, 6);
        if (pyString == NULL) continue;
        if (pyString != Py_None) {
            pkg->depends[1] = read_dep_andor(PyString_AsString(pyString));
        } else pkg->depends[1] = NULL;

        pyString = PyList_GetItem(value, 7);
        if (pyString == NULL) continue;
        if (pyString != Py_None) {
            pkg->conflicts = read_dep_and(PyString_AsString(pyString));
        } else pkg->conflicts = NULL;

        pyString = PyList_GetItem(value, 8);
        if (pyString == NULL) continue;
        if (pyString != Py_None) {
            pkg->provides = read_packagenames(PyString_AsString(pyString));
        } else pkg->provides = NULL;

        add_package(dpkg_pkgs, pkg);
    }

    dpkgpackages *res;
    res = PyObject_NEW(dpkgpackages, &Packages_Type);
    if (res == NULL) return NULL;

    res->pkgs = dpkg_pkgs;
    res->freeme = FREE;
    res->ref = NULL;

    return (PyObject *)res;
}


/**************************************************************************
 * module initialisation
 ***********************/

static PyMethodDef britneymethods[] = {
	{ "Sources", dpkgsources_new, METH_VARARGS, NULL },
	{ "SourcesNote", dpkgsrcsn_new, METH_VARARGS, NULL },

	{ "versioncmp", apt_versioncmp, METH_VARARGS, NULL },

	{ "buildSystem", build_system, METH_VARARGS, NULL },

	{ NULL, NULL, 0, NULL }
};

void initbritney(void) {
	Py_InitModule("britney", britneymethods);
}

