# -*- coding: utf-8 -*-

# Refactored parts from britney.py, which is/was:
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

import re

binnmu_re = re.compile(r'^(.*)\+b\d+$')

def same_source(sv1, sv2, binnmu_re=binnmu_re):
    """Check if two version numbers are built from the same source

    This method returns a boolean value which is true if the two
    version numbers specified as parameters are built from the same
    source. The main use of this code is to detect binary-NMU.

    binnmu_re is an optimization to avoid "load global".
    """
    if sv1 == sv2:
        return 1

    m = binnmu_re.match(sv1)
    if m: sv1 = m.group(1)
    m = binnmu_re.match(sv2)
    if m: sv2 = m.group(1)

    if sv1 == sv2:
        return 1

    return 0
