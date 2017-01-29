TEST_HINTER = 'test-hinter'
HINTS_ALL = ('ALL')
DEFAULT_URGENCY = 'medium'


class MockObject(object):

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

