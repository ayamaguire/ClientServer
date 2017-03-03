import requests
import time
import logging
import json
import multiprocessing
import psutil
import os

# TODO: Request headers!
# TODO: Docstrings!
# TODO: Unit Tests!
# TODO: Log different clients to different logfiles
# TODO: configurable log location
# TODO: Client needs to roll over data write files

URL = 'http://127.0.0.1:5000'
log = logging.getLogger('client_app')
log.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

fh = logging.FileHandler('client.log', mode='w')
fh.setLevel(logging.DEBUG)
fh.setFormatter(formatter)
log.addHandler(fh)

ch = logging.StreamHandler()
ch.setLevel(logging.WARNING)
ch.setFormatter(formatter)
log.addHandler(ch)


log.info("Logger for clients")


# Helper functions! Maybe I should move these...

def files_gen(base_name):
    # we get up early just to start crankin' the generator
    """ Generator for finding the next file to write to.
    :param str base_name: the naming schema for the files
    :return str: (well, yield) the next file
    """
    # start at -1 so we get _0 as our first data file
    count = -1
    while True:
        count += 1
        new_file = '{}_{}.data'.format(base_name, count)
        yield new_file


def get_next_file(base_name, chunk_size, max_size):
    """ Determine if it's time to roll over to the next file, knowing the size of the next write
    :param str base_name: the naming schema for the file
    :param int chunk_size: the number of byes being written at a time
    :param int max_size: the max size of the file
    :return (str, bool): the file to write to and whether we rolled over or not
    """
    f = files_gen(base_name)
    write_file = f.next()
    rolling = False
    if os.path.exists(write_file) and os.path.getsize(write_file) > max_size - chunk_size:
        write_file = f.next()
        rolling = True
    return write_file, rolling


def rand_write(datafile, chunk_size):
    """ Write random data the given file
    :param str datafile: path to the file to write to
    :param int chunk_size: the number of byes being written at a time
    :return: None
    """
    # I guess fail if you gave me a bad chunk size
    # like what do you want me to do, write half a byte?
    assert isinstance(chunk_size, int)
    with open(datafile, "a+") as df:
        df.write(os.urandom(chunk_size))


def write_and_roll(base_name, chunk_size, max_size):
    """ Write data to the correct file, rolling over as appropriate
    :param str base_name: the naming schema for the files
    :param int chunk_size: the number of byes being written at a time
    :param int max_size: the max size of the files
    :return bool: whether the file rolled during this write, so this can be logged and sent to the server
    """
    current_file, rolling = get_next_file(base_name, chunk_size, max_size)
    rand_write(current_file, chunk_size)
    return rolling


def assert_rollover(chunk_size, max_size, interval, runtime):
    # move over once, move over twice
    # come on honey don't be cold as ice
    """ Determine if we will write enough data to roll over the datafiles twice
    :param int chunk_size: the number of byes being written at a time
    :param int max_size: the max size of the files
    :param int interval: how many seconds to wait between writes
    :param int runtime: how many seconds to run for
    :return bool: Whether or not we will roll over at least twice
    """
    writes = runtime/interval
    total = writes * chunk_size
    if total >= max_size * 2:
        return True
    else:
        return False


def get_proc_info(proc):
    """ Given a process, gather some information on it so we can send this to the server
    :param MultiProcessing.Process proc: Process to monitor
    :return (cputime, meminfo): returns None, if the PID has gone; returns process info otherwise
    """
    if not proc.pid:
        return
    try:
        p = psutil.Process(proc.pid)

        # this is so we don't have to query the process multiple times for data. !
        with p.oneshot():
            cputime = p.cpu_times()
            # memory_info probably returns something different between OSX and linux
            # so we'll have to be careful
            meminfo = p.memory_info()
            return cputime, meminfo

    # since the process we are monitoring only runs for a while, we expect that sometimes it will exit
    # in between when we first check for it and when we query for information
    except psutil.NoSuchProcess:
        log.info("The process must have exited since we looked for it! "
                  "No process found with ID {}".format(proc.pid))

    # however we don't expect access denied, so we raise here
    except psutil.AccessDenied:
        log.error("Process cannot be monitored because access was denied."
                  "Did you kick off the process with incorrect permissions?")
        raise


