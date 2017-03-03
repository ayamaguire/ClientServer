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

# this should be 120; setting to 30 for debugging
TIMEOUT = 30


@app.route("/", methods=['POST', 'GET'])
def request_handler():
    rdata = request.data
    if len(rdata) == 0:
        log.info("Received a zero length request. Probably grabbing some info.")
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
        CCs[rname] = ClientManager(rname)
    if rsignal == 0:
        CCs[rname].current_heartbeat = rtime
        log.info("Got a heartbeat at time {}".format(rtime))
    if rsignal == 1:
        CCs[rname].current_data = rdata
        log.info("Got some data: {}".format(rdata))
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

        with open(self.datafile, 'w') as datalog:
            datalog.write("This is the data file for client: {} \n".format(self.name))

        # When we initialize, the client is active
        self.active = True

        t1 = threading.Thread(target=self.heartbeat_monitor)
        t2 = threading.Thread(target=self.data_monitor)
        t1.start()
        t2.start()

    def heartbeat_monitor(self):
        while True:
            if self.current_heartbeat != 0:
                now = time.time()
                if abs(now - self.current_heartbeat) > 10:
                    log.info("The client {} hasn't sent a heartbeat in over 10 seconds.".format(self.name))
                if abs(now - self.current_heartbeat) > TIMEOUT:
                    log.warning("No heartbeat received for {} seconds - marking client {} as failed."
                                .format(TIMEOUT, self.name))
                    self.active = False

                    # can't recover after this, so we might as well exit this thread
                    return

    def data_monitor(self):
        while self.active:
            if self.current_data != 0:
                with open(self.datafile, 'a+') as datalog:
                    datalog.write(str(self.current_data) + "\n")
                self.previous_data = self.current_data
                self.current_data = 0


if __name__ == "__main__":
    app.run()
