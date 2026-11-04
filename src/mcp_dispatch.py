"""Bounded network work; local SQLite handles stay on the transport thread."""
import threading
import time
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

    def _handle(self, request, submitted_ns=None):
        started_ns = time.monotonic_ns()
        try:
            response = self.server.handle(request)
        except Exception as error:
            self.server._log("Request handler failed (%s)" % type(error).__name__)
            response = self._error(request.get("id") if isinstance(request, dict) else None,
                                   -32603, "Internal server error")
        if isinstance(request, dict) and request.get("method") == "tools/call":
            params = request.get("params")
            name = params.get("name") if isinstance(params, dict) else None
            if not isinstance(name, str) or not name.isascii() or not name.replace("_", "").isalnum():
                name = "invalid"
            queue_ms = max(0, (started_ns - submitted_ns) // 1_000_000) if submitted_ns is not None else 0
            handler_ms = max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
            result = response.get("result") if isinstance(response, dict) else None
            outcome = "error" if isinstance(response, dict) and ("error" in response or
                      (isinstance(result, dict) and result.get("isError"))) else "ok"
            self.server._log("tool_timing name=%s queue_ms=%d handler_ms=%d outcome=%s" %
                             (name[:64], queue_ms, handler_ms, outcome))
        return response

    def submit(self, request):
        submitted_ns = time.monotonic_ns()
        key, future, error = self._key(request), None, None
        with self.lock:
            if key is not None and key in self.pending:
                error = self._error(key[1], -32600, "Request id is already in flight")
            elif key is not None and self.server.background_call(request):
                if len(self.pending) >= self.max_pending:
                    error = self._error(key[1], -32000, "Network request queue is full; retry after an earlier response")
                else:
                    future = self.pool.submit(self._handle, request, submitted_ns)
                    self.pending[key] = future
        if error is not None:
            self.emit(error)
        elif future is not None:
            future.add_done_callback(lambda completed: self._done(key, completed))
        else:
            self.emit(self._handle(request, submitted_ns))

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