class RequestClient(object):

    def __init__(self, name, runtime=120, chunk_size=1000, file_size=1000, data_interval=10):
        self.name = name
        self.runtime = runtime
        self.start = time.time()
        self.chunk_size = chunk_size
        self.file_size = file_size
        self.data_interval = data_interval
        self.base_name = 'data_{}'.format(self.name)

        if not assert_rollover(chunk_size=self.chunk_size,
                               max_size=self.file_size,
                               interval=self.data_interval,
                               runtime=self.runtime):
            log.warning("The client {} is not configured to write at least two data files!"
                        .format(self.name))

    def run(self):


        self.send_request(signal=2, data="Hello!")
        log.debug("Logging client {} onto server...".format(self.name))

        p1 = multiprocessing.Process(target=self.heartbeats)
        p2 = multiprocessing.Process(target=self.data)
        p3 = multiprocessing.Process(target=self.monitor, args=(p2,))
        p1.start()
        p2.start()
        p3.start()
        log.info("All processes started on {}".format(self.name))

        # TODO: how do we log a goodbye? join doesn't do what we want it to do?

    def send_request(self, signal, data):
        now = time.time()
        payload = json.dumps({"name": self.name,
                              "signal": signal,
                              "time": now, "data": data})
        r = requests.post(URL, data=payload)
        if signal == 0:
            log.debug("Sending heartbeat for time {}".format(now))
        elif signal == 1:
            log.debug("Sending data for time {}. Data: {}".format(now, data))
        elif signal ==2:
            log.debug("Sending client information for time: {}. Information: ".format(now, data))
        else:
            log.debug("An unrecognized signal was sent! Signal: {}. Data: {}".format(signal, data))

        return r

    def heartbeats(self):
        while abs(self.start - time.time()) < self.runtime:
            time.sleep(5)
            self.send_request(0, None)

    def data(self):
        while abs(self.start - time.time()) < self.runtime:
            time.sleep(self.data_interval)

            log.info("Writing {} byes of data".format(self.chunk_size))
            rolling = write_and_roll(self.base_name, self.chunk_size, self.file_size)
            if rolling:
                log.info("Rolling over a new file.")
                self.send_request(signal=2, data="Data writer has rolled over to a new file.")

    def send_proc_info(self, proc):
        thread_info = get_proc_info(proc)

        # if the PID went to None, thread_info will be None.
        if thread_info:
            self.send_request(signal=1, data=str(thread_info))

    def monitor(self, proc):
        while abs(self.start - time.time()) < self.runtime:
            time.sleep(10)
            self.send_proc_info(proc)


if __name__ == "__main__":

    try:
        r = requests.get(URL)
        if r.status_code != 200:
            log.error("Server appears to not be up! Status code {} received.".format(r.status_code))
            raise StandardError
    except requests.ConnectionError:
        log.error("Server not up!")
        raise requests.ConnectionError

    # TODO: should this be in a try statement?
    with open("requester_config.json", 'r') as c:
        config = json.load(c)

    # TODO: Could this be prettier?
    for key, val in config["info"].items():
        try:
            assert config["count"] == len(val)
        except AssertionError:
            print "Invalid configuration file provided. You asked for {} clients but gave {} {}!"\
                .format(config["count"], len(val), key)
            raise

    clients = []
    for i in range(config["count"]):
        clients.append(RequestClient(
            name=config["info"]["names"][i],
            runtime=config["info"]["run_times"][i],
            chunk_size=config["info"]["chunk_sizes"][i],
            file_size=config["info"]["file_sizes"][i]
        ))

    for client in clients:
        client.run()

    # Client1 = RequestClient("client1", runtime=30)
    # Client2 = RequestClient("client2", runtime=30)
    # Client1.heartbeats()