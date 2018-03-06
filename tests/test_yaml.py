#!/usr/bin/python3
# (C) 2017 Canonical Ltd.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import fileinput
import json
import os
import pprint
import sys
import unittest

import apt_pkg
import yaml

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from tests import TestBase, mock_swift

apt_pkg.init()


class YamlTest(TestBase):
    """Validate generated yaml"""
    def setUp(self):
        super().setUp()
        self.fake_amqp = os.path.join(self.data.path, 'amqp')

        # Set fake AMQP and Swift server
        for line in fileinput.input(self.britney_conf, inplace=True):
            if 'ADT_AMQP' in line:
                print('ADT_AMQP = file://%s' % self.fake_amqp)
            elif 'ADT_SWIFT_URL' in line:
                print('ADT_SWIFT_URL = http://localhost:18085')
            elif 'ADT_ARCHES' in line:
                print('ADT_ARCHES = amd64 i386')
            else:
                sys.stdout.write(line)

        self.data.add('libc6', False)
        self.sourceppa_cache = {}

        self.email_cache = {}
        for pkg, vals in self.sourceppa_cache.items():
            for version, empty in vals.items():
                self.email_cache.setdefault(pkg, {})
                self.email_cache[pkg][version] = True

        # create mock Swift server (but don't start it yet, as tests first need
        # to poke in results)
        self.swift = mock_swift.AutoPkgTestSwiftServer(port=18085)
        self.swift.set_results({})

    def tearDown(self):
        del self.swift

    def do_test(self, unstable_add):
        """Run britney with some unstable packages and verify excuses.

        unstable_add is a list of (binpkgname, field_dict, daysold)

        Return excuses_dict.
        """
        age_file = os.path.join(self.data.path,
                                'data',
                                'testing',
                                'state',
                                'age-policy-dates')
        for (pkg, fields, daysold) in unstable_add:
            self.data.add(pkg, True, fields, True, None)
            self.sourceppa_cache.setdefault(pkg, {})
            if fields['Version'] not in self.sourceppa_cache[pkg]:
                self.sourceppa_cache[pkg][fields['Version']] = ''
            with open(age_file, 'w') as f:
                import time
                do = time.time() - (60 * 60 * 24 * daysold)
                f.write('%s %s %d' % (pkg, fields['Version'], do))

        # Set up sourceppa cache for testing
        sourceppa_path = os.path.join(self.data.dirs[True], 'SourcePPA')
        with open(sourceppa_path, 'w', encoding='utf-8') as sourceppa:
            sourceppa.write(json.dumps(self.sourceppa_cache))

        (excuses_yaml, excuses_html, out) = self.run_britney()

        # convert excuses to source indexed dict
        excuses_dict = {}
        for s in yaml.load(excuses_yaml, Loader=yaml.CSafeLoader)['sources']:
            excuses_dict[s['source']] = s

        if 'SHOW_EXCUSES' in os.environ:
            print('------- excuses -----')
            pprint.pprint(excuses_dict, width=200)
        if 'SHOW_YAML' in os.environ:
            print('------- excuses.yaml -----\n%s\n' % excuses_yaml)
        if 'SHOW_HTML' in os.environ:
            print('------- excuses.html -----\n%s\n' % excuses_html)
        if 'SHOW_OUTPUT' in os.environ:
            print('------- output -----\n%s\n' % out)

        self.assertNotIn('FIXME', out)

        return excuses_dict

    def test_unsat_deps(self):
        """Test unsatisfiable dependencies list"""
        pkg = ('libc6', {'Version': '2',
                         'Depends': 'notavailable (>= 2)'},
               6)

        excuse = self.do_test([pkg])
        self.assertIn('notavailable (>= 2)', excuse['libc6']['dependencies']['unsatisfiable-dependencies']['amd64'])

    def test_epoch_in_deps(self):
        """Test dependencies listing with epoch in versioned dep"""
        pkg = ('libc6', {'Version': '2',
                         'Depends': 'datefudge (>= 99:1.0-0.1ubuntu8)'},
               6)

        excuse = self.do_test([pkg])
        self.assertIn('datefudge', list(excuse['libc6']['dependencies']['unsatisfiable-dependencies']['amd64'])[0])


if __name__ == '__main__':
    unittest.main()
