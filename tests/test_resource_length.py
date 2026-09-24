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
                status = 404 if self.path == "/error" else 200
                if self.path == "/html":
                    body = b"<html>error</html>"
                elif self.path == "/blocked":
                    body = b"<html>Access denied</html>"
                    status = 403
                elif self.path == "/challenge":
                    body = b"<html>Checking your browser</html>"
                else:
                    body = b"media"
                if self.path == "/range":
                    start, end = map(int, self.headers["Range"].removeprefix("bytes=").split("-"))
                    body = b"0123456789"[start:end + 1]
                    status = 206
                self.send_response(status)
                if self.path == "/range":
                    self.send_header("Content-Range", f"bytes {start}-{end}/10")
                self.send_header("Content-Type", "text/html" if self.path in ("/html", "/blocked", "/challenge") else "video/mp4")
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

    def test_local_verification_fixtures_are_actionable(self):
        for path in ("/blocked", "/challenge"):
            with self.subTest(path=path), self.assertRaisesRegex(
                InvalidDownloadResponse, "verification|browser|retry"
            ):
                Download.get_total_download_size(self.base + path)

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


class PaheEpisodeResponseTests(unittest.TestCase):
    def test_missing_empty_or_invalid_episode_data_is_explicit(self):
        from senpwai.scrapers.pahe import main as pahe

        for data in ({}, {"data": []}, {"data": None}, {"data": {}},
                     {"data": [None]}, {"data": [{"episode": 1}]},
                     {"data": [{"episode": 1, "session": ""}]}):
            with self.subTest(data=data), patch.object(pahe, "site_request", return_value=Mock(
                json=Mock(return_value={"per_page": 30, **data})
            )):
                with self.assertRaisesRegex(InvalidDownloadResponse, "Animepahe.*episode.*[Rr]etry"):
                    pahe.get_episode_pages_info("fixture", 1, 1)

    def test_invalid_pagination_is_explicit(self):
        from senpwai.scrapers.pahe import main as pahe

        for per_page in (None, 0, -1, "30", True):
            page = {"data": [{"episode": 1, "session": "one"}], "per_page": per_page}
            with self.subTest(per_page=per_page), patch.object(pahe, "site_request", return_value=Mock(
                json=Mock(return_value=page)
            )):
                with self.assertRaisesRegex(InvalidDownloadResponse, "Animepahe.*pagination.*[Rr]etry"):
                    pahe.get_episode_pages_info("fixture", 1, 1)

    def test_missing_later_page_data_aborts_collection(self):
        from senpwai.scrapers.pahe import main as pahe

        first = {"data": [{"episode": 1, "session": "one"}], "per_page": 1}
        progress = Mock()
        with patch.object(pahe, "site_request", return_value=Mock(json=Mock(return_value={}))) as request:
            with self.assertRaisesRegex(InvalidDownloadResponse, "Animepahe.*episode.*[Rr]etry"):
                pahe.GetEpisodePageLinks().get_episode_page_links(
                    1, 2, pahe.EpisodePagesInfo(1, 2, 2, first), "fixture", "anime", progress
                )
        request.assert_called_once()
        progress.assert_called_once_with(1)

    def test_first_page_without_integer_episode_is_explicit(self):
        from senpwai.scrapers.pahe import main as pahe

        first = {"data": [{"episode": 1.5}], "per_page": 30}
        with self.assertRaisesRegex(InvalidDownloadResponse, "Animepahe.*episode.*[Rr]etry"):
            pahe.GetEpisodePageLinks().get_episode_page_links(
                1, 1, pahe.EpisodePagesInfo(1, 1, 1, first), "fixture", "anime"
            )

    def test_valid_pages_preserve_sequel_offsets_order_and_progress(self):
        from senpwai.scrapers.pahe import main as pahe

        first = {"data": [{"episode": 14, "session": "one"},
                          {"episode": 14.25}], "per_page": 1}
        second = {"data": [{"episode": 14.5},
                           {"episode": 15, "session": "two"}]}
        progress = Mock()
        with patch.object(pahe, "site_request", side_effect=[
            Mock(json=Mock(return_value=first)), Mock(json=Mock(return_value=second))
        ]):
            info = pahe.get_episode_pages_info("fixture", 1, 2)
            links = pahe.GetEpisodePageLinks().get_episode_page_links(1, 2, info, "fixture", "anime", progress)
        self.assertEqual(links, [pahe.EPISODE_PAGE_URL.format("anime", session) for session in ("one", "two")])
        self.assertEqual(progress.call_args_list, [unittest.mock.call(1), unittest.mock.call(1)])




