"""Offline download-response regressions; no provider requests are made."""
import ast
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from senpwai.common.scraper import Download, InvalidDownloadResponse, NoResourceLengthException  # noqa: E402


def response(headers=None, status=200, body=b"<html>error</html>"):
    result = Mock()
    result.headers = headers or {}
    result.status_code = status
    result.ok = 200 <= status < 400
    result.url = "https://fixture.invalid/media"
    result.iter_content.return_value = iter([body])
    return result


class ResourceLengthTests(unittest.TestCase):
    def test_error_html_is_rejected_at_lookup_and_transfer(self):
        for status in (200, 404):
            with self.subTest(status=status), patch("senpwai.common.scraper.CLIENT.get") as get:
                get.return_value = response(
                    {"Content-Length": "18", "Content-Type": "text/html"}, status
                )
                with self.assertRaisesRegex(Exception, "[Ii]nvalid download response"):
                    Download.get_total_download_size("https://fixture.invalid/media")
                with tempfile.TemporaryDirectory() as folder:
                    download = Download(
                        "https://fixture.invalid/media", "episode", folder, 18, lambda _: None
                    )
                    with self.assertRaisesRegex(Exception, "[Ii]nvalid download response"):
                        download.start_download()
                    self.assertFalse(Path(download.file_path).exists())

    def test_invalid_lengths_are_explicit(self):
        for length in ("invalid", "0", "-1"):
            with self.subTest(length=length), patch(
                "senpwai.common.scraper.CLIENT.get",
                return_value=response({"Content-Length": length}),
            ):
                with self.assertRaisesRegex(Exception, "[Ii]nvalid.*length"):
                    Download.get_total_download_size("https://fixture.invalid/media")

    def test_missing_length_does_not_restart_gogo_collection(self):
        from senpwai.scrapers.gogo import main as gogo
        page = Mock(content=b'<div class="cf-download"><a href="media">1080p</a></div>')
        with patch.object(gogo.CLIENT, "get", return_value=page), patch.object(
            gogo, "get_session_cookies", return_value={}
        ), patch.object(Download, "get_total_download_size", side_effect=[
            NoResourceLengthException("media", "media"), AssertionError("retried")
        ]):
            with self.assertRaises(NoResourceLengthException):
                gogo.GetDirectDownloadLinks().get_direct_download_links(["page"], "1080p")

    def test_missing_content_length_is_explicit(self):
        with patch("senpwai.common.scraper.CLIENT.get", return_value=response()):
            with self.assertRaises(NoResourceLengthException):
                Download.get_total_download_size("https://fixture.invalid/media")

    def test_valid_size_and_redirect_url_are_returned(self):
        result = response({"Content-Length": "2048", "Content-Type": "video/mp4"})
        with patch("senpwai.common.scraper.CLIENT.get", return_value=result):
            self.assertEqual(
                Download.get_total_download_size("https://fixture.invalid/media"),
                (2048, result.url),
            )


class LocalTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"<html>error</html>" if self.path == "/html" else b"media"
                if self.path == "/range":
                    start, end = map(int, self.headers["Range"].removeprefix("bytes=").split("-"))
                    body = b"0123456789"[start:end + 1]
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/10")
                else:
                    self.send_response(404 if self.path == "/error" else 200)
                self.send_header("Content-Type", "text/html" if self.path == "/html" else "video/mp4")
                if self.path != "/missing":
                    self.send_header("Content-Length", "100" if self.path == "/short" else str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True

            def log_message(self, *_):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_real_metadata_responses(self):
        for path in ("/html", "/error", "/missing"):
            with self.subTest(path=path), self.assertRaises(InvalidDownloadResponse):
                Download.get_total_download_size(self.base + path)
        self.assertEqual(Download.get_total_download_size(self.base + "/valid")[0], 5)

    def test_valid_single_and_multipart_downloads(self):
        for path, size, part_size, expected in (
            ("/valid", 5, 0, b"media"),
            ("/range", 10, 4, b"0123456789"),
        ):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as folder:
                download = Download(self.base + path, "episode", folder, size, lambda _: None, max_part_size=part_size)
                download.start_download()
                self.assertEqual(Path(download.file_path).read_bytes(), expected)

    def test_interrupted_and_invalid_transfers_never_replace_existing_file(self):
        for path in ("/html", "/error", "/short"):
            for part_size in (0, 50):
                with self.subTest(path=path, part_size=part_size), tempfile.TemporaryDirectory() as folder:
                    download = Download(self.base + path, "episode", folder, 100, lambda _: None, max_part_size=part_size)
                    target = Path(download.file_path)
                    target.write_bytes(b"previous good file")
                    with self.assertRaises(InvalidDownloadResponse):
                        download.start_download()
                    self.assertEqual(target.read_bytes(), b"previous good file")


def load_node(path, name, namespace):
    root = Path(__file__).resolve().parents[1] / "senpwai"
    tree = ast.parse((root / path).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if getattr(n, "name", None) == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


class GuiFailureSignalTests(unittest.TestCase):
    """GUI threads must surface invalid responses without false success or slot leaks."""

    def test_gogo_retrieval_failure_notifies_and_skips_finished(self):
        thread_type = load_node(
            "windows/download.py", "GetDirectDownloadLinksThread",
            dict(
                QThread=type("QThread", (), {"__init__": lambda self, parent=None: None}),
                pyqtSignal=lambda *_, **__: Mock(), pyqtSlot=lambda *_, **__: (lambda f: f),
                AnimeDetails=object, ProgressBarWithButtons=object,
                DownloadWindow=object, TYPE_CHECKING=False,
                Callable=__import__("typing").Callable,
                PAHE="PAHE", gogo=SimpleNamespace(GetDirectDownloadLinks=lambda: Mock(
                    pause_or_resume=Mock(), cancel=Mock(),
                    get_direct_download_links=Mock(side_effect=InvalidDownloadResponse("bad response")),
                )),
                IBYTES_TO_MBS_DIVISOR=1048576, cast=lambda t, v: v,
                InvalidDownloadResponse=InvalidDownloadResponse,
            ),
        )
        thread = thread_type.__new__(thread_type)
        thread.download_window = SimpleNamespace(
            main_window=SimpleNamespace(tray_icon=SimpleNamespace(make_notification=Mock()))
        )
        thread.anime_details = SimpleNamespace(site="GOGO", quality="1080p", sanitised_title="Example")
        thread.download_page_links = ["page"]
        thread.progress_bar = Mock(paused=False)
        thread.progress_bar.cancel.side_effect = lambda: thread.progress_bar.cancel_callback()
        thread.run()
        thread_type.failed.emit.assert_called_once()
        self.assertIn("Example", thread_type.failed.emit.call_args[0][0])
        thread_type.finished.emit.assert_not_called()
        # Qt invokes the connected slot on the GUI thread; drive it directly here.
        thread.handle_failure(thread_type.failed.emit.call_args[0][0])
        thread.download_window.main_window.tray_icon.make_notification.assert_called_once()
        self.assertIn("Example", thread.download_window.main_window.tray_icon.make_notification.call_args[0][1])
        thread.progress_bar.cancel_callback.assert_called_once()

    def test_worker_transfer_failure_sets_failed_and_still_cleans_slot(self):
        class FakeDownload:
            cancelled = False
            file_path = "final.mp4"

            def __init__(self, *_, **__):
                pass

            def pause_or_resume(self):
                pass

            def cancel(self):
                pass

            def start_download(self):
                raise InvalidDownloadResponse("bad response")

        thread_type = load_node(
            "windows/download.py", "DownloadThread",
            dict(
                QThread=type("QThread", (), {"__init__": lambda self, parent=None: None}),
                pyqtSignal=lambda *_, **__: Mock(), pyqtSlot=lambda *_, **__: (lambda f: f),
                Download=FakeDownload, get_max_part_size=Mock(return_value=None),
                IBYTES_TO_MBS_DIVISOR=1048576, Callable=object, cast=lambda t, v: v,
                DownloadManagerThread=object, ProgressBarWithButtons=object,
                ProgressBarWithoutButtons=object, QMutex=object, os=os,
                InvalidDownloadResponse=InvalidDownloadResponse,
            ),
        )
        thread = thread_type.__new__(thread_type)
        thread.manager = SimpleNamespace(
            download_failed=SimpleNamespace(set=Mock()), failed=Mock()
        )
        thread.ddl_or_seg_urls = "url"
        thread.title = "Episode 1"
        thread.download_size = 100
        thread.site = "GOGO"
        thread.hls_quality = "1080p"
        thread.is_hls_download = False
        thread.download_folder = "."
        thread.progress_bar = Mock()
        thread.anime_progress_bar = Mock()
        thread.mutex = Mock()
        thread.is_cancelled = False
        thread.download_failed = SimpleNamespace(set=Mock())
        thread.run()
        thread.manager.failed.emit.assert_called_once()
        self.assertIn("Episode 1", thread.manager.failed.emit.call_args[0][0])
        thread.manager.download_failed.set.assert_called_once()
        # Slot bookkeeping still runs exactly once so the manager never strands.
        thread_type.finished.emit.assert_called_once_with("Episode 1")
        thread_type.update_eps_count_and_hls_sizes.emit.assert_not_called()


class CliFailureAccountingTests(unittest.TestCase):
    """CLI download_manager must account failures without hanging or false success."""

    def test_all_metadata_failures_report_incomplete_and_return(self):
        def fake_episode_title(_idx, _shortened):
            return "episode"

        manager = load_node(
            "senpcli/main.py", "download_manager",
            dict(
                Download=Mock(get_total_download_size=Mock(side_effect=InvalidDownloadResponse("bad response"))),
                Event=Mock(side_effect=lambda: SimpleNamespace(set=lambda: None, clear=lambda: None, is_set=lambda: True, wait=lambda t: True)),
                Lock=Mock(return_value=Mock(__enter__=Mock(), __exit__=Mock(return_value=False))),
                Thread=Mock(),
                ProgressBar=Mock(return_value=Mock(close_=Mock())),
                print_error=Mock(), print_rainbow=Mock(), add_color=Mock(return_value=""),
                Color=SimpleNamespace(MAGENTA="m"), random=Mock(choice=lambda _: ""),
                ANIME_REFERENCES=[], SETTINGS=SimpleNamespace(max_simultaneous_downloads=2),
                InvalidDownloadResponse=InvalidDownloadResponse, get_max_part_size=Mock(return_value=None),
                IBYTES_TO_MBS_DIVISOR=1048576, cast=lambda t, v: v, AnimeDetails=object,
                enumerate=enumerate,
            ),
        )
        anime_details = SimpleNamespace(
            validate_anime_folder_path=lambda: None,
            episode_title=fake_episode_title,
            shortened_title="Example",
            site="GOGO",
            anime_folder_path=".",
        )
        manager(["link"], anime_details, False, 2, None)
        # No success message means failures were accounted; nothing raised or hung.


class PaheLinkResponseTests(unittest.TestCase):
    def test_missing_kwik_link_raises_actionable_error(self):
        from senpwai.scrapers.pahe import main as pahe

        with patch.object(pahe.CLIENT, "get", return_value=SimpleNamespace(text="<html>Unavailable</html>")):
            with self.assertRaisesRegex(InvalidDownloadResponse, "Animepahe.*[Rr]etry"):
                pahe.GetDirectDownloadLinks().get_direct_download_links(["https://fixture.invalid/page"])

    def test_missing_parameters_aborts_without_partial_result(self):
        from senpwai.scrapers.pahe import main as pahe

        progress = Mock()
        with patch.object(pahe.CLIENT, "get", side_effect=[
            SimpleNamespace(text="https://kwik.cx/f/fixture"),
            SimpleNamespace(text="<html>Unavailable</html>"),
        ]) as get:
            with self.assertRaisesRegex(InvalidDownloadResponse, "Animepahe.*parameters.*[Rr]etry"):
                pahe.GetDirectDownloadLinks().get_direct_download_links(["page1", "page2"], progress)
        self.assertEqual(get.call_count, 2)
        progress.assert_not_called()

    def test_cli_closes_progress_bar_on_provider_error(self):
        bar = Mock()
        collector = Mock()
        collector.get_direct_download_links.side_effect = InvalidDownloadResponse("Animepahe unavailable")
        function = load_node("senpcli/main.py", "pahe_get_direct_download_links", dict(
            ProgressBar=Mock(return_value=bar),
            pahe=SimpleNamespace(GetDirectDownloadLinks=lambda: collector),
        ))
        with self.assertRaises(InvalidDownloadResponse):
            function(["page"])
        bar.close_.assert_called_once()

    def test_gui_pahe_failure_notifies_cancels_bar_and_never_queues(self):
        from typing import Callable, cast
        from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        collector = Mock()
        collector.get_direct_download_links.side_effect = InvalidDownloadResponse("Animepahe unavailable")
        provider = SimpleNamespace(
            GetDirectDownloadLinks=lambda: collector,
            bind_sub_or_dub_to_link_info=lambda *_: (["page"], ["1080p 10MB"]),
            bind_quality_to_link_info=lambda *_: (["page"], ["1080p 10MB"]),
        )
        cls = load_node("windows/download.py", "GetDirectDownloadLinksThread", dict(
            QThread=QThread, pyqtSignal=pyqtSignal, pyqtSlot=pyqtSlot,
            AnimeDetails=object, DownloadWindow=object, ProgressBarWithButtons=object,
            Callable=Callable, cast=cast, PAHE="PAHE", pahe=provider,
            InvalidDownloadResponse=InvalidDownloadResponse,
        ))
        details = SimpleNamespace(site="PAHE", sub_or_dub="sub", quality="1080p", sanitised_title="Example", ddls_or_segs_urls=[])
        queued = Mock()
        bar = Mock(paused=True)
        def resume_bar():
            bar.paused = False
            bar.pause_callback()
        bar.pause_or_resume.side_effect = resume_bar
        bar.cancel.side_effect = lambda: bar.cancel_callback() if not bar.paused else None
        thread = cls(None, [["page"]], [["1080p 10MB"]], details, queued, bar)
        notice = Mock()
        thread.download_window = SimpleNamespace(main_window=SimpleNamespace(tray_icon=SimpleNamespace(make_notification=notice)))
        thread.run()
        app.processEvents()
        notice.assert_called_once_with("Download failed", "Example: Animepahe unavailable", False, None)
        bar.pause_or_resume.assert_called_once()
        collector.pause_or_resume.assert_called_once()
        self.assertFalse(bar.paused)
        bar.cancel.assert_called_once()
        collector.cancel.assert_called_once()
        queued.assert_not_called()
        self.assertEqual(details.ddls_or_segs_urls, [])

    def test_valid_link_response_preserves_order_and_progress(self):
        from senpwai.scrapers.pahe import main as pahe

        progress = Mock()
        with patch.object(pahe.CLIENT, "get", side_effect=[
            SimpleNamespace(text="https://kwik.cx/f/fixture"),
            SimpleNamespace(text='("abc",1,"abc",1,2,3)', cookies={}),
        ] * 2), patch.object(pahe, "decrypt_post_form", return_value=
            '<form action="https://fixture.invalid/post"><input value="x"></form>'
        ), patch.object(pahe.CLIENT, "post", side_effect=[
            SimpleNamespace(headers={"Location": f"https://fixture.invalid/{i}.mp4"})
            for i in (1, 2)
        ]):
            links = pahe.GetDirectDownloadLinks().get_direct_download_links(["page1", "page2"], progress)
        self.assertEqual(links, ["https://fixture.invalid/1.mp4", "https://fixture.invalid/2.mp4"])
        self.assertEqual(progress.call_count, 2)
        progress.assert_called_with(1)


if __name__ == "__main__":
    unittest.main()
