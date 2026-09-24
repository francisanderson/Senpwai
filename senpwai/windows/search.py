import random
import time
from typing import TYPE_CHECKING, Any, cast

from PyQt6.QtCore import QEvent, QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLayoutItem,
    QLineEdit,
    QScrollBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from senpwai.scrapers import gogo, pahe
from senpwai.common.classes import Anime
from senpwai.common.scraper import (
    CLIENT,
    DomainNameError,
    InvalidDownloadResponse,
)
from requests.exceptions import RequestException
from senpwai.common.classes import SETTINGS
from senpwai.common.static import (
    ANILIST_API_ENTRYPOINY,
    BUNSHIN_POOF_AUDIO_PATH,
    GIGACHAD_AUDIO_PATH,
    GOGO,
    GOGO_HOVER_COLOR,
    GOGO_NORMAL_COLOR,
    GOGO_PRESSED_COLOR,
    IS_CHRISTMAS,
    KAGE_BUNSHIN_AUDIO_PATH,
    L_ANIME,
    LOADING_ANIMATION_PATH,
    MERRY_CHRISMASU_AUDIO_PATH,
    PAHE,
    PAHE_HOVER_COLOR,
    PAHE_NORMAL_COLOR,
    PAHE_PRESSED_COLOR,
    RANDOM_MACOT_ICON_PATH,
    ANIME_NOT_FOUND_PATH,
    SEARCH_WINDOW_BCKG_IMAGE_PATH,
    SEN_ANILIST_ID,
    SEN_FAVOURITE_AUDIO_PATH,
    ONE_PIECE_REAL_AUDIO_PATH,
    TOKI_WA_UGOKI_DASU_AUDIO_PATH,
    W_ANIME,
    WHAT_DA_HELL_AUDIO_PATH,
    ZA_WARUDO_AUDIO_PATH,
)
from senpwai.common.widgets import (
    AnimationAndText,
    AudioPlayer,
    Icon,
    IconButton,
    OutlinedButton,
    ScrollableSection,
    StyledButton,
    set_minimum_size_policy,
)

from senpwai.windows.abstracts import AbstractWindow

# https://stackoverflow.com/questions/39740632/python-type-hinting-without-cyclic-imports/3957388#39757388
if TYPE_CHECKING:
    from senpwai.windows.main import MainWindow


