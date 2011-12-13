#include <python2.6/Python.h>

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

static void dpkgpackages_dealloc(dpkgpackages *self) {
	if (self->freeme == FREE) free_packages(self->pkgs);
	Py_XDECREF(self->ref);
	self->pkgs = NULL;
	self->ref = NULL;
	PyObject_DEL(self);
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
    pkg->arch_all = (pyString == Py_None || strcmp(PyString_AsString(pyString), "all") ? 0 : 1);

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
		{ "is_installable", (binaryfunc) dpkgpackages_isinstallable, 
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
 * britney.buildSystem() -- build a fake package system, with the only purpose of
 *                          calling the is_installable method on the packages.
 ******************************************************/

static PyObject *build_system(PyObject *self, PyObject *args) {
    Py_ssize_t pos = 0;
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
        pkg->arch_all = (pyString == Py_None || strcmp(PyString_AsString(pyString), "all") ? 0 : 1);

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
	{ "buildSystem", build_system, METH_VARARGS, NULL },

	{ NULL, NULL, 0, NULL }
};

void initbritney(void) {
	Py_InitModule("britney", britneymethods);
}

