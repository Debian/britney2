import unittest
import pep8


class TestCodeFormat(unittest.TestCase):

    def test_conformance(self):
        """Test that we conform to PEP-8."""
        style = pep8.StyleGuide()
        result = style.check_files('.')
        self.assertEqual(result.total_errors, 0,
                         "Found code style errors (and warnings).")
