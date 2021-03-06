import requests
import time
import logging
import json
import multiprocessing
import psutil
import os

# TODO: Request headers!
# TODO: Unit Tests!
# TODO: Log different clients to different logfiles
# TODO: configurable log location
# TODO: Parse psutil info better


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

STATUS_UP_CODES = [200, 201, 202, 203, 204, 205, 206]


# Helper functions!

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


def get_next_file(current_file, base_name, chunk_size, max_size, gen):
    """ Determine if it's time to roll over to the next file, knowing the size of the next write
    :param str current_file: the text string of the name of the current file
    :param str base_name: the naming schema for the file
    :param int chunk_size: the number of byes being written at a time
    :param int max_size: the max size of the file
    :param generator gen: the instantiation of the generator which counts up files
    :return (str, bool): the file to write to, whether we rolled over or not
    """
    rolling = False

    if not current_file:
        write_file = gen.next()
    elif os.path.getsize(current_file) > max_size - chunk_size:
        write_file = gen.next()
        rolling = True
    else:
        write_file = current_file
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


def write_and_roll(write_file, base_name, chunk_size, max_size, gen):
    """ Write data to the correct file, rolling over as appropriate
    :param str base_name: the naming schema for the files
    :param int chunk_size: the number of byes being written at a time
    :param int max_size: the max size of the files
    :param generator gen: the generator which counts up files
    :return bool: whether the file rolled during this write, so this can be logged and sent to the server
    """
    current_file = write_file
    current_file, rolling = get_next_file(current_file, base_name, chunk_size, max_size, gen=gen)
    rand_write(current_file, chunk_size)
    return current_file, rolling


def assert_rollover(chunk_size, max_size, interval, runtime, desired_rollovers=2):
    # move over once, move over twice
    # come on honey don't be cold as ice
    """ Determine if we will write enough data to roll over the datafiles twice
    :param int chunk_size: the number of byes being written at a time
    :param int max_size: the max size of the files
    :param int interval: how many seconds to wait between writes
    :param int runtime: how many seconds to run for
    :param int desired_rollovers: how many times the data files should roll over
    :return bool: Whether or not we will roll over at least twice
    """
    # a write size of 2 and file size of 5 means files will get filled to 2*2 = 4
    writes_per_file = max_size / chunk_size

    writes = runtime / interval

    if writes > writes_per_file * desired_rollovers:
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


class FlaskServerNotUp(BaseException):
    pass


