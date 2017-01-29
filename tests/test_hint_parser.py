import unittest

from britney2.hints import HintParser

from . import MockObject, HINTS_ALL, TEST_HINTER


def new_hint_paser(logger=None):
    if logger is None:
        def empty_logger(x, type='I'):
            pass
        logger = empty_logger
    fake_britney = MockObject(log=logger)
    hint_parser = HintParser(fake_britney)
    return hint_parser


def parse_should_not_call_this_function(*args, **kwargs):
    raise AssertionError("Should not be called")


class HintParsing(unittest.TestCase):

    def test_parse_invalid_hints(self):
        hint_log = []
        hint_parser = new_hint_paser(lambda x, type='I': hint_log.append(x))

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
            hint_parser.parse_hints(TEST_HINTER, test['permissions'], 'test-parse-hint', [test['hint_text']])
            assert len(hint_log) == 1
            assert test['error_message_contains'] in hint_log[0]
            assert hint_parser.hints.is_empty
            hint_log.clear()


if __name__ == '__main__':
    unittest.main()
