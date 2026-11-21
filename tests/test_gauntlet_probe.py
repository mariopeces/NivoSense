import unittest


class GauntletProbe(unittest.TestCase):
    def test_deliberate_failure(self) -> None:
        self.assertEqual(1 + 1, 3)
