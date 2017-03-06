from flask import Flask, request, session
import logging
import json
import time
import threading
from multiprocessing import Process, Event
from CustomFlask import CustomFlask, Counter

# TODO: Unit tests
# TODO: make sure the clients' name is printed in the log
# TODO: Print a report after shutdown

log = logging.getLogger('server_app')
log.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

fh = logging.FileHandler('server.log', mode='w')
fh.setLevel(logging.DEBUG)
fh.setFormatter(formatter)
log.addHandler(fh)

ch = logging.StreamHandler()

# you can turn this down, or off, since everything is in the log. I like to see updates on the console.
ch.setLevel(logging.WARNING)
ch.setFormatter(formatter)
log.addHandler(ch)

# These are configurable in the json file
with open("FlaskServer_config.json", 'r') as c:
    config = json.load(c)

TIMEOUT = config["timeout"]
PORT = config["port"]
FINAL_WAIT = config["final_wait"]
CCs = {}

first_request = Event()
shutdown = Event()
is_shutdown = Event()
report = {"total_requests": Counter(0),
          "total_connections": Counter(0),
          "total_timeouts": Counter(0),
          "total_goodbyes": Counter(0)}

app = CustomFlask(__name__, CCs, FINAL_WAIT, log, first_request, shutdown, is_shutdown)
app.debug = False
app.use_reloader=False


def print_report(is_shutdown_event):
    """ Monitor whether the given event has been set; if so, print out the usage report.
    :param multiprocessing.Event is_shutdown_event: Event instance which says whether the server has
    been shutdown
    """
    while not is_shutdown_event.is_set():
        time.sleep(10)
    report_to_print = {}
    for key, val in report.items():
        report_to_print[key] = val.value()
    log.warning("Usage report: {}".format(report_to_print))


def assert_request_format(request_data):
    if "name" and "time" and "signal" and "data" in request_data.keys():
        return True
    else:
        log.warning("A bad request was received! Request will be discarded. Request: {}"
                    .format(request_data))
        return False


def map_requests(request_data, client_conns_dict):

    good_request = assert_request_format(request_data)
    if not good_request:
        return

    if request_data["name"] not in client_conns_dict.keys():

        # is it weird to store objects in a dictionary?
        # I dunno, I feel like this made everything less readable
        # Something about this whole thing is weird, but it works? Can we talk about it??
        client_conns_dict[request_data["name"]] = ClientManager(request_data["name"])
        client = client_conns_dict[request_data["name"]]
        report["total_connections"].increment()
    else:
        client = client_conns_dict[request_data["name"]]
    if request_data["signal"] == 1:

        client.current_data = request_data["data"]
        log.info("Client {} sent some data: {}".format(request_data["name"],
                                                       request_data["data"]))
    if request_data["signal"] == 2:

        # this isn't really a warning, but it makes it pop up on the console
        log.warning("Client {} says {}".format(request_data["name"],
                                               request_data["data"]))

        # Set the client to inactive, since it told us so politely
        if request_data["data"] == "Goodbye.":
            client.active = False
            report["total_goodbyes"].increment()

    if request_data["signal"] == 0 and client.active:

        # we don't need to keep looking for heartbeats if we received a goodbye
        client.current_heartbeat = request_data["time"]
        log.info("Client {} sent a heartbeat at time {}".format(request_data["name"],
                                                                request_data["time"]))


# This is the messiest thing in this whole project. :/
@app.route("/", methods=['POST', 'GET'])
def request_handler():
    """ Function for handling the requests that are sent to the server.
    :return: Sets what to display on the browser at our server's port. This doesn't matter.
    """
    # ideally there would be a way to avoid setting this every time there's a new request
    # it doesn't really matter, just a wasted operation.
    if not first_request.is_set():
        first_request.set()
    report["total_requests"].increment()

    # if the request had zero length, it's probably the client code making sure the server is up.
    # Or it's someone refreshing the browser page. Stop that, it tickles!
    if len(request.data) == 0:
        log.info("Received a zero length request. Nothing to do here.")
        return "Hi"

    # if we sent a nonzero request, it should be in json format
    try:
        request_data = json.loads(request.data)
    except ValueError as e:
        log.error("A malformed request was received! error: {}".format(e))
        raise

    # go confirm that the request was correctly formatted, and then do stuff with it
    map_requests(request_data, CCs)

    # it must return :/ if I understood Flask and requests better I could make this make more sense.
    return "Hello"


class ClientManager(object):
    """ Class for keeping track of whether a client is alive, and writing data streams
    """

    def __init__(self, name):
        self.name = name
        # initializing this to 0 for now meaning no heartbeats/data yet received
        self.current_heartbeat = 0
        self.current_data = 0
        # how do we make sure we're not writing the same data twice?
        self.previous_data = 0
        self.datafile = "{}.data".format(self.name)

        with open(self.datafile, 'a+') as datalog:
            datalog.write("This is the data file for client: {} \n".format(self.name))

        # When we initialize, the client is active
        self.active = True

        log.debug("Initializing client {}!".format(self.name))
        t1 = threading.Thread(target=self.heartbeat_monitor)
        t2 = threading.Thread(target=self.data_monitor)
        t1.start()
        t2.start()

    def heartbeat_monitor(self):
        """ After the first heartbeat, self.hearbeat will be the timestamp of the last heartbeat sent.
        Monitor it to tell if the client has gone away.
        :return: None
        """
        elapsed = 10

        # this is clunky... I can't do "while self.current_heartbeat != 0"
        # because it *IS* 0 at some point
        while True:
            time.sleep(1)
            if self.current_heartbeat != 0 and self.active:
                now = time.time()
                while abs(now - self.current_heartbeat) > elapsed:
                    log.info("The client {} hasn't sent a heartbeat in over {} seconds."
                             .format(self.name, elapsed))
                    time.sleep(10)
                    elapsed += 10

                if abs(now - self.current_heartbeat) > TIMEOUT:
                    log.warning("Client {}: No heartbeat received for {} seconds - marking as failed."
                                .format(self.name, TIMEOUT))
                    self.active = False
                    report["total_timeouts"].increment()

                    # can't recover after this, so we might as well exit this thread
                    return

    def data_monitor(self):
        """ While the client is considered active, write the process info data to a file.
        :return: None
        """
        # I know there is some "proper" way to pass information between threads.
        # but I don't see why using a self parameter is wrong. I'd love to know.
        while self.active:
            if self.current_data != 0:
                with open(self.datafile, 'a+') as datalog:
                    datalog.write(str(self.current_data) + "\n")
                self.previous_data = self.current_data
                self.current_data = 0


if __name__ == "__main__":
    # Start up the server in a process, and then send that process to the shutdown monitors.
    # This way we can kill it.
    server = Process(target=app.run_with_monitors, kwargs={'port': PORT})
    server.start()
    log.warning("Server started here.")

    shutdown_thread = threading.Thread(target=app.shutdown_monitor, args=(server,))
    auto_shutdown_thread = threading.Thread(target=app.auto_shutdown)
    print_report_thread = threading.Thread(target=print_report, args=(is_shutdown,))
    shutdown_thread.start()
    auto_shutdown_thread.start()
    print_report_thread.start()
