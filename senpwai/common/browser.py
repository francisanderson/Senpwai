"""Optional in-memory browser transport for manually verified providers."""
import atexit
from concurrent.futures import Future
import os
import threading
import time
from queue import Queue
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
        interaction_timeout: float = 180,
        request_timeout: float = 30,
    ):
        self._playwright_factory = playwright_factory
        self._interaction_timeout = interaction_timeout
        self._request_timeout = request_timeout
        self._queue: Queue[tuple[str, str, dict, Future] | None] = Queue()
        self._started = threading.Event()
        self._startup_error: Exception | None = None
        self._closed = False
        self._ready_hosts: set[str] = set()
        self._thread = threading.Thread(
            target=self._run, name="senpwai-browser-session", daemon=True
        )
        self._thread.start()

    @property
    def unavailable(self) -> bool:
        return self._startup_error is not None

    def request(
        self,
        method: str,
        url: str,
        *,
        data: Any = None,
        headers: dict | None = None,
        allow_redirects: bool = True,
        timeout: float | None = None,
    ) -> BrowserResponse:
        if self._closed:
            raise BrowserUnavailableError("The Animepahe browser session is closed.")
        future: Future = Future()
        self._queue.put(
            (
                method.upper(),
                url,
                {
                    "data": data,
                    "headers": headers or {},
                    "allow_redirects": allow_redirects,
                    "timeout": timeout or self._request_timeout,
                },
                future,
            )
        )
        self._started.wait()
        if self._startup_error is not None:
            raise BrowserUnavailableError(BROWSER_SETUP_MESSAGE) from self._startup_error
        return future.result(timeout=self._interaction_timeout + self._request_timeout + 10)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._queue.put(None)
        self._thread.join(timeout=5)

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
        host = (urlparse(url).hostname or "").lower()
        if host and host not in self._ready_hosts:
            self._ensure_host(host, url, page)
        request_timeout_ms = int(options["timeout"] * 1000)
        response = context.request.fetch(
            url,
            method=method,
            data=options["data"],
            headers=options["headers"],
            max_redirects=20 if options["allow_redirects"] else 0,
            timeout=request_timeout_ms,
        )
        body = response.body()
        result = BrowserResponse(
            response.status, response.headers, body, response.url
        )
        if self._looks_challenged(result):
            raise InvalidDownloadResponse(BROWSER_SETUP_MESSAGE)
        return result

    def _ensure_host(self, host, url, page):
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}/"
        try:
            page.goto(origin, wait_until="domcontentloaded", timeout=30000)
        except Exception as error:
            raise BrowserUnavailableError(
                f"Could not open {origin} in the Animepahe browser session."
            ) from error
        deadline = time.monotonic() + self._interaction_timeout
        while self._html_is_challenged(page.content()):
            if time.monotonic() >= deadline:
                raise BrowserUnavailableError(
                    "Timed out waiting for manual Animepahe verification. "
                    "Complete the challenge in the visible browser and retry."
                )
            time.sleep(0.5)
        self._ready_hosts.add(host)

    @classmethod
    def _html_is_challenged(cls, body: str) -> bool:
        body = body.lower()
        return any(marker in body for marker in CHALLENGE_MARKERS)

    @classmethod
    def _looks_challenged(cls, response: BrowserResponse) -> bool:
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