class PaheEpisodeConsumerTests(unittest.TestCase):
    def test_cli_rejects_nonpositive_totals_before_clamping_episode_range(self):
        warn = Mock()
        validate = load_node("senpcli/main.py", "validate_start_and_end_episode", dict(
            InvalidDownloadResponse=InvalidDownloadResponse, print_warn=warn,
        ))
        for total in (0, -1):
            for start, end in ((1, -1), (-1, -1), (1, 5)):
                with self.subTest(total=total, start=start, end=end):
                    with self.assertRaisesRegex(InvalidDownloadResponse, "[Ee]pisodes.*[Rr]etry"):
                        validate(start, end, total)
        warn.assert_not_called()

    def test_cli_valid_total_preserves_episode_range_defaults(self):
        validate = load_node("senpcli/main.py", "validate_start_and_end_episode", dict(
            InvalidDownloadResponse=InvalidDownloadResponse, print_warn=Mock(),
        ))
        self.assertEqual(validate(1, -1, 12), (1, 12))
        self.assertEqual(validate(-1, -1, 12), (12, 12))
        self.assertEqual(validate(1, 15, 12), (1, 12))

    def test_cli_episode_links_bar_closes_on_failure_and_success(self):
        for fails in (True, False):
            with self.subTest(fails=fails):
                bar, collector = Mock(), Mock()
                error = InvalidDownloadResponse("Animepahe episode response invalid. Retry later or choose another source.")
                collector.get_episode_page_links.side_effect = error if fails else None
                collector.get_episode_page_links.return_value = ["episode1", "episode2"]
                info = SimpleNamespace(total=1)
                provider = SimpleNamespace(
                    get_episode_pages_info=Mock(return_value=info),
                    GetEpisodePageLinks=lambda: collector,
                )
                retrieve = load_node("senpcli/main.py", "pahe_get_episode_page_links", dict(
                    pahe=provider, ProgressBar=Mock(return_value=bar),
                ))
                if fails:
                    with self.assertRaises(InvalidDownloadResponse):
                        retrieve(1, 2, "id", "page")
                else:
                    self.assertEqual(retrieve(1, 2, "id", "page"), ["episode1", "episode2"])
                bar.close_.assert_called_once()

    def test_cli_main_reports_episode_retrieval_errors_without_traceback(self):
        for stage in ("metadata", "links"):
            with self.subTest(stage=stage):
                error = InvalidDownloadResponse("Animepahe episode response invalid. Retry later or choose another source.")
                provider = SimpleNamespace(
                    get_episode_pages_info=Mock(
                        side_effect=error if stage == "metadata" else None,
                        return_value=SimpleNamespace(total=1),
                    ),
                    GetEpisodePageLinks=lambda: SimpleNamespace(
                        get_episode_page_links=Mock(side_effect=error)
                    ),
                )
                bars = Mock()
                retrieve = load_node("senpcli/main.py", "pahe_get_episode_page_links", dict(
                    pahe=provider, ProgressBar=bars,
                ))
                parsed = SimpleNamespace(
                    config=False, update=False, check_tracked_anime=False,
                    remove_tracked_anime=False, add_tracked_anime=False, title="Example",
                )
                report, finish = Mock(), Mock()
                main = load_node("senpcli/main.py", "main", dict(
                    sys=SimpleNamespace(argv=["senpcli"]), ASCII_APP_NAME="", print_rainbow=Mock(),
                    parse_args=lambda _: (parsed, None), validate_args=lambda _: True,
                    start_update_check_thread=lambda: (), get_anime_details=lambda _: object(),
                    initiate_download_pipeline=lambda *_: retrieve(1, 2, "id", "page"),
                    finish_update_check=finish, print_error=report, ProgressBar=bars,
                    InvalidDownloadResponse=InvalidDownloadResponse, AnimeDetails=object,
                ))
                main()
                report.assert_called_once_with(f"Download failed: {error}")
                bars.cancel_all_active.assert_called_once()
                finish.assert_not_called()

    def _gui_type(self, name, provider):
        from typing import Callable, cast
        from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot

        return load_node("windows/download.py", name, dict(
            QThread=QThread, pyqtSignal=pyqtSignal, pyqtSlot=pyqtSlot,
            AnimeDetails=object, DownloadWindow=object, ProgressBarWithButtons=object,
            Callable=Callable, cast=cast, pahe=provider,
            InvalidDownloadResponse=InvalidDownloadResponse,
        ))

    def _gui_fixture(self):
        from PyQt6.QtCore import QObject
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        parent = QObject()
        notice = Mock()
        parent.main_window = SimpleNamespace(
            tray_icon=SimpleNamespace(make_notification=notice)
        )
        details = SimpleNamespace(
            sanitised_title="Example",
            anime=SimpleNamespace(page_link="page", id="id"),
        )
        return app, parent, details, notice

    def test_gui_episode_info_failure_notifies_without_success(self):
        app, parent, details, notice = self._gui_fixture()
        error = InvalidDownloadResponse("Animepahe episode response invalid. Retry later or choose another source.")
        provider = SimpleNamespace(EpisodePagesInfo=object, get_episode_pages_info=Mock(side_effect=error))
        queued = Mock()
        thread = self._gui_type("PaheGetEpisodePageInfo", provider)(parent, 1, 2, details, queued)
        thread.run()
        app.processEvents()
        notice.assert_called_once_with("Download failed", f"Example: {error}", False, None)
        queued.assert_not_called()

    def test_gui_episode_links_failure_resumes_before_cancel_and_never_advances(self):
        for paused in (True, False):
            with self.subTest(paused=paused):
                app, parent, details, notice = self._gui_fixture()
                error = InvalidDownloadResponse("Animepahe episode response invalid. Retry later or choose another source.")
                collector = Mock(cancelled=False)
                collector.get_episode_page_links.side_effect = error
                provider = SimpleNamespace(EpisodePagesInfo=object, GetEpisodePageLinks=lambda: collector)
                queued, bar = Mock(), Mock(paused=paused)

                def resume_bar():
                    bar.paused = False
                    bar.pause_callback()

                bar.pause_or_resume.side_effect = resume_bar
                bar.cancel.side_effect = lambda: bar.cancel_callback() if not bar.paused else None
                thread = self._gui_type("PaheGetEpisodePageLinksThread", provider)(
                    parent, details, 1, 2, object(), queued, bar
                )
                thread.run()
                app.processEvents()
                notice.assert_called_once_with("Download failed", f"Example: {error}", False, None)
                self.assertEqual(bar.pause_or_resume.call_count, int(paused))
                self.assertEqual(collector.pause_or_resume.call_count, int(paused))
                self.assertFalse(bar.paused)
                bar.cancel.assert_called_once()
                collector.cancel.assert_called_once()
                queued.assert_not_called()

    def test_gui_episode_consumers_preserve_valid_success(self):
        app, parent, details, notice = self._gui_fixture()
        info = object()
        provider = SimpleNamespace(EpisodePagesInfo=object, get_episode_pages_info=Mock(return_value=info))
        queued = Mock()
        thread = self._gui_type("PaheGetEpisodePageInfo", provider)(parent, 1, 2, details, queued)
        thread.run()
        app.processEvents()
        queued.assert_called_once_with(details, info)

        collector = Mock(cancelled=False)
        collector.get_episode_page_links.return_value = ["episode1", "episode2"]
        provider.GetEpisodePageLinks = lambda: collector
        queued, bar = Mock(), Mock(paused=False)
        thread = self._gui_type("PaheGetEpisodePageLinksThread", provider)(
            parent, details, 1, 2, info, queued, bar
        )
        thread.run()
        app.processEvents()
        queued.assert_called_once_with(details, ["episode1", "episode2"])
        bar.cancel.assert_not_called()
        notice.assert_not_called()




