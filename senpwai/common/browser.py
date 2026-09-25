"""Optional in-memory browser transport for manually verified providers."""
import atexit
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
import os
import threading
import time
from queue import Empty, Queue
from typing import Any, Callable
from urllib.parse import urlparse

from requests import Response
from requests.cookies import RequestsCookieJar
from requests.structures import CaseInsensitiveDict

from senpwai.common.scraper import InvalidDownloadResponse


CHALLENGE_MARKERS = (
    "just a moment",
    "checking your browser",
    "cf-chl-",
    "challenge-platform",
    "cf-turnstile",
    "challenges.cloudflare.com",
)
BROWSER_NAVIGATION_TIMEOUT = 30
BROWSER_SETUP_MESSAGE = (
    "Animepahe needs a browser session. Install Playwright's browser with "
    "`python -m playwright install chromium`, then retry. Senpwai does not "
    "automate or bypass provider verification."
)


class BrowserUnavailableError(InvalidDownloadResponse):
    """The browser transport could not be started or used."""


class BrowserResponse(Response):
    """A requests-compatible response backed by browser-context bytes."""

    def __init__(self, status_code: int, headers: dict, body: bytes, url: str):
        super().__init__()
        self.status_code = status_code
        self.headers = CaseInsensitiveDict(
            {
                key: value if isinstance(value, str) else ", ".join(value)
                for key, value in headers.items()
            }
        )
        self._content = body
        self.url = url
        self.encoding = "utf-8"
        # Never expose the browser context's cookies to the rest of the app.
        self.cookies = RequestsCookieJar()

    def close(self):
        return None


