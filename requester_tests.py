import unittest
import requester


# I need mock to do more of these
class ClientTests(unittest.TestCase):

    def test_files_gen(self):
        self.assertEqual(next(requester.files_gen('hello')), 'hello_0.data')

    def test_assert_rollover_positive(self):
        self.assertEqual(requester.assert_rollover(2, 5, 10, 120), True)

    def test_assert_rollover_negative(self):
        self.assertEqual(requester.assert_rollover(2, 6, 10, 120), True)

if __name__ == '__main__':

    unittest.main()