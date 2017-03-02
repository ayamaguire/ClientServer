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
log = logging.getLogger()
log.setLevel(logging.DEBUG)
log.addHandler(logging.FileHandler('client.log', mode='w'))
log.info("Logger for clients")

# TODO: should this be in a try statement?
with open("requester_config.json", 'r') as c:
    config = json.load(c)


def rand_write(datafile, chunk):
    with open(datafile, "a+") as df:
        df.write(os.urandom(chunk))


class RequestClient(object):

    def __init__(self, name, runtime=120, chunksize=1000, filesize=1000):
        self.name = name
        self.runtime = runtime
        self.start = time.time()
        self.chunksize = chunksize
        self.filesize = filesize

        try:
            r = requests.get(URL)
            if r.status_code != 200:
                log.error("Server appears to not be up! Status code {} received.".format(r.status_code))
                raise StandardError
        except requests.ConnectionError:
            log.error("Server not up!")
            raise requests.ConnectionError

    def run(self):
        p1 = multiprocessing.Process(target=self.heartbeats)
        p2 = multiprocessing.Process(target=self.data)
        p3 = multiprocessing.Process(target=self.monitor, args=(p2,))
        p1.start()
        p2.start()
        p3.start()
        log.info("All processes started on {}".format(self.name))

        # TODO: how do we log a goodbye? join doesn't do what we want it to do?
        # p1.join()
        # p2.join()
        # p3.join()
        log.info("All processes ended here??? {}".format(self.name))

    def heartbeats(self):
        while abs(self.start - time.time()) < self.runtime:
            time.sleep(5)
            now = time.time()
            payload = json.dumps({"name": self.name, "signal": 0, "time": now, "data": None})
            requests.post(URL, data=payload)
            log.debug("Sent heartbeat for time {}".format(now))

    def data(self):
        while abs(self.start - time.time()) < self.runtime:
            time.sleep(10)
            log.info("Writing {} byes of data".format(self.chunksize))
            rand_write("rand_{}.data".format(self.name), self.chunksize)

    def monitor(self, proc):
        while abs(self.start - time.time()) < self.runtime:
            time.sleep(10)
            if proc.pid:
                try:
                    p = psutil.Process(proc.pid)
                except psutil.NoSuchProcess:
                    log.error("The process must have exited since we looked for it! No process found with ID {}"
                             .format(proc.pid))
                except psutil.AccessDenied:
                    log.error("Process cannot be monitored because access was denied. "
                              "Did you kick off the process with incorrect permissions?")
                    raise

                # this is so we don't have to query the process multiple times for data. NIFTY!
                with p.oneshot():
                    try:
                        # iocount = p.io_counters()
                        cputime = p.cpu_times()
                        # memory_info probably returns something different between OSX (my development system) and linux
                        # so we'll have to be careful
                        meminfo = p.memory_info()
                        threadinfo = (cputime, meminfo)
                        now = time.time()
                        payload = json.dumps({"name": self.name, "signal": 1, "time": now, "data": str(threadinfo)})
                        requests.post(URL, data=payload)
                        log.debug("Sent data for time: {} on {}. data: {}".format(now, self.name, threadinfo))
                    except psutil.NoSuchProcess:
                        log.error("The process has ended since we looked for it. "
                                  "No data thread to monitor on client {}".format(self.name))


if __name__ == "__main__":

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
            runtime=config["info"]["runtimes"][i],
            chunksize=config["info"]["chunksizes"][i],
            filesize=config["info"]["filesizes"][i]
        ))

    for client in clients:
        client.run()

    # Client1 = RequestClient("client1", runtime=30)
    # Client2 = RequestClient("client2", runtime=30)
    # Client1.heartbeats()