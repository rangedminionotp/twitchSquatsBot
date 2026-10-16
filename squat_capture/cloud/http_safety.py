"""Small single-instance safeguards, not a replacement for a TLS reverse proxy."""
import threading
import time
from collections import OrderedDict
from http.server import ThreadingHTTPServer


class RateLimiter:
    def __init__(self, clock=time.monotonic):
        self.clock=clock;self.lock=threading.Lock();self.entries=OrderedDict()

    def allow(self, key, limit, seconds=60):
        with self.lock:
            now=self.clock()
            started,count=self.entries.get(key,(now,0))
            if now-started>=seconds:started,count=now,0
            self.entries[key]=(started,count+1);self.entries.move_to_end(key)
            while len(self.entries)>2048:self.entries.popitem(last=False)
            return count<limit


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=32

    def __init__(self, *args, **kwargs):
        self.slots=threading.BoundedSemaphore(32)
        super().__init__(*args,**kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:super().process_request(request,client_address)
        except Exception:
            self.slots.release();raise

    def process_request_thread(self, request, client_address):
        try:super().process_request_thread(request,client_address)
        finally:self.slots.release()

    def handle_error(self, request, client_address):
        # Exception strings can contain tokens, cookie values or bearer URLs.
        print('Cloud request failed; details suppressed to protect credentials.')