class BrowserSession:
    """Own one visible browser context on a worker thread.

    The user completes any challenge in the visible browser. Requests then
    run through that context, so credentials never leave the in-memory
    context or get written to disk.
    """

    def __init__(
        self,
        playwright_factory: Callable[[], Any] | None = None,
        interaction_timeout: float | None = None,
        request_timeout: float | None = None,
    ):
        self._playwright_factory = playwright_factory
        configured_interaction_timeout = os.environ.get(
            "SENPWAI_BROWSER_INTERACTION_TIMEOUT"
        )
        self._interaction_timeout = float(
            configured_interaction_timeout
            if configured_interaction_timeout is not None
            else interaction_timeout or 180
        )
        self._request_timeout = float(request_timeout or 30)
        self._queue: Queue[tuple[str, str, dict, Future] | None] = Queue()
        self._started = threading.Event()
        self._startup_error: Exception | None = None
        self._closed = False
        self._stop = threading.Event()
        self._lifecycle_lock = threading.RLock()
        self._ready_hosts: set[str] = set()
        self._thread = threading.Thread(
            target=self._run, name="senpwai-browser-session", daemon=True
        )
        self._thread.start()

    @property
    def unavailable(self) -> bool:
        return self._startup_error is not None

    @property
    def finished(self) -> bool:
        return not self._thread.is_alive()

    @property
    def closed(self) -> bool:
        return self._closed

    def request(
        self,
        method: str,
        url: str,
        *,
        data: Any = None,
        form: dict | None = None,
        headers: dict | None = None,
        allow_redirects: bool = True,
        timeout: float | None = None,
    ) -> BrowserResponse:
        with self._lifecycle_lock:
            if self._closed:
                raise BrowserUnavailableError("The Animepahe browser session is closed.")
            future: Future = Future()
            self._queue.put(
                (
                    method.upper(),
                    url,
                    {
                        "data": data,
                        "form": form,
                        "headers": headers or {},
                        "allow_redirects": allow_redirects,
                        "timeout": timeout or self._request_timeout,
                    },
                    future,
                )
            )
        if not self._started.wait(timeout=self._request_timeout + 5):
            raise BrowserUnavailableError(BROWSER_SETUP_MESSAGE)
        if self._startup_error is not None:
            raise BrowserUnavailableError(BROWSER_SETUP_MESSAGE) from self._startup_error
        wait_budget = (
            2 * self._interaction_timeout
            + 2 * self._request_timeout
            + 2 * BROWSER_NAVIGATION_TIMEOUT
            + 10
        )
        try:
            return future.result(timeout=wait_budget)
        except FutureTimeoutError as error:
            raise InvalidDownloadResponse(
                "Animepahe browser request timed out. Complete the challenge and try again."
            ) from error

    def close(self):
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            self._stop.set()
            self._queue.put(None)
        self._thread.join(timeout=self._request_timeout + 5)
        return self.finished

    def _run(self):
        playwright = browser = context = page = None
        try:
            factory = self._playwright_factory or self._default_playwright
            playwright = factory()
            browser = self._launch_browser(playwright)
            context = browser.new_context()
            page = context.new_page()
        except Exception as error:
            self._startup_error = error
        finally:
            self._started.set()

        while True:
            item = self._queue.get()
            if self._stop.is_set():
                self._fail_queued_requests()
                break
            if item is None:
                break
            method, url, options, future = item
            if self._startup_error is not None:
                future.set_exception(
                    BrowserUnavailableError(BROWSER_SETUP_MESSAGE)
                )
                continue
            try:
                future.set_result(self._request(method, url, options, context, page))
            except Exception as error:
                future.set_exception(error)

        for closeable in (context, browser, playwright):
            close = getattr(closeable, "close", None) or getattr(
                closeable, "stop", None
            )
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def _fail_queued_requests(self):
        while True:
            try:
                item = self._queue.get_nowait()
            except Empty:
                return
            if item is not None:
                item[3].set_exception(
                    BrowserUnavailableError("The Animepahe browser session is closed.")
                )

    @staticmethod
    def _launch_browser(playwright):
        configured_channel = os.environ.get("SENPWAI_BROWSER_CHANNEL")
        channels = [configured_channel] if configured_channel else []
        if os.name == "nt":
            channels.extend(("msedge", "chrome"))
        first_error = None
        try:
            return playwright.chromium.launch(headless=False)
        except Exception as error:
            first_error = error
        for channel in channels:
            try:
                return playwright.chromium.launch(channel=channel, headless=False)
            except Exception:
                continue
        raise first_error

    @staticmethod
    def _default_playwright():
        from playwright.sync_api import sync_playwright

        return sync_playwright().start()

    def _request(self, method, url, options, context, page) -> BrowserResponse:
        if self._stop.is_set():
            raise BrowserUnavailableError("The Animepahe browser session is closed.")
        host = (urlparse(url).hostname or "").lower()
        if host and host not in self._ready_hosts:
            self._ensure_host(host, url, page)
        for attempt in range(2):
            result = self._fetch(method, url, options, context)
            if not self._looks_challenged(result):
                return result
            if attempt == 0:
                self._wait_for_path(url, page)
                continue
            raise InvalidDownloadResponse(BROWSER_SETUP_MESSAGE)
        raise InvalidDownloadResponse(BROWSER_SETUP_MESSAGE)

    def _fetch(self, method, url, options, context) -> BrowserResponse:
        request_options = {
            "method": method,
            "headers": options["headers"],
            "max_redirects": 20 if options["allow_redirects"] else 0,
            "timeout": int(options["timeout"] * 1000),
        }
        if options["form"] is not None:
            request_options["form"] = options["form"]
        elif options["data"] is not None:
            request_options["data"] = options["data"]
        response = None
        try:
            response = context.request.fetch(url, **request_options)
            body = response.body()
            headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower() not in ("set-cookie", "set-cookie2")
            }
            return BrowserResponse(response.status, headers, body, response.url)
        except BrowserUnavailableError:
            raise
        except Exception as error:
            raise InvalidDownloadResponse(
                "Animepahe browser request failed. Check the browser session and try again."
            ) from error
        finally:
            if response is not None:
                dispose = getattr(response, "dispose", None)
                if callable(dispose):
                    try:
                        dispose()
                    except Exception:
                        pass

    def _ensure_host(self, host, url, page):
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}/"
        try:
            page.goto(
                origin,
                wait_until="domcontentloaded",
                timeout=BROWSER_NAVIGATION_TIMEOUT * 1000,
            )
        except Exception as error:
            raise BrowserUnavailableError(
                f"Could not open {origin} in the Animepahe browser session."
            ) from error
        self._wait_until_clear(page)
        self._ready_hosts.add(host)

    def _wait_for_path(self, url, page):
        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=BROWSER_NAVIGATION_TIMEOUT * 1000,
            )
        except Exception as error:
            raise BrowserUnavailableError(
                f"Could not open {url} in the Animepahe browser session."
            ) from error
        self._wait_until_clear(page)

    def _wait_until_clear(self, page):
        deadline = time.monotonic() + self._interaction_timeout
        while True:
            try:
                challenged = self._html_is_challenged(page.content())
            except Exception as error:
                raise BrowserUnavailableError(
                    "Could not read the Animepahe browser page."
                ) from error
            if not challenged:
                return
            if self._stop.is_set():
                raise BrowserUnavailableError(
                    "The Animepahe browser session is closed."
                )
            if time.monotonic() >= deadline:
                raise BrowserUnavailableError(
                    "Timed out waiting for manual Animepahe verification. "
                    "Complete the challenge in the visible browser and retry."
                )
            time.sleep(0.5)

    @classmethod
    def _html_is_challenged(cls, body: str) -> bool:
        body = body.lower()
        return any(marker in body for marker in CHALLENGE_MARKERS)

    @classmethod
    def _looks_challenged(cls, response: BrowserResponse) -> bool:
        if response.status_code in (403, 429):
            return True
        content_type = response.headers.get("Content-Type", "").lower()
        return "text/html" in content_type and cls._html_is_challenged(
            response.text[:4096]
        )


_SESSION: BrowserSession | None = None
_SESSION_LOCK = threading.Lock()


def get_browser_session() -> BrowserSession:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is not None and _SESSION.unavailable:
            _SESSION.close()
            _SESSION = None
        if _SESSION is not None and _SESSION.closed and _SESSION.finished:
            _SESSION = None
        if _SESSION is None:
            _SESSION = BrowserSession()
        return _SESSION


def close_browser_session():
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is not None:
            _SESSION.close()
            _SESSION = None


atexit.register(close_browser_session)
