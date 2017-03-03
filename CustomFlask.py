import time
from multiprocessing import Event
import threading
from flask import Flask

shutdown = Event()


class CustomFlask(Flask):

    def __init__(self, name, client_conns_dict, final_wait, log, first_request):
        self.CC = client_conns_dict
        self.final_wait = final_wait
        self.log = log
        self.first_request = first_request
        super(CustomFlask, self).__init__(name)

    def run_with_monitors(self, port=5000):
        monitor = threading.Thread(target=self.active_client_monitor)
        monitor.start()

        # flask says this isn't safe for deployment.
        # If you are running this, is it deployment, or employment?
        self.run(port=port)

    def active_client_monitor(self):
        while True:
            active_clients = self.check_active_clients()
            if not active_clients:
                self.shutdown_timer()
            time.sleep(10)

    def shutdown_timer(self):
        active_clients = self.check_active_clients()
        start = time.time()
        time.sleep(10)
        elapsed = 0
        self.log.warning("Entering shutdown timer.")
        while not active_clients and elapsed < self.final_wait:
            time.sleep(10)
            elapsed += 10
            self.log.warning("Timer unbroken by new connections for {} seconds".format(elapsed))
            active_clients = self.check_active_clients()
        if not active_clients and abs(start - time.time()) >= self.final_wait:
            self.log.warning("There have been no new connections for the final timeout {} seconds"
                        .format(self.final_wait))
            shutdown.set()
            return

    def check_active_clients(self, ):
        self.log.debug("Checking active clients!")
        for key, val in self.CC.items():
            self.log.debug("Found client {} with active val {}".format(val.name, val.active))
            if val.active:
                self.log.debug("Active client found.")
                return True
        self.log.debug("No active client found.")
        return False

    def shutdown_monitor(self, servproc):
        while True:
            time.sleep(10)
            if shutdown.is_set():
                self.log.warning("Shutting down server.")
                servproc.terminate()
                servproc.join()
                return

    def auto_shutdown(self):
        start = time.time()
        while not self.first_request.is_set():
            time.sleep(10)
            if abs(start - time.time()) >= self.final_wait:
                self.log.warning("No connections were received before the final wait time of {} seconds."
                                 " Shutting down.".format(self.final_wait))
                shutdown.set()
                return

        # if first_request got set, let's get out of this thread
        return