class SearchWindow(AbstractWindow):
    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window, SEARCH_WINDOW_BCKG_IMAGE_PATH)
        self.main_window = main_window
        self.main_window.app.aboutToQuit.connect(self.shutdown)
        self._shutdown = False
        main_widget = QWidget()
        main_layout = QVBoxLayout()

        mascot_button = IconButton(Icon(117, 100, RANDOM_MACOT_ICON_PATH), 1)
        mascot_button.setToolTip("Goofy 🗿")

        mascot_button.clicked.connect(
            AudioPlayer(self, SEN_FAVOURITE_AUDIO_PATH, volume=60).play
        )
        mascot_button.clicked.connect(FetchFavouriteThread(self).start)
        self.search_bar = SearchBar(self)
        self.get_search_bar_text = lambda: self.search_bar.text()
        self.search_bar.setMinimumHeight(60)

        search_bar_and_mascot_widget = QWidget()
        search_bar_and_mascot_layout = QVBoxLayout()
        search_bar_and_mascot_layout.addWidget(
            mascot_button, alignment=Qt.AlignmentFlag.AlignHCenter
        )
        search_bar_and_mascot_layout.addWidget(self.search_bar)
        search_bar_and_mascot_layout.setSpacing(0)
        search_bar_and_mascot_widget.setLayout(search_bar_and_mascot_layout)
        main_layout.addWidget(search_bar_and_mascot_widget)

        search_buttons_widget = QWidget()
        search_buttons_layout = QHBoxLayout()
        self.pahe_search_button = SearchButton(self, PAHE)
        set_minimum_size_policy(self.pahe_search_button)
        self.gogo_search_button = SearchButton(self, GOGO)
        set_minimum_size_policy(self.gogo_search_button)
        search_buttons_layout.addWidget(self.pahe_search_button)
        search_buttons_layout.addWidget(self.gogo_search_button)
        search_buttons_widget.setLayout(search_buttons_layout)
        main_layout.addWidget(search_buttons_widget)
        self.results_layout = QVBoxLayout()
        self.results_widget = ScrollableSection(self.results_layout)
        self.res_wid_hor_scroll_bar = cast(
            QScrollBar, self.results_widget.horizontalScrollBar()
        )

        self.loading = AnimationAndText(
            LOADING_ANIMATION_PATH, 250, 300, "Loading.. .", 1, 48, 50
        )
        self.anime_not_found = AnimationAndText(
            ANIME_NOT_FOUND_PATH, 400, 300, ":( couldn't find that anime ", 1, 48, 50
        )
        self.bottom_section_stacked_widgets = QStackedWidget()
        self.bottom_section_stacked_widgets.addWidget(self.results_widget)
        self.bottom_section_stacked_widgets.addWidget(self.loading)
        self.bottom_section_stacked_widgets.addWidget(self.anime_not_found)
        self.bottom_section_stacked_widgets.setCurrentWidget(self.results_widget)
        main_layout.addWidget(self.bottom_section_stacked_widgets)
        self.search_thread: SearchThread | None = None
        self.search_threads: list[SearchThread] = []
        self.pending_thread_cleanup: list = []
        self.naruto_threads: list = []
        self.active_naruto_owner = None
        self.active_naruto_thread = None
        main_widget.setLayout(main_layout)
        self.full_layout.addWidget(main_widget)
        self.setLayout(self.full_layout)
        # We use a timer instead of calling setFocus normally cause apparently Qt wont really set the widget in focus if the widget isn't shown on screen,
        # So we gotta wait a bit first till the UI is rendered.
        # Stack Overflow comment link: https://stackoverflow.com/questions/52853701/set-focus-on-button-in-app-with-group-boxes#comment92652037_52858926
        QTimer.singleShot(0, self.search_bar.setFocus)

    def shutdown(self):
        if self._shutdown:
            return
        self._shutdown = True
        self.active_naruto_owner = None
        self.active_naruto_thread = None
        threads = [*self.search_threads, *self.naruto_threads]
        for thread in threads:
            cancel = getattr(thread, "cancel", None)
            if callable(cancel):
                cancel()
            thread.quit()
        for thread in threads:
            wait = getattr(thread, "wait", None)
            if callable(wait):
                wait()
            delete_later = getattr(thread, "deleteLater", None)
            if callable(delete_later):
                delete_later()
        self.search_threads.clear()
        self.naruto_threads.clear()
        self.pending_thread_cleanup.clear()
        self.search_thread = None

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    # Qt pushes the horizontal scroll bar to the center automatically sometimes
    def fix_hor_scroll_bar(self):
        self.res_wid_hor_scroll_bar.setValue(self.res_wid_hor_scroll_bar.minimum())

    def set_focus(self):
        self.search_bar.setFocus()
        self.fix_hor_scroll_bar()

    def search_anime(self, anime_title: str, site: str) -> None:
        if not anime_title:
            return
        self.active_naruto_owner = None
        self.active_naruto_thread = None
        previous_thread = self.search_thread
        if previous_thread:
            previous_thread.cancel()
            previous_thread.quit()
            is_finished = getattr(previous_thread, "isFinished", None)
            if callable(is_finished) and is_finished():
                self.search_thread = None
                self.remove_search_thread(previous_thread)
        was_anime_not_found = (
            self.bottom_section_stacked_widgets.currentWidget() == self.anime_not_found
        )
        self.loading.start()
        self.bottom_section_stacked_widgets.setCurrentWidget(self.loading)
        if was_anime_not_found:
            self.anime_not_found.stop()
        for idx in reversed(range(self.results_layout.count())):
            item = cast(
                QWidget, cast(QLayoutItem, self.results_layout.itemAt(idx)).widget()
            ).deleteLater()
            self.results_layout.removeItem(item)
        owner = SearchThread(self, anime_title, site)
        self.search_thread = owner
        self.search_threads.append(owner)
        anime_title_lower = anime_title.lower()
        is_naruto = "naruto" in anime_title_lower or "boruto" in anime_title_lower
        if "one piece" in anime_title_lower:
            AudioPlayer(self, ONE_PIECE_REAL_AUDIO_PATH, volume=100).play()
        elif "jojo" in anime_title_lower:
            AudioPlayer(self, ZA_WARUDO_AUDIO_PATH, 100).play()
            for _ in range(180):
                self.main_window.app.processEvents()
                time.sleep(0.01)
            for x in range(20):
                self.main_window.app.processEvents()
                time.sleep(x * 0.01)
            time.sleep(2)
            AudioPlayer(self, TOKI_WA_UGOKI_DASU_AUDIO_PATH, 100).play()
            time.sleep(1.8)
        elif any(w_anime in anime_title_lower for w_anime in W_ANIME):
            AudioPlayer(self, GIGACHAD_AUDIO_PATH, 25).play()
        elif any(l_anime in anime_title_lower for l_anime in L_ANIME):
            AudioPlayer(self, WHAT_DA_HELL_AUDIO_PATH, 100).play()
        elif is_naruto:
            self.kage_bunshin_no_jutsu = AudioPlayer(
                self, KAGE_BUNSHIN_AUDIO_PATH, volume=50
            )
            self.kage_bunshin_no_jutsu.play()
        elif IS_CHRISTMAS:
            AudioPlayer(self, MERRY_CHRISMASU_AUDIO_PATH, 30).play()

        owner.is_naruto = is_naruto
        owner.search_finished.connect(self._handle_search_finished)
        owner.failed.connect(self._handle_search_failure)
        owner.finished.connect(self.remove_search_thread)
        owner.start()

    def _handle_search_finished(self, owner_thread, site, results):
        if owner_thread is not self.search_thread:
            return
        if getattr(owner_thread, "is_naruto", False):
            self.search_thread = None
            self.active_naruto_owner = owner_thread
            self.start_naruto_results_thread(site, results, owner_thread)
        else:
            self.show_results(site, results, owner_thread)

    def _handle_search_failure(self, owner_thread, message):
        if owner_thread is not self.search_thread:
            return
        self.show_search_error(message, owner_thread)

    def remove_search_thread(self, thread=None):
        if thread is None:
            thread = self.sender() if hasattr(self, "sender") else None
        if thread is None or self.search_thread is thread:
            return
        is_finished = getattr(thread, "isFinished", None)
        if callable(is_finished) and not is_finished():
            if thread not in self.pending_thread_cleanup:
                self.pending_thread_cleanup.append(thread)
            return
        if thread in self.pending_thread_cleanup:
            self.pending_thread_cleanup.remove(thread)
        if any(
            getattr(naruto_thread, "owner_thread", None) is thread
            for naruto_thread in self.naruto_threads
        ):
            return
        if thread in self.search_threads:
            self.search_threads.remove(thread)
        delete_later = getattr(thread, "deleteLater", None)
        if callable(delete_later):
            delete_later()

    def start_naruto_results_thread(
        self, site: str, results: list[Anime], owner_thread=None
    ):
        if owner_thread is not None and owner_thread is not self.active_naruto_owner:
            return
        thread = NarutoResultsThread(self, site, results, owner_thread)
        self.naruto_threads.append(thread)
        self.active_naruto_thread = thread
        thread.finished.connect(self.finish_naruto_results)
        thread.start()

    def _owner_is_current(self, owner_thread):
        return (
            owner_thread is None
            or owner_thread is self.search_thread
            or owner_thread is self.active_naruto_owner
        )

    def finish_naruto_results(self, thread=None):
        if thread is None:
            thread = self.sender() if hasattr(self, "sender") else None
        if thread in self.naruto_threads:
            self.naruto_threads.remove(thread)
        if self.active_naruto_thread is thread:
            self.active_naruto_thread = None
            self.active_naruto_owner = None
        delete_later = getattr(thread, "deleteLater", None)
        if callable(delete_later):
            delete_later()
        owner_thread = getattr(thread, "owner_thread", None)
        if owner_thread is not None:
            self.remove_search_thread(owner_thread)

    def play_bunshin_poof(self):
        AudioPlayer(self, BUNSHIN_POOF_AUDIO_PATH, 10).play()

    def stop_naruto_loading(self, owner_thread):
        if self._owner_is_current(owner_thread):
            self.loading.stop()

    def show_naruto_not_found(self, owner_thread):
        if self._owner_is_current(owner_thread):
            self.anime_not_found.start()

    def set_naruto_widget(self, owner_thread, widget):
        if self._owner_is_current(owner_thread):
            self.bottom_section_stacked_widgets.setCurrentWidget(widget)

    def play_naruto_bunshin(self, owner_thread):
        if self._owner_is_current(owner_thread):
            self.play_bunshin_poof()

    def show_results(
        self, site: str, results: list[Anime], owner_thread=None
    ):
        if owner_thread is not None and owner_thread is not self.search_thread:
            return
        sender = self.sender() if hasattr(self, "sender") else None
        if sender is not None and sender is not self.search_thread:
            return
        if not results:
            self.anime_not_found.text_label.setText(":( couldn't find that anime ")
            self.anime_not_found.start()
            self.bottom_section_stacked_widgets.setCurrentWidget(self.anime_not_found)
        else:
            self.bottom_section_stacked_widgets.setCurrentWidget(self.results_widget)
            for result in results:
                button = ResultButton(result, self.main_window, self, site, 9, 48)
                self.results_layout.addWidget(button)
        self.loading.stop()
        self.search_thread = None
        if owner_thread is not None:
            self.remove_search_thread(owner_thread)

    def show_search_error(
        self, message: str, owner_thread=None
    ):
        if owner_thread is not None and owner_thread is not self.search_thread:
            return
        sender = self.sender() if hasattr(self, "sender") else None
        if sender is not None and sender is not self.search_thread:
            return
        display_message = message.removeprefix("Search failed: ")
        self.loading.stop()
        self.search_thread = None
        self.anime_not_found.text_label.setText(f"Search failed: {display_message}")
        self.anime_not_found.start()
        self.bottom_section_stacked_widgets.setCurrentWidget(self.anime_not_found)
        self.main_window.tray_icon.make_notification(
            "Search failed", display_message, False, None
        )
        if owner_thread is not None:
            self.remove_search_thread(owner_thread)

    def make_naruto_result_button(self, owner_thread, result: Anime, site: str):
        if not self._owner_is_current(owner_thread):
            return
        button = ResultButton(result, self.main_window, self, site, 9, 48)
        self.results_layout.addWidget(button)