class RequestClient(object):
    """ A class for initializing a client which will send heartbeats, write data, and monitor the
    process which sends data.
    """

    def __init__(self, name, url, runtime=120, chunk_size=1000, file_size=1000, data_interval=10,
                 rollovers=2):
        self.name = name
        self.runtime = runtime
        self.start = time.time()
        self.chunk_size = chunk_size
        if chunk_size < 10000000:
            log.warning("The given chunk size for client {} is smaller than 10MB.".format(self.name))
        self.file_size = file_size
        self.data_interval = data_interval
        self.url = url
        self.rollovers = rollovers
        self.current_file = None
        self.end_data_tunnel = multiprocessing.Event()

        self.base_name = 'data_{}'.format(self.name)
        self.gen = files_gen(self.base_name)

        if not assert_rollover(chunk_size=self.chunk_size,
                               max_size=self.file_size,
                               interval=self.data_interval,
                               runtime=self.runtime,
                               desired_rollovers=self.rollovers):
            log.warning("The configuration for {} does not meet the specified rollover "
                        "requirements ({}).".format(self.name, self.rollovers))

    def run(self):
        """ Kick off heartbeats, data writer, and data writer monitor in separate processes
        """
        self.send_request(signal=2, data="Hello!")
        log.debug("Logging client {} onto server...".format(self.name))

        p1 = multiprocessing.Process(target=self.heartbeats)
        p2 = multiprocessing.Process(target=self.data)
        p3 = multiprocessing.Process(target=self.monitor, args=(p2,))
        p1.start()
        p2.start()
        p3.start()
        log.info("All processes started on {}".format(self.name))

    def send_request(self, signal, data):
        """ Format a request to send to the server
        :param int signal: What kind of request (heartbeat, data, client info)
        :param str data: Data in addition to signal
        """
        now = time.time()
        payload = json.dumps({"name": self.name,
                              "signal": signal,
                              "time": now, "data": data})
        r = requests.post(self.url, data=payload)
        if r.status_code not in STATUS_UP_CODES:
            log.error("Attempted to send data at time: {} but received status code: {}"
                      .format(now, r.status_code))
            raise FlaskServerNotUp
        if signal == 0:
            log.debug("Sending heartbeat for time {}".format(now))
        elif signal == 1:
            log.debug("Sending data for time {}. Data: {}".format(now, data))
        elif signal ==2:
            log.debug("Sending client information for time: {}. Information: {}".format(now, data))
        else:
            log.debug("An unrecognized signal was sent! Signal: {}. Data: {}".format(signal, data))

    def heartbeats(self):
        """ At intervals of 5 sec, send a heartbeat to the server
        """
        while abs(self.start - time.time()) < self.runtime:
            time.sleep(5)
            self.send_request(signal=0, data="Heartbeat")

        # to avoid race conditions, we wait until the monitor thread says it's done
        while not self.end_data_tunnel.is_set():
            time.sleep(1)
        self.send_request(signal=2, data="Goodbye.")

    def data(self):
        """ At a configurable interval, write random data to files
        """
        while abs(self.start - time.time()) < self.runtime:
            time.sleep(self.data_interval)

            log.info("{} - Writing {} byes of data".format(self.name, self.chunk_size))
            self.current_file, rolling = write_and_roll(self.current_file, self.base_name,
                                                        self.chunk_size, self.file_size,
                                                        self.gen)
            if rolling:
                log.info("{} - Rolling over a new file.".format(self.name))
                self.send_request(signal=2, data="Data writer has rolled over to a new file.")

    def send_proc_info(self, proc):
        """ Gather info on the given process and send that data to the server.
        :param  multiprocessing.Process proc: the process to monitor
        """
        thread_info = get_proc_info(proc)

        # if the PID went to None, thread_info will be None.
        if thread_info:
            self.send_request(signal=1, data=str(thread_info))

    def monitor(self, proc):
        """ At intervals of 10 sec, run send_proc_info to gather and send process info
        :param  multiprocessing.Process proc: the process to monitor
        """
        while abs(self.start - time.time()) < self.runtime:
            time.sleep(10)
            self.send_proc_info(proc)
        self.end_data_tunnel.set()

if __name__ == "__main__":

    # TODO: should this be in a try statement?
    with open("requester_config.json", "r") as c:
        config = json.load(c)

    PORT = config["port"]
    URL = 'http://127.0.0.1:{}'.format(PORT)
    ROLLOVERS = config["desired_rollovers"]

    # Make sure the given port is correct
    try:
        r = requests.get(URL)
        if r.status_code not in STATUS_UP_CODES:
            log.error("Server appears to not be up! Status code {} received.".format(r.status_code))
            raise FlaskServerNotUp
    except requests.ConnectionError:
        log.error("Server not up!")
        raise requests.ConnectionError

    # Make sure we have the right information to run
    for key, val in config["info"].items():
        try:
            assert config["count"] == len(val)
        except AssertionError:
            print "Invalid configuration file provided. You asked for {} clients but gave {} {}!"\
                .format(config["count"], len(val), key)
            raise

    # Now initialize the clients with the given information
    clients = []
    for i in range(config["count"]):
        clients.append(RequestClient(
            name=config["info"]["names"][i],
            url=URL,
            runtime=config["info"]["run_times"][i],
            chunk_size=config["info"]["chunk_sizes"][i],
            file_size=config["info"]["file_sizes"][i],
            rollovers=ROLLOVERS
        ))

    # run them all!
    # Stress testing revealed this could be faster. This would be a future improvement.
    for client in clients:
        client.run()
