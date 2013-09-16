# -*- coding: utf-8 -*-

# Constants from britney.py
#
# Assuming constants are copyrightable, then they are:
# Copyright (C) 2001-2008 Anthony Towns <ajt@debian.org>
#                         Andreas Barth <aba@debian.org>
#                         Fabio Tranchitella <kobold@debian.org>
# Copyright (C) 2010-2012 Adam D. Barratt <adsb@debian.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# source package
VERSION = 0
SECTION = 1
BINARIES = 2
MAINTAINER = 3
FAKESRC = 4

# binary package
SOURCE = 2
SOURCEVER = 3
ARCHITECTURE = 4
MULTIARCH = 5
# PREDEPENDS = 6 - No longer used by the python code
#  - The C-code needs it for alignment reasons and still check it
#    but ignore it if it is None (so keep it None).
DEPENDS = 7
CONFLICTS = 8
PROVIDES = 9
RDEPENDS = 10
RCONFLICTS = 11