class NarutoResultsThread(QThread):
    send_result = pyqtSignal(object, Anime, str)
    stop_loading_animation = pyqtSignal(object)
    start_anime_not_found_animation = pyqtSignal(object)
    set_curr_wid = pyqtSignal(object, QWidget)
    play_bunshin = pyqtSignal(object)

    def __init__(
        self,
        search_window: SearchWindow,
        site: str,
        results: list[Anime],
        owner_thread=None,
    ):
        super().__init__(search_window)
        self.search_window = search_window
        self.results = results
        self.site = site
        self.owner_thread = owner_thread
        self.cancelled = False
        self.bunshin_poof = AudioPlayer(search_window, BUNSHIN_POOF_AUDIO_PATH)
        self.send_result.connect(search_window.make_naruto_result_button)
        self.stop_loading_animation.connect(search_window.stop_naruto_loading)
        self.start_anime_not_found_animation.connect(
            search_window.show_naruto_not_found
        )
        self.set_curr_wid.connect(search_window.set_naruto_widget)
        self.play_bunshin.connect(search_window.play_naruto_bunshin)

    def cancel(self):
        self.cancelled = True

    def _is_current_search(self):
        return not self.cancelled and (
            self.owner_thread is None
            or self.search_window.active_naruto_owner is self.owner_thread
        )

    def run(self):
        if not self._is_current_search():
            return
        while self.search_window.kage_bunshin_no_jutsu.isPlaying():
            if not self._is_current_search():
                return
            time.sleep(0.1)
        if not self._is_current_search():
            return
        if not self.results:
            self.start_anime_not_found_animation.emit(self.owner_thread)
            self.set_curr_wid.emit(self.owner_thread, self.search_window.anime_not_found)
        else:
            self.stop_loading_animation.emit(self.owner_thread)
            self.set_curr_wid.emit(self.owner_thread, self.search_window.results_widget)
            for idx, result in enumerate(self.results):
                if not self._is_current_search():
                    return
                self.send_result.emit(self.owner_thread, result, self.site)
                if idx <= 5:
                    self.play_bunshin.emit(self.owner_thread)
                    time.sleep(0.35)


