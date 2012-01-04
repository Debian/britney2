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
        # copy upgrade_me
        self.packages = britney.upgrade_me[:]

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
                prefix = ''
                if len(text) > 0 and text[0] == '-':
                    text = text[1:]
                    prefix = '-'
                start = bisect.bisect_left(self.packages, text)
                while start < len(self.packages):
                    if not self.packages[start].startswith(text):
                        break
                    self.matches.append(prefix + self.packages[start])
                    start += 1

        if len(self.matches) > state:
            return self.matches[state]
        return None

