#!/usr/bin/env python

import sys
import britney

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

packages = {'phpldapadmin': ['1.0', 'web', 'phpldapadmin', '1.0', 'all', '', 'apache2 (>= 2.0)', '', '', [], []],
            'apache2': ['2.0', 'web', 'apache2', '2.0', 'i386', '', '', 'phpldapadmin (<= 1.0~)', '', [], []],
           }

system = britney.buildSystem('i386', packages)
print system.is_installable('phpldapadmin'), system.packages
britney.removeBinary(system, 'apache2')
print system.is_installable('phpldapadmin'), system.packages
britney.addBinary(system, 'apache2', ['2.0', 'web', 'apache2', '2.0', 'i386', '', '', 'phpldapadmin (<= 1.0~)', '', [], []])
print system.is_installable('phpldapadmin'), system.packages
