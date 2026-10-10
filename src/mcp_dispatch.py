"""Bounded network work; local SQLite handles stay on the transport thread."""
import threading
from concurrent.futures import CancelledError, ThreadPoolExecutor


class StdioRequestQueue:
    def __init__(self, server, emit, workers=4, max_pending=16):
        self.server, self._emit = server, emit
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bookmark-network")
        self.max_pending = max_pending
        self.pending = {}
        self.lock = threading.RLock()
        self.output_lock = threading.Lock()
        self.output_closed = False

    @staticmethod
    def _key(message):
        identifier = message.get("id") if isinstance(message, dict) else None
        return (type(identifier), identifier) if type(identifier) in (int, str) else None

    @staticmethod
    def _error(identifier, code, message):
        return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}

    def emit(self, response):
        if response is None:
            return
        with self.output_lock:
            if self.output_closed:
                return
            try:
                self._emit(response)
            except (BrokenPipeError, OSError):
                self.output_closed = True

    def _handle(self, request):
        try:
            return self.server.handle(request)
        except Exception as error:
            self.server._log("Request handler failed (%s)" % type(error).__name__)
            return self._error(request.get("id") if isinstance(request, dict) else None,
                               -32603, "Internal server error")

    def submit(self, request):
        key, future, error = self._key(request), None, None
        with self.lock:
            if key is not None and key in self.pending:
                error = self._error(key[1], -32600, "Request id is already in flight")
            elif key is not None and self.server.background_call(request):
                if len(self.pending) >= self.max_pending:
                    error = self._error(key[1], -32000, "Network request queue is full; retry after an earlier response")
                else:
                    future = self.pool.submit(self._handle, request)
                    self.pending[key] = future
        if error is not None:
            self.emit(error)
        elif future is not None:
            future.add_done_callback(lambda completed: self._done(key, completed))
        else:
            self.emit(self._handle(request))

    def _done(self, key, future):
        try:
            response = future.result()
        except CancelledError:
            response = self._error(key[1], -32800, "Request cancelled before execution")
        with self.lock:
            self.emit(response)
            if self.pending.get(key) is future:
                del self.pending[key]

    def cancel(self, identifier):
        with self.lock:
            future = self.pending.get((type(identifier), identifier))
            if future is not None and not future.cancel():
                # An HTTP request already sent may still consume quota or
                # produce a durable receipt. Let it finish and return that result.
                self.server._log("Cancellation could not stop an already started call; provider timeouts still apply")

    def close(self, cancel_pending=False):
        # Normal EOF drains accepted requests, as line-oriented CLI clients
        # commonly close stdin before collecting responses.
        self.pool.shutdown(wait=True, cancel_futures=cancel_pending)
