import unittest

from britney2 import Suite, Suites, SuiteClass
from britney2.hints import HintParser, single_hint_taking_list_of_packages
from britney2.migrationitem import MigrationItem

from . import HINTS_ALL, TEST_HINTER

SUITES = Suites(
    Suite(SuiteClass.TARGET_SUITE, 'testing', "/somewhere/target", ''),
    [Suite(SuiteClass.PRIMARY_SOURCE_SUITE, 'unstable', "/somewhere/source", '')],
)


MigrationItem.set_suites(SUITES)


def new_hint_parser():
    return HintParser()


def parse_should_not_call_this_function(*args, **kwargs):
    raise AssertionError("Should not be called")


class HintParsing(unittest.TestCase):

    def test_parse_invalid_hints(self):
        hint_parser = new_hint_parser()

        hint_parser.register_hint_type('min-10-arg', parse_should_not_call_this_function, min_args=10)
        hint_parser.register_hint_type('simple-hint', parse_should_not_call_this_function)

        tests = [
            {
                'hint_text': 'min-10-arg foo bar',
                'permissions': HINTS_ALL,
                'error_message_contains': 'Needs at least 10 argument(s), got'
            },
            {
                'hint_text': 'undefined-hint with some arguments',
                'permissions': HINTS_ALL,
                'error_message_contains': 'Unknown hint found in'
            },
            {
                'hint_text': 'simple-hint foo/1.0',
                'permissions': ['not-this-hint'],
                'error_message_contains': 'not a part of the permitted hints for'
            },
        ]

        for test in tests:
            with self.assertLogs() as cm:
                hint_parser.parse_hints(TEST_HINTER, test['permissions'], 'test-parse-hint', [test['hint_text']])

            assert len(cm.output) == 1
            assert test['error_message_contains'] in cm.output[0]
            assert hint_parser.hints.is_empty

    def test_alias(self):
        hint_parser = new_hint_parser()
        hint_parser.register_hint_type('real-name',
                                       single_hint_taking_list_of_packages,
                                       aliases=['alias1', 'alias2']
                                       )
        hint_parser.parse_hints(TEST_HINTER,
                                HINTS_ALL,
                                'test-parse-hint',
                                [
                                    'alias1 foo/1.0',
                                    'alias2 bar/2.0',
                                ])
        hints = hint_parser.hints
        # Aliased hints can be found by the real name
        assert hints.search(type='real-name', package='foo', version='1.0')
        assert hints.search(type='real-name', package='bar', version='2.0')
        # But not by their alias
        assert not hints.search(type='alias1', package='foo', version='1.0')
        assert not hints.search(type='alias2', package='bar', version='2.0')


if __name__ == '__main__':
    unittest.main()