class FetchFavouriteThread(QThread):
    def __init__(self, search_window: SearchWindow) -> None:
        super().__init__(search_window)
        self.search_window = search_window

    def run(self):
        favourite = self.get_random_sen_favourite()
        if not favourite:
            return
        self.type_write_favourite_in_search_bar(favourite)

    def type_write_favourite_in_search_bar(self, favourite_name: str):
        self.search_window.search_bar.clear()
        for idx in range(len(favourite_name)):
            self.search_window.search_bar.setText(favourite_name[: idx + 1])
            time.sleep(0.1)

    def get_random_sen_favourite(self) -> str | None:
        page = random.choice((1, 2))
        query = """
        query getUserFavourite($id: Int, $page: Int){
        User(id: $id) {
            favourites{
            anime(page: $page){
                nodes{
                title{
                    romaji
                }
                }
                pageInfo {
                lastPage
                perPage
                total
                }
            }
            }
        }
        }
        """
        response = CLIENT.post(
            ANILIST_API_ENTRYPOINY,
            json={"query": query, "variables": {"id": SEN_ANILIST_ID, "page": page}},
            headers=CLIENT.make_headers({"Content-Type": "application/json"}),
        )
        if response.status_code != 200:
            return None
        response_json = response.json()
        favourites: list[dict["str", Any]] = response_json["data"]["User"][
            "favourites"
        ]["anime"]["nodes"]
        if not favourites:
            return None
        chosen_favourite = random.choice(favourites)
        anime_title = chosen_favourite["title"]["romaji"]
        return anime_title


