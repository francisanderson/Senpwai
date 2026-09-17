"""Offline consumer regressions; AST loading avoids legacy startup side effects.

Requires PyQt6 (an application dependency). No provider requests are made.
"""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1] / "senpwai"


def load_node(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if getattr(n, "name", None) == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


class UnknownSizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtCore import QMutex, QTimer, Qt
        from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QProgressBar, QWidget

        cls.app = QApplication.instance() or QApplication([])
        ns = dict(QWidget=QWidget, QProgressBar=QProgressBar, QHBoxLayout=QHBoxLayout,
                  QMutex=QMutex, QTimer=QTimer, Qt=Qt, time=time,
                  OutlinedLabel=lambda parent, *_: QLabel(parent),
                  SETTINGS=SimpleNamespace(font_family="Arial"),
                  PAHE_NORMAL_COLOR="blue", GOGO_NORMAL_COLOR="green", RED_NORMAL_COLOR="red")
        cls.widget = load_node("common/widgets.py", "ProgressBarWithoutButtons", ns)

    def make_bar(self, total):
        bar = self.widget(None, "Downloading", "Example", total, "MB", 1, False)
        self.addCleanup(bar.deleteLater)
        return bar

    def test_unknown_total_tracks_bytes_without_premature_completion(self):
        bar = self.make_bar(None)
        self.assertEqual((bar.bar.minimum(), bar.bar.maximum()), (0, 0))
        bar.update_bar(150)
        self.assertFalse(bar.is_complete())
        self.assertIn("150/? MB", bar.current_against_max_values.text())
        self.assertNotIn("%", bar.percentage.text())
        self.assertEqual(bar.eta.text(), "? secs left")
        bar.pause_or_resume()
        self.assertTrue(bar.paused)
        bar.pause_or_resume()
        bar.complete()
        self.assertTrue(bar.is_complete())
        self.assertIn("Completed", bar.bar.format())
        self.assertEqual(bar.bar.value(), bar.bar.maximum())

    def test_cancelled_unknown_total_does_not_complete_on_late_update(self):
        bar = self.make_bar(None)
        bar.update_bar(50)
        bar.update_bar(-20)
        self.assertIn("30/? MB", bar.current_against_max_values.text())
        bar.cancel()
        bar.update_bar(10)
        bar.complete()
        self.assertTrue(bar.cancelled)
        self.assertFalse(bar.is_complete())
        self.assertIn("Cancelled", bar.bar.format())

    def test_known_total_keeps_percentage_and_completion(self):
        bar = self.make_bar(100)
        bar.update_bar(25)
        self.assertEqual(bar.percentage.text(), "25%")
        self.assertFalse(bar.is_complete())
        bar.update_bar(75)
        self.assertTrue(bar.is_complete())
        self.assertIn("Completed", bar.bar.format())

    def test_episode_completion_finishes_unknown_bar_before_queue_advances(self):
        class Counter:
            def update_count(self, added):
                self.current += added

        count_type = load_node("windows/download.py", "DownloadedEpisodeCount", dict(
            CurrentAgainstTotal=Counter, SETTINGS=SimpleNamespace(allow_notifications=False),
        ))
        for cancelled, total, added in ((False, 2, 1), (False, 0, 0), (True, 2, 0)):
            with self.subTest(cancelled=cancelled, total=total):
                bar = self.make_bar(None)
                counter = count_type.__new__(count_type)
                counter.current = 1 if total else 0
                counter.total = total
                counter.cancelled = cancelled
                counter.download_window = SimpleNamespace(current_anime_progress_bar=bar)
                terminal_states = []
                counter.start_next_download = lambda: terminal_states.append((bar.is_complete(), bar.cancelled))
                counter.update_count(added)
                self.assertEqual(terminal_states, [(not cancelled and total > 0, cancelled or total == 0)])

    def test_stale_episode_callback_cannot_terminalize_next_queued_bar(self):
        class Counter:
            def update_count(self, added):
                self.current += added

        count_type = load_node("windows/download.py", "DownloadedEpisodeCount", dict(
            CurrentAgainstTotal=Counter, SETTINGS=SimpleNamespace(allow_notifications=False),
        ))
        bar = self.make_bar(None)
        new_manager = object()
        counter = count_type.__new__(count_type)
        counter.current = 0
        counter.total = 1
        counter.cancelled = False
        counter.download_window = SimpleNamespace(
            current_anime_progress_bar=bar, current_download_manager_thread=new_manager,
        )
        advanced = []
        counter.start_next_download = lambda: advanced.append(True)
        # A leftover episode of the cancelled previous anime finishing late:
        counter.update_count(0, object())
        self.assertEqual(advanced, [])
        self.assertFalse(bar.cancelled)
        self.assertFalse(bar.is_complete())
        # The owning manager's episodes still drive the live bar:
        counter.update_count(1, new_manager)
        self.assertEqual(advanced, [True])
        self.assertTrue(bar.is_complete())
        self.assertIn("Completed", bar.bar.format())

    def test_stale_manager_callback_leaves_shared_counter_untouched(self):
        class Counter:
            def update_count(self, added):
                self.current += added

        count_type = load_node("windows/download.py", "DownloadedEpisodeCount", dict(
            CurrentAgainstTotal=Counter, SETTINGS=SimpleNamespace(allow_notifications=False),
        ))
        manager_type = load_node("windows/download.py", "DownloadManagerThread", dict(
            QThread=type("QThread", (), {"__init__": lambda *a, **k: None}),
            ProgressFunction=type("ProgressFunction", (), {"__init__": lambda self: None}),
            pyqtSignal=lambda *_, **__: None, Event=object, QMutex=object,
            AnimeDetails=object, DownloadWindow=object, ProgressBarWithoutButtons=object,
            DownloadedEpisodeCount=object, SETTINGS=SimpleNamespace(max_simultaneous_downloads=2),
            time=time,
        ))
        bar = self.make_bar(None)
        stale = manager_type.__new__(manager_type)
        stale.download_window = SimpleNamespace(
            current_download_manager_thread=object(), hls_est_size=SimpleNamespace(update_count=Mock()),
        )
        stale.downloaded_episode_count = count_type.__new__(count_type)
        stale.downloaded_episode_count.current = 0
        stale.downloaded_episode_count.total = 2
        stale.downloaded_episode_count.cancelled = False
        stale.downloaded_episode_count.download_window = SimpleNamespace(
            current_anime_progress_bar=bar, current_download_manager_thread=stale.download_window.current_download_manager_thread,
        )
        # Leftover cancelled episode after the counter reset to the new anime:
        stale.update_eps_count_and_size(True, "ignored")
        self.assertEqual(stale.downloaded_episode_count.total, 2)
        self.assertEqual(stale.downloaded_episode_count.current, 0)
        self.assertFalse(bar.cancelled)
        self.assertFalse(bar.is_complete())
        stale.downloaded_episode_count.hls_est_size = None
        # Leftover successful episode must not advance the new anime's counter either:
        stale.update_eps_count_and_size(False, "unused")
        self.assertEqual(stale.downloaded_episode_count.current, 0)
        stale.download_window.hls_est_size.update_count.assert_not_called()

    def test_unknown_aggregate_cancellation_uses_episode_values_not_maximum(self):
        thread_type = load_node("windows/download.py", "DownloadThread", dict(
            QThread=type("QThread", (), {}), pyqtSignal=lambda *_, **__: None,
            IBYTES_TO_MBS_DIVISOR=1048576, Download=None, get_max_part_size=None,
            DownloadManagerThread=object, Callable=object, cast=lambda t, v: v,
            ProgressBarWithButtons=object, ProgressBarWithoutButtons=object,
            QMutex=object, os=os,
        ))
        aggregate = self.make_bar(None)
        aggregate.update_bar(4)
        episode = self.make_bar(6 * 1048576)
        episode.bar.setValue(6 * 1048576)
        thread = thread_type.__new__(thread_type)
        thread.is_hls_download = False
        thread.download_size = 6 * 1048576
        thread.anime_progress_bar = aggregate
        thread.progress_bar = episode
        thread.download = Mock()
        thread.cancel()
        self.assertTrue(thread.is_cancelled)
        # Per-episode 6 MB is subtracted from the aggregate's 4 MB, floored at 0:
        self.assertIn("0/? MB", aggregate.current_against_max_values.text())
        # A single episode's cancel leaves the aggregate to the download manager;
        # only the manager's cancel-all marks the whole anime cancelled.
        self.assertFalse(aggregate.cancelled)
        self.assertFalse(aggregate.is_complete())
        aggregate.cancel()
        aggregate.complete()
        self.assertTrue(aggregate.cancelled)
        self.assertIn("Cancelled", aggregate.bar.format())
        # Late sibling data updates are ignored after cancellation:
        aggregate.update_bar(2)
        self.assertIn("0/? MB", aggregate.current_against_max_values.text())
        thread.download.cancel.assert_called_once()


class CliSizeTests(unittest.TestCase):
    def test_cli_unknown_and_known_totals_still_return_links(self):
        for total, text in ((None, "unknown"), (350, "350 MB"), (1200, "1200 MB, go shower"), (0, "0 MB")):
            with self.subTest(total=total):
                progress = Mock()
                pahe = SimpleNamespace(
                    GetPahewinPageLinks=lambda: SimpleNamespace(get_pahewin_page_links_and_info=lambda *_: (["download"], ["metadata"])),
                    bind_sub_or_dub_to_link_info=lambda _, links, info: (links, info),
                    bind_quality_to_link_info=lambda _, links, info: (links, info),
                    calculate_total_download_size=lambda _: total,
                )
                output = []
                function = load_node("senpcli/main.py", "pahe_get_download_page_links", dict(
                    pahe=pahe, ProgressBar=lambda **_: progress,
                    add_color=lambda value, _: value, Color=SimpleNamespace(MAGENTA=""), print_info=output.append,
                ))
                self.assertEqual(function(["episode"], "720p", "sub"), ["download"])
                self.assertEqual(output, [f"Total download size: {text}"])
                progress.close_.assert_called_once()


if __name__ == "__main__":
    unittest.main()
