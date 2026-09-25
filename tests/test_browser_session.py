"""Offline contract tests for the manual Animepahe browser session."""
import threading
import time
import unittest
from requests.cookies import RequestsCookieJar

from senpwai.common.browser import (
    BrowserResponse,
    BrowserSession,
    BrowserUnavailableError,
    InvalidDownloadResponse,
)


class FakeApiResponse:
    def __init__(self):
        self.status = 200
        self.headers = {
            "content-type": "application/json",
            "set-cookie": "secret=should-not-escape",
        }
        self.url = "https://animepahe.pw/api?m=search"
        self.disposed = False
        self.body_value = b'{"data": []}'

    def body(self):
        return self.body_value

    def dispose(self):
        self.disposed = True


class FakeRequestContext:
    def __init__(self):
        self.calls = []
        self.responses = []
        self.error = None

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        response = FakeApiResponse()
        self.responses.append(response)
        return response


class FakePage:
    def __init__(self):
        self.challenge = False
        self.visited = []

    def goto(self, url, **kwargs):
        self.visited.append((url, kwargs))

    def content(self):
        if self.challenge:
            return "<html><title>Just a moment...</title></html>"
        return "<html>ready</html>"


class FakeContext:
    def __init__(self):
        self.page = FakePage()
        self.request = FakeRequestContext()

    def new_page(self):
        return self.page


class FakeBrowser:
    def __init__(self):
        self.context = FakeContext()
        self.closed = False

    def new_context(self):
        return self.context

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, browser):
        self.browser = browser

    def launch(self, **kwargs):
        return self.browser


class FakePlaywright:
    def __init__(self):
        self.browser = FakeBrowser()
        self.chromium = FakeChromium(self.browser)

    def stop(self):
        self.browser.close()


class BrowserSessionTests(unittest.TestCase):
    def test_response_is_requests_compatible_without_exporting_cookies(self):
        response = BrowserResponse(
            200,
            {"Content-Type": "application/json"},
            b'{"data": []}',
            "https://fixture.invalid",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(response.json(), {"data": []})
        self.assertEqual(response.content, b'{"data": []}')
        self.assertIsInstance(response.cookies, RequestsCookieJar)
        self.assertEqual(len(response.cookies), 0)
        response.close()

    def test_session_uses_browser_context_for_requests(self):
        playwright = FakePlaywright()
        session = BrowserSession(playwright_factory=lambda: playwright)
        try:
            response = session.request("GET", "https://animepahe.pw/api?m=search")
        finally:
            session.close()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("set-cookie", response.headers)
        self.assertTrue(playwright.browser.context.request.responses[0].disposed)
        call = playwright.browser.context.request.calls[0]
        self.assertEqual(call[0], "https://animepahe.pw/api?m=search")
        self.assertGreaterEqual(call[1]["max_redirects"], 0)
        self.assertTrue(playwright.browser.context.page.visited)

    def test_post_uses_form_encoding(self):
        playwright = FakePlaywright()
        session = BrowserSession(playwright_factory=lambda: playwright)
        try:
            session.request(
                "POST",
                "https://kwik.cx/f/form",
                form={"_token": "value"},
            )
        finally:
            session.close()
        call = playwright.browser.context.request.calls[0][1]
        self.assertEqual(call["form"], {"_token": "value"})
        self.assertNotIn("data", call)

    def test_session_waits_for_manual_challenge_completion(self):
        playwright = FakePlaywright()
        playwright.browser.context.page.challenge = True
        session = BrowserSession(
            playwright_factory=lambda: playwright, interaction_timeout=1
        )

        def solve_later():
            time.sleep(0.05)
            playwright.browser.context.page.challenge = False

        threading.Thread(target=solve_later, daemon=True).start()
        try:
            response = session.request("GET", "https://animepahe.pw/api?m=search")
        finally:
            session.close()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(playwright.browser.closed)

    def test_pahe_search_uses_the_browser_session(self):
        from unittest.mock import Mock, patch
        from senpwai.scrapers.pahe import main as pahe

        browser = Mock()
        browser.request.return_value = BrowserResponse(
            200, {"Content-Type": "application/json"}, b'{"data": []}', "https://animepahe.pw/api?m=search"
        )
        with patch.object(pahe, "get_browser_session", return_value=browser):
            self.assertEqual(pahe.search("fixture"), [])
        self.assertEqual(browser.request.call_args.args[:2], ("GET", pahe.API_ENTRY_POINT + "search&q=fixture"))
        self.assertEqual(browser.request.call_args.kwargs["timeout"], pahe.SEARCH_TIMEOUT)

    def test_path_challenge_is_opened_for_manual_completion(self):
        playwright = FakePlaywright()
        first = FakeApiResponse()
        first.status = 403
        first.headers = {"content-type": "text/html"}
        first.body_value = b"<html><title>Just a moment...</title></html>"
        calls = []

        def fetch(url, **kwargs):
            calls.append((url, kwargs))
            return first if len(calls) == 1 else FakeApiResponse()

        playwright.browser.context.request.fetch = fetch
        session = BrowserSession(playwright_factory=lambda: playwright)
        try:
            response = session.request("GET", "https://animepahe.pw/api?m=search")
        finally:
            session.close()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(calls), 2)
        self.assertIn("https://animepahe.pw/api?m=search", [url for url, _ in playwright.browser.context.page.visited])

    def test_close_interrupts_a_waiting_manual_challenge(self):
        playwright = FakePlaywright()
        playwright.browser.context.page.challenge = True
        session = BrowserSession(playwright_factory=lambda: playwright, interaction_timeout=10)
        errors = []

        def request():
            try:
                session.request("GET", "https://animepahe.pw/")
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=request)
        thread.start()
        time.sleep(0.05)
        session.close()
        thread.join(timeout=2)
        self.assertTrue(errors)
        self.assertIsInstance(errors[0], BrowserUnavailableError)
        self.assertFalse(session._thread.is_alive())

    def test_request_after_close_is_rejected(self):
        playwright = FakePlaywright()
        session = BrowserSession(playwright_factory=lambda: playwright)
        session.close()
        with self.assertRaisesRegex(BrowserUnavailableError, "closed"):
            session.request("GET", "https://animepahe.pw/")

    def test_browser_fetch_failures_become_actionable_errors(self):
        playwright = FakePlaywright()
        playwright.browser.context.request.error = RuntimeError("network down")
        session = BrowserSession(playwright_factory=lambda: playwright)
        try:
            with self.assertRaisesRegex(InvalidDownloadResponse, "browser request failed"):
                session.request("GET", "https://animepahe.pw/api?m=search")
        finally:
            session.close()

    def test_missing_playwright_is_actionable(self):
        def missing_playwright():
            raise ImportError("No module named playwright")

        session = BrowserSession(playwright_factory=missing_playwright)
        try:
            with self.assertRaisesRegex(BrowserUnavailableError, "playwright install chromium"):
                session.request("GET", "https://animepahe.pw/api?m=search")
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