class SearchBar(QLineEdit):
    def __init__(self, search_window: SearchWindow):
        super().__init__()
        self.search_window = search_window
        self.setPlaceholderText("Enter anime title")
        self.installEventFilter(self)
        self.setStyleSheet(
            f"""
            QLineEdit{{
                border: 1px solid black;
                border-radius: 15px;
                padding: 5px;
                background-color: white;
                color: black;
                font-size: 30px;
                font-family: {SETTINGS.font_family};
            }}
        """
        )

    def eventFilter(self, a0: QObject | None, a1: QEvent | None):
        if isinstance(a1, QKeyEvent) and a0 == self and a1.type() == a1.Type.KeyPress:
            if a1.key() == Qt.Key.Key_Enter or a1.key() == Qt.Key.Key_Return:
                self.search_window.pahe_search_button.animateClick()
                return True
            elif a1.key() == Qt.Key.Key_Tab:
                self.search_window.gogo_search_button.animateClick()
                return True
            elif a1.key() == Qt.Key.Key_Down:
                first_button = self.search_window.results_layout.itemAt(0)
                if first_button:
                    cast(QWidget, first_button.widget()).setFocus()
                return True
        return super().eventFilter(a0, a1)


class SearchButton(StyledButton):
    def __init__(self, window: SearchWindow, site: str):
        if site == PAHE:
            super().__init__(
                window,
                40,
                "black",
                PAHE_NORMAL_COLOR,
                PAHE_HOVER_COLOR,
                PAHE_PRESSED_COLOR,
            )
            self.setText("Animepahe")
        else:
            super().__init__(
                window,
                40,
                "black",
                GOGO_NORMAL_COLOR,
                GOGO_HOVER_COLOR,
                GOGO_PRESSED_COLOR,
            )
            self.setText("Gogoanime")
        self.clicked.connect(
            lambda: window.search_anime(window.get_search_bar_text(), site)
        )


