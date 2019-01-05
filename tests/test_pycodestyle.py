import os
import unittest
import pycodestyle


class TestCodeFormat(unittest.TestCase):

    def test_conformance(self):
        """Test that we conform to PEP-8."""
        project_dir = os.path.dirname(os.path.dirname(__file__))
        codestyle_cfg = os.path.join(project_dir, 'setup.cfg')
        style = pycodestyle.StyleGuide(config_file=codestyle_cfg)
        result = style.check_files('.')
        self.assertEqual(result.total_errors, 0,
                         "Found code style errors (and warnings).")
