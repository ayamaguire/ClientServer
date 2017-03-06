import unittest
import requester
import CustomFlask
import multiprocessing
import os
import FlaskServer


class HelperFunctionTests(unittest.TestCase):

    def test_files_gen(self):
        self.assertEqual(next(requester.files_gen('hello')), 'hello_0.data')

    def test_assert_rollover_positive_0(self):
        self.assertEqual(requester.assert_rollover(chunk_size=2, max_size=5, interval=10,
                                                   runtime=120, desired_rollovers=2), True)

    def test_assert_rollover_positive_1(self):
        self.assertEqual(requester.assert_rollover(chunk_size=10000000, max_size=40000000, interval=10,
                                                   runtime=120, desired_rollovers=2), True)

    def test_assert_rollover_negative(self):
        self.assertEqual(requester.assert_rollover(chunk_size=1, max_size=6, interval=10,
                                                   runtime=120, desired_rollovers=2), False)


class GetNextFileTest(unittest.TestCase):
    def setUp(self):

        # with 500 bytes written to the file, test various write sizes to ensure we roll correctly
        with open('hello_0.data', 'a+') as write_file:
            write_file.write(os.urandom(500))

    def tearDown(self):
        os.remove('hello_0.data')

    def test_get_next_positive_0(self):
        f = requester.files_gen('hello')
        a, rolling = requester.get_next_file('hello_0.data', 'hello', 100, 500, f)
        self.assertEqual(rolling, True)

    def test_get_next_positive_1(self):
        f = requester.files_gen('hello')
        a, rolling = requester.get_next_file('hello_0.data', 'hello', 100, 550, f)
        self.assertEqual(rolling, True)

    def test_get_next_negative_0(self):
        f = requester.files_gen('hello')
        a, rolling = requester.get_next_file('hello_0.data', 'hello', 100, 600, f)
        self.assertEqual(rolling, False)

    def test_get_next_negative_1(self):
        f = requester.files_gen('hello')
        a, rolling = requester.get_next_file('hello_0.data', 'hello', 100, 700, f)
        self.assertEqual(rolling, False)


class TestCounterObject(unittest.TestCase):
    # test that multiple processes can modify the TestCounterObject

    def add_one_get_value(self, counter):
        counter.increment()

    def test_increment_val(self):
        MyCounter = CustomFlask.Counter(0)
        p1 = multiprocessing.Process(target=self.add_one_get_value, args=(MyCounter,))
        p1.start()
        p1.join()
        self.assertEqual(MyCounter.value(), 1)

    def test_increment_val_twice(self):
        MyCounter = CustomFlask.Counter(0)
        p1 = multiprocessing.Process(target=self.add_one_get_value, args=(MyCounter,))
        p2 = multiprocessing.Process(target=self.add_one_get_value, args=(MyCounter,))
        p1.start()
        p2.start()
        p1.join()
        p2.join()
        self.assertEqual(MyCounter.value(), 2)


class RequestMappingTest(unittest.TestCase):

    def test_assert_request_format_positive(self):
        request = {"name": "nah", "signal": "bee", "time": "bah", "data": "fee"}
        self.assertEqual(FlaskServer.assert_request_format(request), True)

    def test_assert_request_format_negative_0(self):
        request = {"wah": "nah", "wee": "bee"}
        self.assertEqual(FlaskServer.assert_request_format(request), False)

    def test_assert_request_format_negative_1(self):
        request = {"name": "nah", "signal": "bee", "time": "bah"}
        self.assertEqual(FlaskServer.assert_request_format(request), False)


if __name__ == '__main__':

    unittest.main()