class ResultButton(OutlinedButton):
    def __init__(
        self,
        anime: Anime,
        main_window: "MainWindow",
        search_window: SearchWindow,
        site: str,
        paint_x: int,
        paint_y: int,
    ):
        self.search_window = search_window
        if site == PAHE:
            hover_color = PAHE_NORMAL_COLOR
            pressed_color = PAHE_HOVER_COLOR
        else:
            hover_color = GOGO_NORMAL_COLOR
            pressed_color = GOGO_HOVER_COLOR
        super().__init__(
            paint_x,
            paint_y,
            None,
            40,
            "white",
            "transparent",
            hover_color,
            pressed_color,
            21,
        )
        self.setText(anime.title)
        self.setStyleSheet(
            self.styleSheet()
            + """
                           QPushButton{
                           text-align: left;
                           border: none;
                           }"""
        )
        self.style_sheet_buffer = self.styleSheet()
        self.focused_sheet = (
            self.style_sheet_buffer
            + f"""
                    QPushButton{{
                        background-color: {hover_color};
        }}"""
        )
        self.clicked.connect(
            lambda: main_window.switch_to_chosen_anime_window(anime, site)
        )
        self.installEventFilter(self)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None):
        if a0 == self:
            a1 = cast(QEvent, a1)
            if a1.type() == QEvent.Type.FocusIn:
                self.setStyleSheet(self.focused_sheet)
            elif a1.type() == QEvent.Type.FocusOut:
                self.setStyleSheet(self.style_sheet_buffer)
            if (
                isinstance(a1, QKeyEvent)
                and a1.type() == a1.Type.KeyPress
                and (
                    a1.key()
                    in (
                        Qt.Key.Key_Tab,
                        Qt.Key.Key_Up,
                        Qt.Key.Key_Down,
                        Qt.Key.Key_Left,
                        Qt.Key.Key_Right,
                    )
                )
            ):
                # It doesn't work without the QTimer for some reason, probably cause the horizontal scroll bar centering bug happens
                # after this event is processed so the fix is overwridden hence we wait for the bug to happen first then fix it thus we need the QTimer
                QTimer(self).singleShot(0, self.search_window.fix_hor_scroll_bar)
        return super().eventFilter(a0, a1)


class SearchThread(QThread):
    search_finished = pyqtSignal(object, str, list)
    failed = pyqtSignal(object, str)

    def __init__(self, search_window: SearchWindow, anime_title: str, site: str):
        super().__init__(search_window)
        self.anime_title = anime_title
        self.site = site
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        extracted_results = []
        try:
            if self.site == PAHE:
                results = pahe.search(self.anime_title)

                for result in results:
                    title, page_link, anime_id = pahe.extract_anime_title_page_link_and_id(
                        result
                    )
                    extracted_results.append(Anime(title, page_link, anime_id))
            elif self.site == GOGO:
                results = gogo.search(self.anime_title)
                for title, page_link in results:
                    extracted_results.append(Anime(title, page_link, None))
        except (
            RequestException,
            DomainNameError,
            InvalidDownloadResponse,
            KeyError,
            TypeError,
            AttributeError,
        ) as error:
            if not self.cancelled:
                message = (
                    str(error)
                    if isinstance(error, InvalidDownloadResponse)
                    else f"{error}. Check your connection and try again later."
                )
                self.failed.emit(self, message)
            return
        except Exception as error:
            if not self.cancelled:
                message = (
                    str(error)
                    if isinstance(error, InvalidDownloadResponse)
                    else f"{error}. Check your connection and try again later."
                )
                self.failed.emit(self, message)
            return
        if not self.cancelled:
            self.search_finished.emit(self, self.site, extracted_results)
