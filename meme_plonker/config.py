import logging
import sys
import tkinter as ttk
from enum import Enum
from os import environ
from pathlib import Path
from sys import exit
from tkinter import Button, Label

from PIL import Image, ImageTk

# Remove pygame welcome text
environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import pygame

logger: logging.Logger = logging.getLogger(__name__)


class HandlePosition(Enum):
    TopLeft = 0
    TopRight = 1
    BottomLeft = 2
    BottomRight = 3


# Classic Windows 98 palette
WIN98_DESKTOP = "#008080"   # Teal desktop background
WIN98_FACE = "#c0c0c0"      # Button / panel face gray
WIN98_TOOLTIP = "#ffffe1"   # Pale yellow tooltip


class TkObject:
    # Tkinter object id
    id: int

    # Either the text or the PIL image
    data: str | Image.Image | None = None

    # The unrotated on-screen size of an image, used to keep resize/rotation crisp
    size: tuple[int, int] | None = None

    # For each position, the object id of the handle
    resize_handles: dict[HandlePosition, int]

    # Object id of the rotation handle
    rotate_handle: int | None

    # Object's rotation
    rotation: float

    # Animated GIF playback: the frames, current index, per-frame delays (ms) and
    # the pending `after` callback id. `frames` is None for a still image.
    frames: list[Image.Image] | None
    frame_index: int
    frame_durations: list[int]
    anim_id: str | None

    def __init__(self, id: int, data: str | Image.Image):
        self.id = id
        self.data = data
        self.size = None
        self.resize_handles = {}
        self.rotate_handle = None
        self.rotation = 0.0
        self.frames = None
        self.frame_index = 0
        self.frame_durations = []
        self.anim_id = None


def show_tooltip(event, label: Label, text: str):
    """Display tooltip with dynamic text."""
    label.config(text=text)
    label.place(relx=1.0, rely=0.0, anchor='ne')


def setup_widget(widget: Button | Label, tooltip_label: Label | None = None, text: str | None = None, packing: bool = True):
    """Add sounds and text on hover on given widget object."""
    if packing:
        widget.pack(pady=5, padx=10)

    # Give buttons the chunky, beveled Windows 98 look and a "select" cursor.
    if isinstance(widget, Button):
        widget.config(relief="raised", bd=3, bg=WIN98_FACE,
                      activebackground=WIN98_FACE, highlightthickness=0,
                      cursor="hand2")
        # Make the global click/release sounds (on the "all" bindtag) fire BEFORE
        # the button's own command. Otherwise a command that opens a modal dialog
        # (e.g. the color picker) blocks the event loop and the release sound only
        # plays once the dialog closes.
        tags = list(widget.bindtags())
        if "all" in tags:
            tags.remove("all")
            tags.insert(1, "all")
            widget.bindtags(tuple(tags))

    # The click/release sounds are played globally via bind_all in main().
    if tooltip_label and text:
        widget.bind("<Enter>", lambda event: show_tooltip(
            event, tooltip_label, text))
        widget.bind("<Leave>", lambda event: tooltip_label.place_forget())