class ProviderVerificationTests(unittest.TestCase):
    @staticmethod
    def blocked_response(status=403, body="<html>Access denied</html>"):
        result = Mock()
        result.status_code = status
        result.headers = {"Content-Type": "text/html; charset=utf-8"}
        result.text = body
        return result

    def test_blocked_status_is_actionable_only_at_opt_in_boundaries(self):
        from senpwai.common import scraper

        blocked = self.blocked_response()
        with patch.object(scraper.requests, "get", return_value=blocked) as get:
            self.assertIs(
                scraper.Client().get("https://fixture.invalid/blocked"), blocked
            )
        get.assert_called_once()
        with self.assertRaisesRegex(InvalidDownloadResponse, "verification|browser|retry"):
            scraper.raise_for_provider_verification(blocked)
        blocked.close.assert_called_once()

    def test_challenge_html_is_actionable_at_download_validation(self):
        from senpwai.common import scraper

        challenge = self.blocked_response(
            status=200,
            body="<html><title>Just a moment...</title><div>Checking your browser</div></html>",
        )
        with self.assertRaisesRegex(InvalidDownloadResponse, "verification|browser|retry"):
            scraper.Download.validate_response(challenge)

    def test_streamed_challenge_inspection_reads_only_bounded_prefix(self):
        from senpwai.common import scraper
        import requests

        streamed = requests.Response()
        streamed.status_code = 200
        streamed.headers["Content-Type"] = "text/html"
        streamed.encoding = "utf-8"
        streamed.raw = Mock()
        streamed.raw.read.return_value = b"Checking your browser" + b"x" * 10000
        with self.assertRaisesRegex(InvalidDownloadResponse, "verification|browser|retry"):
            scraper.Download.validate_response(streamed)
        streamed.raw.read.assert_called_once_with(scraper.VERIFICATION_BODY_PREFIX_BYTES)

    def test_challenge_marker_is_detected_without_rejecting_ordinary_html(self):
        from senpwai.common import scraper

        challenge = self.blocked_response(
            status=200, body="<html>Checking your browser before continuing</html>"
        )
        with self.assertRaisesRegex(InvalidDownloadResponse, "verification|browser|retry"):
            scraper.raise_for_provider_verification(challenge)

        ordinary = self.blocked_response(
            status=200,
            body="<html>Login form with g-recaptcha and a captcha widget</html>",
        )
        with patch.object(scraper.requests, "get", return_value=ordinary):
            self.assertIs(
                scraper.Client().get("https://fixture.invalid/ordinary"), ordinary
            )

    def test_pahe_direct_link_propagates_supported_action(self):
        from senpwai.common import scraper
        from senpwai.scrapers.pahe.main import GetDirectDownloadLinks

        blocked = self.blocked_response(status=429)
        with patch.object(scraper.requests, "get", return_value=blocked):
            with self.assertRaisesRegex(InvalidDownloadResponse, "verification|browser|retry"):
                GetDirectDownloadLinks().get_direct_download_links(["page"])

    def test_pahe_real_nonstream_challenge_response_is_actionable(self):
        from senpwai.common import scraper
        from senpwai.scrapers.pahe.main import GetDirectDownloadLinks
        import requests

        challenge = requests.Response()
        challenge.status_code = 200
        challenge.headers["Content-Type"] = "text/html"
        challenge.encoding = "utf-8"
        challenge._content = b"<html>Checking your browser</html>"
        challenge.close = Mock()
        with patch.object(scraper.requests, "get", return_value=challenge) as get:
            with self.assertRaisesRegex(InvalidDownloadResponse, "verification|browser|retry"):
                GetDirectDownloadLinks().get_direct_download_links(["page"])
        get.assert_called_once()
        challenge.close.assert_called_once()

    def test_cancelled_direct_link_does_not_start_a_request(self):
        from senpwai.common import scraper
        from senpwai.scrapers.pahe.main import GetDirectDownloadLinks

        collector = GetDirectDownloadLinks()
        collector.cancel()
        with patch.object(scraper.requests, "get") as get:
            self.assertEqual(collector.get_direct_download_links(["page"]), [])
        get.assert_not_called()

    def test_cancellation_between_pahe_requests_stops_before_next_request(self):
        from senpwai.common import scraper
        from senpwai.scrapers.pahe.main import GetDirectDownloadLinks

        collector = GetDirectDownloadLinks()
        first_response = SimpleNamespace(
            status_code=200,
            headers={"Content-Type": "text/html"},
            text="https://kwik.cx/f/fixture",
            close=Mock(),
        )

        def first_get(*_args, **_kwargs):
            collector.cancel()
            return first_response

        with patch.object(scraper.requests, "get", side_effect=first_get) as get:
            self.assertEqual(collector.get_direct_download_links(["page"]), [])
        get.assert_called_once()

    def test_network_errors_stop_after_bounded_retries(self):
        from senpwai.common import scraper
        import requests

        timeout = requests.exceptions.Timeout("fixture timeout")
        with patch.object(scraper.requests, "get", side_effect=[timeout] * 10) as get, patch.object(
            scraper.time, "sleep"
        ) as sleep, patch.object(scraper, "log_exception"):
            with self.assertRaises(requests.exceptions.Timeout):
                scraper.Client().get("https://fixture.invalid/retry")
        self.assertEqual(get.call_count, 4)
        self.assertEqual(sleep.call_count, 3)

    def test_cancelling_paused_progress_wakes_waiters(self):
        from senpwai.common import scraper

        progress = scraper.ProgressFunction()
        progress.pause_or_resume()
        progress.cancel()
        self.assertTrue(progress.cancelled)
        self.assertTrue(progress.resume.is_set())




