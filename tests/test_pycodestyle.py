import os
import unittest
import pycodestyle


EXCEPTIONS_BY_FILE = {
    'britney.py': 36,
    'britney2/__init__.py': 2,
    'britney2/excuse.py': 5,
    'britney2/hints.py': 8,
    'britney2/installability/tester.py': 4,
    'britney2/policies/__init__.py': 2,
    'britney2/policies/policy.py': 27,
    'britney2/policies/autopkgtest.py': 9,
    'tests/mock_swift.py': 2,
    'tests/__init__.py': 31,
    'tests/test_autopkgtest.py': 338,
    'tests/test_policy.py': 31,
    'tests/test_yaml.py': 1,
}


def _on_error(e):
    raise e


def all_python_files(project_dir):

    for basedir, subdirs, files in os.walk(project_dir, onerror=_on_error):
        if basedir == project_dir:
            if '.git' in subdirs:
                subdirs.remove('.git')
            if 'doc' in subdirs:
                subdirs.remove('doc')
            if 'britney2-tests' in subdirs:
                subdirs.remove('britney2-tests')

        subdirs.sort()
        files.sort()

        for file in files:
            if file.endswith('.py'):
                path = os.path.join(basedir, file)
                name = path[len(project_dir)+1:]
                yield path, name


class TestCodeFormat(unittest.TestCase):

    def test_conformance(self):
        """Test that we conform to PEP-8."""
        project_dir = os.path.dirname(os.path.dirname(__file__))
        codestyle_cfg = os.path.join(project_dir, 'setup.cfg')
        for python_file, name in all_python_files(project_dir):
            options = {
                'config_file': codestyle_cfg,
            }
            style = pycodestyle.StyleGuide(**options)
            result = style.input_file(python_file)
            limit = EXCEPTIONS_BY_FILE.get(name, 0)
            # The number are the "unfixed" errors at time of introduction.
            # As we fix them, this number should be reduced.
            self.assertEqual(result, limit,
                             "Found code style errors (and warnings) in %s (%s)." % (name, python_file))