class Config:
    _instance = None

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            # Initialize configuration variables
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        # Initialize the variables only once
        # Window files
        self.WIDTH = 10
        self.HEIGHT = 20
        self.LEFT_FRAME_WIDTH = 1
        self.MINIMUM_WIDTH = 8
        self.MINIMUM_HEIGHT = 20
        self.MAXIMUM_WIDTH = 40
        self.MAXIMUM_HEIGHT = 40
        self.HANDLE_SIZE = 10

        package_dir = Path(__file__).resolve().parent
        project_root = package_dir.parent
        exe_dir = Path(sys.executable).parent

        # src/ (icons + sounds) is bundled inside the package for installed tools
        # (see pyproject force-include) and sits at the project root from source.
        src_candidates = [
            package_dir / "src",   # bundled wheel / uv tool install
            project_root / "src",  # editable install / source checkout
            exe_dir / "src",       # PyInstaller build
            Path.cwd() / "src",
        ]
        self.SRC_FOLDER = next((p for p in src_candidates if p.is_dir()), src_candidates[0])

        # Text font. Drop a TTF at src/impact.ttf to force the exact same font for
        # both the on-screen preview and the saved image (and to embed it in
        # builds). Without it we fall back to the system "Impact" font by name.
        self.FONT_FAMILY = "Impact"
        font_file = self.SRC_FOLDER / "impact.ttf"
        self.FONT_FILE: Path | None = font_file if font_file.exists() else None
        self._register_font()

        # The meme library is large (~200 MB), so it is kept external. Point at it
        # with the MEMEPLONKER_MEMES environment variable; otherwise fall back to
        # the project layout. If none is found the browser simply shows no memes.
        meme_candidates = []
        if env_library := environ.get("MEMEPLONKER_MEMES"):
            meme_candidates.append(Path(env_library))
        meme_candidates += [
            package_dir / "meme_scrapper" / "output",   # embedded in the executable
            project_root / "meme_scrapper" / "output",  # editable install / source
            exe_dir / "meme_scrapper" / "output",       # beside a PyInstaller build
            Path.cwd() / "meme_scrapper" / "output",
        ]
        self.MEME_FOLDER = next(
            (p for p in meme_candidates if (p / "memes.json").exists()),
            meme_candidates[0],
        )
        self.MEME_INDEX = self.MEME_FOLDER / "memes.json"

        # List of all shown objects (objects are ordered depending on their display order)
        self.objects: list[TkObject] = []

        # List of processed Tkinter images
        self.images: list[tuple[int, ttk.PhotoImage]] = []

        # Coordinates of the last click on object
        self.last_x, self.last_y = 0, 0

        # Coordinates of the last click on a rotate handle
        self.rotate_x, self.rotate_y = 0, 0

        # The initial angle at the last click on a rotate handle
        self.initial_angle = 0.0

        # Selection and drawing
        self.selected_item = None
        self.selection_rect = None
        self.pen_color = "black"

        # True while a resize/rotate handle is being dragged, so plain dragging
        # (on_drag) does not fight the handle interaction.
        self.interacting_handle = False

        # Sounds (initialize pygame and load sounds)
        pygame.mixer.init()
        try:
            self.click = pygame.mixer.Sound(
                (self.SRC_FOLDER / "click.mp3").as_posix())
            self.click_release = pygame.mixer.Sound(
                (self.SRC_FOLDER / "click_release.mp3").as_posix())
            self.trash = pygame.mixer.Sound(
                (self.SRC_FOLDER / "trash.mp3").as_posix())
            self.saved = pygame.mixer.Sound(
                (self.SRC_FOLDER / "saved.mp3").as_posix())
            self.loading = pygame.mixer.Sound(
                (self.SRC_FOLDER / "loading.mp3").as_posix())
            self.ding = pygame.mixer.Sound(
                (self.SRC_FOLDER / "ding.mp3").as_posix())
            self.crop = pygame.mixer.Sound(
                (self.SRC_FOLDER / "crop.mp3").as_posix())
        except FileNotFoundError:
            print(
                f"Missing sound files under {self.SRC_FOLDER}. Run 'plonker' from the "
                "project root, or place 'src' and 'meme_scrapper' next to the executable.")
            exit(1)

        # Soften the click feedback by 40% (played on every click).
        self.click.set_volume(0.6)
        self.click_release.set_volume(0.6)

    def _register_font(self) -> None:
        """If a font file is bundled, read its family and make it usable by name.

        This runs before the Tk root is created so the preview can pick the font up.
        """
        if not self.FONT_FILE:
            return
        try:
            from PIL import ImageFont
            self.FONT_FAMILY = ImageFont.truetype(str(self.FONT_FILE), 20).getname()[0]
        except (OSError, ValueError):
            return

        if sys.platform.startswith("win"):
            # Register the file privately so Tk can render the preview with it.
            try:
                import ctypes
                FR_PRIVATE = 0x10
                ctypes.windll.gdi32.AddFontResourceExW(str(self.FONT_FILE), FR_PRIVATE, 0)
            except OSError:
                pass
        elif sys.platform.startswith("linux"):
            # Expose the font to fontconfig (so Tk finds it by name) by dropping it
            # in the user fonts dir and refreshing the cache. Best-effort.
            try:
                import shutil
                import subprocess
                fonts_dir = Path.home() / ".local" / "share" / "fonts"
                fonts_dir.mkdir(parents=True, exist_ok=True)
                dest = fonts_dir / self.FONT_FILE.name
                if not dest.exists():
                    shutil.copyfile(self.FONT_FILE, dest)
                    subprocess.run(["fc-cache", "-f", str(fonts_dir)], check=False,
                                   timeout=15, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                pass

    def get_object(self, id: int) -> TkObject | None:
        """Get an object from a given tkinter id."""
        for obj in self.objects:
            if obj.id == id:
                return obj
        return None

    def update_dimensions(self, screen_width: int, screen_height: int) -> None:
        """Update all dimension variables depending on the screen dimensions."""
        self.MAXIMUM_WIDTH = screen_width
        self.MAXIMUM_HEIGHT = int(screen_height * 0.8)
        self.WIDTH = self.MAXIMUM_WIDTH // 5
        self.HEIGHT = self.MAXIMUM_HEIGHT // 2
        self.MINIMUM_WIDTH = self.WIDTH
        self.MINIMUM_HEIGHT = self.HEIGHT
        self.LEFT_FRAME_WIDTH = self.WIDTH // 5

    def load_resized_icon(self, path: Path) -> ImageTk.PhotoImage:
        """Load and resize an image icon to the given size."""
        size = (self.LEFT_FRAME_WIDTH // 2, self.LEFT_FRAME_WIDTH // 2)
        img = Image.open(self.SRC_FOLDER / path).resize(size, Image.LANCZOS)
        return ImageTk.PhotoImage(img)