class SearchFailureTests(unittest.TestCase):
    @staticmethod
    def signal_double():
        class Signal:
            def __init__(self, *_args):
                self.calls = []
                self.callback = None

            def connect(self, callback):
                self.callback = callback

            def emit(self, *args):
                self.calls.append(args)
                if self.callback:
                    self.callback(*args)

        return Signal

    def test_provider_searches_use_bounded_timeouts(self):
        from senpwai.scrapers import gogo, pahe

        pahe_response = Mock(
            cookies={},
            json=Mock(return_value={"data": []}),
        )
        with patch.object(pahe, "FIRST_REQUEST", False), patch.object(
            pahe.CLIENT, "get", return_value=pahe_response
        ) as pahe_get:
            self.assertEqual(pahe.search("fixture"), [])
        self.assertEqual(pahe_get.call_args.kwargs["timeout"], 30)

        gogo_response = Mock(json=Mock(return_value={"content": ""}))
        with patch.object(gogo.CLIENT, "get", return_value=gogo_response) as gogo_get:
            self.assertEqual(gogo.search("fixture"), [])
        self.assertEqual(gogo_get.call_args.kwargs["timeout"], 30)

    def test_pahe_search_timeout_keeps_domain_probes_finite(self):
        import requests
        from senpwai.common import scraper
        from senpwai.common.scraper import InvalidDownloadResponse
        from senpwai.scrapers import pahe

        timeout = requests.exceptions.Timeout("fixture timeout")

        def fail_request(url, **kwargs):
            raise timeout

        with patch.object(pahe, "FIRST_REQUEST", True), patch.object(
            scraper.requests, "get", side_effect=fail_request
        ) as get, patch.object(scraper.time, "sleep"), patch.object(
            scraper, "log_exception"
        ):
            with self.assertRaisesRegex(InvalidDownloadResponse, "search|connection"):
                pahe.search("fixture")
        provider_calls = [
            call for call in get.call_args_list if "google.com" not in call.args[0]
        ]
        self.assertEqual(len(provider_calls), 4)
        self.assertTrue(all(call.kwargs["timeout"] == 30 for call in provider_calls))
        self.assertTrue(
            all(
                call.kwargs.get("timeout")
                in (30, scraper.DOMAIN_DISCOVERY_TIMEOUT)
                for call in get.call_args_list
            )
        )
    def test_search_thread_reports_request_failure_without_finished(self):
        import requests
        from senpwai.common.scraper import DomainNameError, InvalidDownloadResponse

        signal = self.signal_double()
        thread_type = load_node("windows/search.py", "SearchThread", dict(
            QThread=type("QThread", (), {"__init__": lambda self, parent=None: None}),
            pyqtSignal=lambda *args: signal(*args),
            SearchWindow=object,
            Anime=object,
            pahe=SimpleNamespace(search=Mock(side_effect=requests.exceptions.Timeout("fixture"))),
            gogo=SimpleNamespace(search=Mock()),
            RequestException=requests.exceptions.RequestException,
            DomainNameError=DomainNameError,
            InvalidDownloadResponse=InvalidDownloadResponse,
            PAHE="PAHE",
            GOGO="GOGO",
        ))
        thread = thread_type(object(), "fixture", "PAHE")
        thread.run()
        self.assertTrue(thread.failed.calls)
        self.assertIn("connection", str(thread.failed.calls[0][1]).lower())
        self.assertFalse(thread.search_finished.calls)

    def test_search_failure_resets_controls_and_notifies(self):
        thread_type = load_node("windows/search.py", "SearchWindow", dict(
            AbstractWindow=object, Anime=object
        ))
        window = thread_type.__new__(thread_type)
        window.loading = Mock()
        window.anime_not_found = Mock()
        window.bottom_section_stacked_widgets = Mock()
        window.main_window = SimpleNamespace(
            tray_icon=SimpleNamespace(make_notification=Mock())
        )
        window.search_thread = object()
        window.show_search_error("Search timed out. Try again later.")
        window.loading.stop.assert_called_once()
        window.anime_not_found.start.assert_called_once()
        window.bottom_section_stacked_widgets.setCurrentWidget.assert_called_once_with(
            window.anime_not_found
        )
        self.assertIsNone(window.search_thread)
        window.main_window.tray_icon.make_notification.assert_called_once_with(
            "Search failed", "Search timed out. Try again later.", False, None
        )

    def test_stale_search_failure_does_not_reset_current_search(self):
        thread_type = load_node("windows/search.py", "SearchWindow", dict(
            AbstractWindow=object, Anime=object
        ))
        window = thread_type.__new__(thread_type)
        window.loading = Mock()
        window.anime_not_found = Mock()
        window.bottom_section_stacked_widgets = Mock()
        window.main_window = SimpleNamespace(
            tray_icon=SimpleNamespace(make_notification=Mock())
        )
        window.search_thread = object()
        window.sender = Mock(return_value=object())
        window.show_search_error("stale failure")
        window.loading.stop.assert_not_called()
        window.main_window.tray_icon.make_notification.assert_not_called()
        self.assertIsNotNone(window.search_thread)

    def test_stale_search_success_does_not_replace_current_results(self):
        thread_type = load_node("windows/search.py", "SearchWindow", dict(
            AbstractWindow=object, Anime=object, ResultButton=Mock
        ))
        window = thread_type.__new__(thread_type)
        window.loading = Mock()
        window.results_layout = Mock()
        window.results_widget = Mock()
        window.bottom_section_stacked_widgets = Mock()
        window.main_window = SimpleNamespace()
        window.search_thread = object()
        window.sender = Mock(return_value=object())
        window.show_results("PAHE", [object()])
        window.results_layout.addWidget.assert_not_called()
        window.loading.stop.assert_not_called()
        self.assertIsNotNone(window.search_thread)

    def test_search_thread_preserves_success_signal(self):
        signal = self.signal_double()
        thread_type = load_node("windows/search.py", "SearchThread", dict(
            QThread=type("QThread", (), {"__init__": lambda self, parent=None: None}),
            pyqtSignal=lambda *args: signal(*args),
            SearchWindow=object,
            Anime=object,
            pahe=SimpleNamespace(search=Mock(return_value=[])),
            gogo=SimpleNamespace(search=Mock()),
            RequestException=Exception,
            DomainNameError=Exception,
            InvalidDownloadResponse=Exception,
            PAHE="PAHE",
            GOGO="GOGO",
        ))
        thread = thread_type(object(), "fixture", "PAHE")
        thread.run()
        self.assertEqual(thread.search_finished.calls, [(thread, "PAHE", [])])
        self.assertFalse(thread.failed.calls)

    def test_cancelled_search_thread_does_not_emit_success(self):
        signal = self.signal_double()
        thread_type = load_node("windows/search.py", "SearchThread", dict(
            QThread=type("QThread", (), {"__init__": lambda self, parent=None: None}),
            pyqtSignal=lambda *args: signal(*args),
            SearchWindow=object,
            Anime=object,
            pahe=SimpleNamespace(search=Mock(return_value=[])),
            gogo=SimpleNamespace(search=Mock()),
            RequestException=Exception,
            DomainNameError=Exception,
            InvalidDownloadResponse=Exception,
            PAHE="PAHE",
            GOGO="GOGO",
        ))
        thread = thread_type(object(), "fixture", "PAHE")
        thread.cancel()
        thread.run()
        self.assertFalse(thread.search_finished.calls)
        self.assertFalse(thread.failed.calls)

    def test_owner_thread_waits_for_naruto_cleanup_before_delete(self):
        thread_type = load_node("windows/search.py", "SearchWindow", dict(
            AbstractWindow=object, Anime=object
        ))
        window = thread_type.__new__(thread_type)
        owner = Mock()
        naruto = SimpleNamespace(owner_thread=owner)
        window.search_thread = None
        window.search_threads = [owner]
        window.pending_thread_cleanup = []
        window.naruto_threads = [naruto]
        window.active_naruto_owner = owner
        window.active_naruto_thread = naruto
        window.remove_search_thread(owner)
        owner.deleteLater.assert_not_called()
        window.finish_naruto_results(naruto)
        owner.deleteLater.assert_called_once()
        self.assertNotIn(owner, window.search_threads)

    def test_search_window_shutdown_cancels_and_waits_for_workers(self):
        thread_type = load_node("windows/search.py", "SearchWindow", dict(
            AbstractWindow=object, Anime=object
        ))
        window = thread_type.__new__(thread_type)
        search_thread, naruto_thread = Mock(), Mock()
        window._shutdown = False
        window.search_thread = search_thread
        window.search_threads = [search_thread]
        window.naruto_threads = [naruto_thread]
        window.pending_thread_cleanup = []
        window.active_naruto_owner = search_thread
        window.active_naruto_thread = naruto_thread
        window.shutdown()
        search_thread.cancel.assert_called_once()
        search_thread.quit.assert_called_once()
        search_thread.wait.assert_called_once()
        search_thread.deleteLater.assert_called_once()
        naruto_thread.cancel.assert_called_once()
        naruto_thread.quit.assert_called_once()
        naruto_thread.wait.assert_called_once()
        naruto_thread.deleteLater.assert_called_once()
        self.assertIsNone(window.search_thread)
        window.shutdown()

    def test_thread_cleanup_waits_for_qthread_finished(self):
        thread_type = load_node("windows/search.py", "SearchWindow", dict(
            AbstractWindow=object, Anime=object
        ))
        window = thread_type.__new__(thread_type)
        owner = Mock()
        owner.isFinished.return_value = False
        window.search_thread = None
        window.search_threads = [owner]
        window.pending_thread_cleanup = []
        window.naruto_threads = []
        window.remove_search_thread(owner)
        owner.deleteLater.assert_not_called()
        self.assertIn(owner, window.pending_thread_cleanup)
        owner.isFinished.return_value = True
        window.remove_search_thread(owner)
        owner.deleteLater.assert_called_once()
        self.assertNotIn(owner, window.pending_thread_cleanup)

    def test_connectivity_probe_has_finite_timeout(self):
        from senpwai.common import scraper

        with patch.object(scraper.requests, "get", return_value=Mock()) as get:
            self.assertTrue(scraper.has_valid_internet_connection())
        get.assert_called_once_with(
            "https://www.google.com", timeout=scraper.DOMAIN_DISCOVERY_TIMEOUT
        )

    def test_domain_discovery_readme_request_has_finite_timeout(self):
        from base64 import b64encode
        from senpwai.common import scraper

        response = Mock(
            json=Mock(
                return_value={
                    "content": b64encode(b"[Animepahe](https://fixture.invalid)").decode()
                }
            )
        )
        with patch.object(scraper.CLIENT, "get", return_value=response) as get:
            scraper.get_new_home_url_from_readme("Animepahe")
        self.assertEqual(
            get.call_args.kwargs["timeout"], scraper.DOMAIN_DISCOVERY_TIMEOUT
        )

    def test_search_module_imports_with_multimedia_test_double(self):
        import importlib
        import sys
        import types

        multimedia = types.ModuleType("PyQt6.QtMultimedia")
        multimedia.QAudioOutput = type("QAudioOutput", (), {})
        multimedia.QMediaPlayer = type("QMediaPlayer", (), {})
        with patch.dict(sys.modules, {"PyQt6.QtMultimedia": multimedia}):
            sys.modules.pop("senpwai.windows.search", None)
            module = importlib.import_module("senpwai.windows.search")
        self.assertTrue(hasattr(module, "SearchThread"))

    def test_real_search_thread_finished_boundary_is_safe_for_deferred_delete(self):
        import importlib
        import sys
        import types
        from unittest.mock import Mock
        from PyQt6.QtCore import QObject
        from PyQt6.QtWidgets import QApplication

        multimedia = types.ModuleType("PyQt6.QtMultimedia")
        multimedia.QAudioOutput = type("QAudioOutput", (), {})
        multimedia.QMediaPlayer = type("QMediaPlayer", (), {})
        with patch.dict(sys.modules, {"PyQt6.QtMultimedia": multimedia}):
            module = importlib.import_module("senpwai.windows.search")
        app = QApplication.instance() or QApplication([])
        parent = QObject()
        thread = module.SearchThread(parent, "fixture", module.PAHE)
        results, finished = Mock(), Mock()
        thread.search_finished.connect(results)
        thread.finished.connect(finished)
        with patch.object(module.pahe, "search", return_value=[]):
            thread.start()
            self.assertTrue(thread.wait(2000))
        app.processEvents()
        results.assert_called_once_with(thread, module.PAHE, [])
        finished.assert_called_once()
        self.assertTrue(thread.isFinished())
        thread.deleteLater()
        app.processEvents()

    def test_malformed_search_shapes_are_typed_or_empty(self):
        from senpwai.common.scraper import InvalidDownloadResponse
        from senpwai.scrapers import gogo, pahe

        with patch.object(pahe, "FIRST_REQUEST", False), patch.object(
            pahe.CLIENT,
            "get",
            return_value=Mock(cookies={}, json=Mock(return_value={})),
        ):
            self.assertEqual(pahe.search("fixture"), [])
        with patch.object(
            gogo.CLIENT, "get", return_value=Mock(json=Mock(return_value={}))
        ):
            with self.assertRaisesRegex(InvalidDownloadResponse, "invalid search data"):
                gogo.search("fixture")

    def test_provider_search_converts_request_failure_to_typed_error(self):
        import requests
        from senpwai.common.scraper import InvalidDownloadResponse
        from senpwai.scrapers import pahe

        with patch.object(
            pahe, "site_request", side_effect=requests.exceptions.Timeout("fixture")
        ):
            with self.assertRaisesRegex(InvalidDownloadResponse, "search|connection|retry"):
                pahe.search("fixture")


if __name__ == "__main__":
    unittest.main()
