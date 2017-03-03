from flask import Flask, request, session
import logging
import json
import time
import threading

# TODO: Docstrings, unit tests
# TODO: Configurable server (JSON)
# TODO: Ensure files are being opened/made at the right time/if they don't exist
# TODO: Handle signal 2 for client info (log on, log off, rollover)
# TODO: make sure the clients' name is printed in the log

app = Flask(__name__)

with open("FlaskServer_config.json", 'r') as c:
    config = json.load(c)

TIMEOUT = config["timeout"]
PORT = config["port"]
FINAL_TIMEOUT = config["final_timeout"]

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

# "client_connections" was too long to type all the time.
CCs = {}

# there are three options for the Server State (SS):
# CCs is empty, and there have been no connections;
# CCs is non-empty (there are client connections);
# CCs is empty, and there *have* been connections; time to shutdown.
SS = 0

@app.route("/", methods=['POST', 'GET'])
def request_handler():
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
        log.info("Got a heartbeat at time {}".format(rtime))
    if rsignal == 1:
        CCs[rname].current_data = rdata
        log.info("Got some data: {}".format(rdata))
    if rsignal == 2:
        # this isn't really a warning, but it makes it pop up on the console
        log.warning("Client {} says {}".format(rname, rdata))
    return "Hello"


def shutdown_server():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()


@app.route('/shutdown', methods=['POST'])
def shutdown():
    shutdown_server()
    return 'Server shutting down...'


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

                    # The client failed, so we can remove it from the list.
                    # This way, if it reconnects, we re-initialize
                    CCs.pop(self.name)

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

    # flask says this isn't safe for deployment. Is you running this deployment, or employment?
    app.run(port=PORT)
