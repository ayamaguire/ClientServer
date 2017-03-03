from flask import Flask, request, session
import logging
import json
import time
import threading
from multiprocessing import Process, Event

# TODO: Docstrings, unit tests
# TODO: Ensure files are being opened/made at the right time/if they don't exist
# TODO: make sure the clients' name is printed in the log
# TODO: MAKE IT CLASSY
# TODO: Print a report after shutdown
# TODO: Properly handle shutdown




with open("FlaskServer_config.json", 'r') as c:
    config = json.load(c)

TIMEOUT = config["timeout"]
PORT = config["port"]
FINAL_WAIT = config["final_wait"]

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



first_request = Event()
shutdown = Event()

# client_connections = {}
CCs = {}


class CustomFlask(Flask):

    def run_with_monitors(self, port=5000):
        monitor = threading.Thread(target=active_client_monitor, args=(CCs,))
        monitor.start()
        self.run(port=port)





def active_client_monitor(CC):
    while True:
        active_clients = check_active_clients(CC)
        if not active_clients:
            shutdown_timer(CC)
        time.sleep(10)


def shutdown_timer(CC):
    active_clients = check_active_clients(CC)
    start = time.time()
    elapsed = 0
    log.warning("Entering shutdown timer.")
    while not active_clients and elapsed < FINAL_WAIT:
        time.sleep(10)
        elapsed += 10
        log.warning("Timer unbroken by new connections for {} seconds".format(elapsed))
        active_clients = check_active_clients(CC)
    if not active_clients and abs(start - time.time()) >= FINAL_WAIT:
        log.warning("There have been no new connections for the final timeout {} seconds"
                    .format(FINAL_WAIT))
        shutdown.set()
        return


def check_active_clients(CC):
    log.debug("Checking active clients!")
    for key, val in CC.items():
        log.debug("Found client {} with active val {}".format(val.name, val.active))
        if val.active:
            log.debug("Active client found.")
            return True
    log.debug("No active client found.")
    return False


def shutdown_monitor(servproc):
    while True:
        time.sleep(10)
        if shutdown.is_set():
            log.warning("Shutting down server.")
            servproc.terminate()
            servproc.join()
            return


def auto_shutdown(servproc):
    start = time.time()
    while not first_request.is_set():
        time.sleep(10)
        if abs(start - time.time()) >= FINAL_WAIT:
            log.warning("No connections were received before the final wait time of {} seconds. "
                        "Shutting down.".format(FINAL_WAIT))
            shutdown.set()
            return

    # if first_request got set, let's get out of this thread
    return


@app.route("/", methods=['POST', 'GET'])
def request_handler():
    first_request.set()
    # log.warning("First connection received - server is active and will not proceed to auto shutdown.")
    # check_thread = threading.Thread(target=check, args=(CCs,))
    # check_thread.start()

    rdata = request.data
    if len(rdata) == 0:
        log.info("Received a zero length request. Nothing to do here.")
        return "Hi"

    # if we sent a nonzero request, it should be in json format
    try:
        rdata = json.loads(rdata)
    except ValueError as e:
        log.error("A malformed request was received! error: {}".format(e))
        raise

    # make sure the request has the right format
    try:
        rname = rdata["name"]
        rtime = rdata["time"]
        rsignal = rdata["signal"]
        rdata = rdata["data"]
    except KeyError as e:
        log.error("A request with incomplete information was sent! error: {}".format(e))
        raise

    if rname not in CCs.keys():

        # is it weird to store objects in a dictionary?
        # I dunno, I feel like this made everything less readable
        CCs[rname] = ClientManager(rname)
    if rsignal == 0:
        CCs[rname].current_heartbeat = rtime
        log.info("Client {} sent a heartbeat at time {}".format(rname, rtime))
    if rsignal == 1:
        CCs[rname].current_data = rdata
        log.info("Client {} sent some data: {}".format(rname, rdata))
    if rsignal == 2:
        # this isn't really a warning, but it makes it pop up on the console
        log.warning("Client {} says {}".format(rname, rdata))

        # Set the client to inactive, since it told us so politely
        if rdata == "Goodbye.":
            CCs[rname].active = False

    return "Hello"


class ClientManager(object):

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

        log.warning("Initializing client {}!".format(self.name))
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
            if self.current_heartbeat != 0:
                now = time.time()
                while abs(now - self.current_heartbeat) > elapsed:
                    log.info("The client {} hasn't sent a heartbeat in over {} seconds.".format(self.name, elapsed))
                    time.sleep(10)
                    elapsed += 10

                if abs(now - self.current_heartbeat) > TIMEOUT:
                    log.warning("No heartbeat received for {} seconds - marking client {} as failed."
                                .format(TIMEOUT, self.name))
                    self.active = False

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

    app = CustomFlask(__name__)
    app.debug = False
    app.use_reloader=False

    # flask says this isn't safe for deployment.
    # If you are running this, is it deployment, or employment?
    server = Process(target=app.run_with_monitors, kwargs={'port': PORT})
    server.start()
    log.warning("Server started here.")

    shutdown_thread = threading.Thread(target=shutdown_monitor, args=(server,))
    auto_shutdown_thread = threading.Thread(target=auto_shutdown, args=(server,))
    shutdown_thread.start()
    auto_shutdown_thread.start()

    # app.start_monitors()

    # The server has to be a process so I can kill it.
    # But they need to share CCs.