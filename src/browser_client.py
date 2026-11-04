"""Local Browser Rendering provider using Playwright or Chrome DevTools Protocol (CDP).

Disabled by default; must be explicitly enabled via settings.browser.enabled=True.
No mandatory external dependencies: optional playwright import, CDP driver, or mock.
"""

import base64
import concurrent.futures
import json
import os
import re
import socket
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from release import user_agent
from remote_mcp import McpError, McpHttpClient
from settings import Settings


class BrowserClient:
    """Render dynamic JavaScript pages using a local browser engine."""

    _mock_handler = None  # Class-level mock handler for testing

    def __init__(self, settings=None, timeout=None):
        self.settings = settings if settings is not None else Settings()
        self.timeout = timeout
        self._lock = threading.Lock()
        self._renders = 0
        self._requests = 0

    def snapshot_usage(self):
        with self._lock:
            return {"http_requests": self._requests, "tool_calls": self._renders}

    @classmethod
    def set_mock(cls, handler):
        cls._mock_handler = handler

    @classmethod
    def clear_mock(cls):
        cls._mock_handler = None

    def _render_mock(self, url, timeout):
        handler = BrowserClient._mock_handler
        if callable(handler):
            res = handler(url)
            if isinstance(res, Exception):
                raise res
            return res
        sample = ("This is rendered prose content that has enough sentences to pass the prose weight check and be classified as usable. Sentence one. Sentence two. Sentence three. Sentence four. " * 5)
        return {
            "url": url,
            "title": "Rendered Page Title",
            "text": sample,
            "content": sample
        }

    def _render_playwright(self, url, timeout, headless=True):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise McpError("Playwright is not installed. Install with 'pip install playwright' or configure CDP driver", "dependency_missing")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            try:
                page = browser.new_page(user_agent=user_agent())
                page.set_default_timeout(int(timeout * 1000))
                page.goto(url, wait_until="networkidle")
                title = page.title()
                # Evaluate full body innerText
                text = page.evaluate("() => document.body ? document.body.innerText : ''")
                final_url = page.url or url
                return {"url": final_url, "title": title, "text": text, "content": text}
            finally:
                browser.close()

    @staticmethod
    def _cdp_ws_evaluate(ws_url, expression, timeout=10):
        if not ws_url:
            return None
        parsed = urllib.parse.urlparse(ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 9222
        path = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")

        sock = socket.create_connection((host, port), timeout=timeout)
        try:
            sock.settimeout(timeout)
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            handshake = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            )
            sock.sendall(handshake.encode("ascii"))

            response = b""
            while b"\r\n\r\n" not in response:
                chunk = sock.recv(4096)
                if not chunk:
                    return None
                response += chunk

            if b" 101 " not in response:
                return None

            msg = json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": True
                }
            }).encode("utf-8")

            length = len(msg)
            header = bytearray([0x81])
            if length <= 125:
                header.append(0x80 | length)
            elif length <= 65535:
                header.append(0x80 | 126)
                header.extend(struct.pack("!H", length))
            else:
                header.append(0x80 | 127)
                header.extend(struct.pack("!Q", length))

            mask = os.urandom(4)
            header.extend(mask)
            masked_payload = bytes(b ^ mask[i % 4] for i, b in enumerate(msg))
            sock.sendall(bytes(header) + masked_payload)

            buf = bytearray()
            deadline = time.time() + timeout
            while time.time() < deadline:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf.extend(chunk)
                while len(buf) >= 2:
                    opcode = buf[0] & 0x0F
                    payload_len = buf[1] & 0x7F
                    offset = 2
                    if payload_len == 126:
                        if len(buf) < 4:
                            break
                        payload_len = struct.unpack("!H", buf[2:4])[0]
                        offset = 4
                    elif payload_len == 127:
                        if len(buf) < 10:
                            break
                        payload_len = struct.unpack("!Q", buf[2:10])[0]
                        offset = 10

                    if len(buf) < offset + payload_len:
                        break

                    frame_data = buf[offset:offset + payload_len]
                    buf = buf[offset + payload_len:]
                    if opcode == 0x1:
                        try:
                            res = json.loads(frame_data.decode("utf-8"))
                            if res.get("id") == 1:
                                return res.get("result", {}).get("result", {}).get("value")
                        except Exception:
                            pass
            return None
        finally:
            sock.close()

    def _render_cdp(self, url, timeout, cdp_url="http://127.0.0.1:9222"):
        version_url = cdp_url.rstrip("/") + "/json/version"
        req = urllib.request.Request(version_url, headers={"User-Agent": user_agent()})
        try:
            with urllib.request.urlopen(req, timeout=min(5, timeout)) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise McpError("Cannot connect to Chrome DevTools Protocol at %s: %s" % (cdp_url, exc),
                           "connection_error", True) from None

        new_tab_url = cdp_url.rstrip("/") + "/json/new?" + urllib.request.quote(url, safe="")
        new_req = urllib.request.Request(new_tab_url, method="PUT", headers={"User-Agent": user_agent()})
        try:
            with urllib.request.urlopen(new_req, timeout=min(5, timeout)) as resp:
                tab = json.loads(resp.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise McpError("CDP failed to create page tab: %s" % exc, "browser_error", True) from None

        tab_id = tab.get("id")
        ws_url = tab.get("webSocketDebuggerUrl")
        close_url = cdp_url.rstrip("/") + "/json/close/" + str(tab_id) if tab_id else None
        try:
            time.sleep(min(2.0, timeout))
            list_url = cdp_url.rstrip("/") + "/json/list"
            with urllib.request.urlopen(list_url, timeout=5) as resp:
                tabs = json.loads(resp.read().decode("utf-8"))
            if isinstance(tabs, list):
                active = next((t for t in tabs if isinstance(t, dict) and t.get("id") == tab_id), tab)
            elif isinstance(tabs, dict):
                active = tabs
            else:
                active = tab
            title = active.get("title", "")
            eval_result = None
            if ws_url:
                try:
                    eval_expr = "(() => ({ title: document.title || '', text: (document.body ? document.body.innerText : (document.documentElement ? document.documentElement.innerText : '')) }))()"
                    eval_result = self._cdp_ws_evaluate(ws_url, eval_expr, timeout=min(5, timeout))
                except Exception:
                    eval_result = None

            body_text = None
            if isinstance(eval_result, dict):
                body_text = (eval_result.get("text") or "").strip()
                title = eval_result.get("title") or title

            if not body_text:
                raise McpError("CDP failed to extract page text: no usable body text extracted from " + url, "browser_error", True)

            return {
                "url": active.get("url", url),
                "title": title,
                "text": body_text,
                "content": body_text
            }
        finally:
            if close_url:
                try:
                    close_req = urllib.request.Request(close_url, method="GET")
                    urllib.request.urlopen(close_req, timeout=2)
                except Exception:
                    pass

    def _render_one(self, url, driver, timeout, cdp_url, headless):
        with self._lock:
            self._requests += 1
            self._renders += 1

        if self._mock_handler is not None or driver == "mock":
            return self._render_mock(url, timeout)

        if driver == "playwright":
            return self._render_playwright(url, timeout, headless=headless)
        elif driver == "cdp":
            return self._render_cdp(url, timeout, cdp_url=cdp_url)
        elif driver == "auto":
            # Try playwright first, then CDP
            try:
                import playwright.sync_api  # noqa: F401
                return self._render_playwright(url, timeout, headless=headless)
            except ImportError:
                return self._render_cdp(url, timeout, cdp_url=cdp_url)
        else:
            raise ValueError("Unknown browser driver: %s" % driver)

    def call(self, purpose, query=None, urls=None, limit=None):
        if purpose != "fetch":
            raise ValueError("Browser provider supports fetch only")
        if not urls:
            raise ValueError("urls must be a non-empty list")

        preferences = self.settings.load()
        browser_cfg = preferences.get("browser", {})
        if not browser_cfg.get("enabled"):
            raise McpError("Browser rendering provider is disabled in settings; enable with settings.browser.enabled=true",
                           "capability_unavailable")

        driver = browser_cfg.get("driver", "auto")
        cdp_url = browser_cfg.get("cdp_url", "http://127.0.0.1:9222")
        headless = browser_cfg.get("headless", True)
        timeout = self.timeout if self.timeout is not None else browser_cfg.get("timeout_seconds", 20)
        max_concurrency = min(browser_cfg.get("max_concurrency", 2), len(urls))

        successful_results, failed_results = [], []

        def execute(url):
            try:
                result = self._render_one(url, driver, timeout, cdp_url, headless)
                return result, None
            except McpError as exc:
                return None, {"url": url, **exc.details()}
            except TimeoutError:
                return None, {"url": url, "error": "Browser rendering timed out after %ds" % timeout,
                              "error_kind": "timeout", "retryable": True}
            except Exception as exc:
                return None, {"url": url, "error": "Browser render failed: %s" % exc,
                              "error_kind": "browser_error", "retryable": False}

        if len(urls) == 1:
            res, err = execute(urls[0])
            if res is not None:
                successful_results.append(res)
            else:
                failed_results.append(err)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrency) as pool:
                futures = {pool.submit(execute, url): url for url in urls}
                for future in concurrent.futures.as_completed(futures):
                    url = futures[future]
                    try:
                        res, err = future.result(timeout=timeout + 2)
                        if res is not None:
                            successful_results.append(res)
                        else:
                            failed_results.append(err)
                    except concurrent.futures.TimeoutError:
                        failed_results.append({
                            "url": url,
                            "error": "Browser rendering timed out after %ds" % timeout,
                            "error_kind": "timeout",
                            "retryable": True
                        })
                    except Exception as exc:
                        failed_results.append({
                            "url": url,
                            "error": "Browser render failed: %s" % exc,
                            "error_kind": "browser_error",
                            "retryable": False
                        })

        content_blocks = [
            {"type": "text", "text": json.dumps(item, ensure_ascii=False)}
            for item in successful_results
        ]
        return {
            "content": content_blocks,
            "structuredContent": {
                "results": successful_results,
                "failed_results": failed_results
            }
        }
