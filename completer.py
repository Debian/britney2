# -*- coding: utf-8 -*-

# Copyright (C) 2011 Niels Thykier <niels@thykier.net>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

import readline
import bisect

class Completer:
    """Completer class

    This class provides a readline completer for the britney hint-tester
    command-line interface.
    """

    def __init__(self, britney):
        """Constructor

        Creates a completer for a given britney.
        """
        self.matches = []
        self.cmds = ['easy', 'hint', 'force-hint', 'exit', 'quit']
        self.britney = britney
        # generate a completion list from excuses.
        # - it might contain too many items, but meh
        complete = []
        for e in britney.excuses:
            ver = None
            pkg = e.name
            suite = 'unstable'
            if pkg[0] == '-':
                suite = 'testing'
                pkg = pkg[1:]
            if "/" in pkg:
                pkg = pkg.split("/")[0]
            name = "%s/%s" % (e.name, britney.sources[suite][pkg][0]) # 0 == VERSION
            complete.append(name)
        self.packages = sorted(complete)

    def completer(self, text, state):
        """readline completer (see the readline API)"""

        origline = readline.get_line_buffer()
        words = origline.split()

        if state < 1:
            self.matches = []
            if len(words) < 1 or words[0] == text:
                # complete a command
                self.matches = [x for x in self.cmds if x.startswith(text)]
            else:
                # complete pkg/[arch/]version
                start = bisect.bisect_left(self.packages, text)
                while start < len(self.packages):
                    if not self.packages[start].startswith(text):
                        break
                    self.matches.append(self.packages[start])
                    start += 1

        if len(self.matches) > state:
            return self.matches[state]
        return None

