import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import Button, Canvas, Entry, Frame, Label, PhotoImage, StringVar, Tk, Toplevel

from PIL import Image, ImageSequence, ImageTk

from meme_plonker.canvas_operations import open_image
from meme_plonker.config import WIN98_DESKTOP, WIN98_FACE, WIN98_TOOLTIP, Config, setup_widget

logger: logging.Logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")


@dataclass
class Meme:
    """A meme from the scraped library: its image plus searchable title and tags."""

    path: Path
    title: str
    tags: list[str] = field(default_factory=list)
    search_key: str = ""  # lowercased "title + tags" blob, precomputed for filtering


def load_meme_library(meme_folder: Path, index_file: Path) -> list[Meme]:
    """Build the meme list from the scraper's memes.json (title + tags + image path).

    Falls back to scanning meme_folder/images when the index is unavailable, so the
    browser still works with images only.
    """
    memes: list[Meme] = []

    try:
        with open(index_file, encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, ValueError) as error:
        logger.warning("Could not read meme index %s (%s); scanning images instead.",
                       index_file, error)
        entries = []

    for entry in entries:
        image_path = meme_folder / entry.get("image_file", "")
        if not image_path.exists():
            continue
        title = entry.get("title") or image_path.stem
        tags = entry.get("tags", [])
        search_key = " ".join([title, *tags]).lower()
        memes.append(Meme(image_path, title, tags, search_key))

    # Fallback: no index (or empty) but images exist on disk.
    if not memes:
        images_dir = meme_folder / "images"
        if images_dir.is_dir():
            for f in sorted(images_dir.iterdir()):
                if f.suffix.lower() in IMAGE_SUFFIXES:
                    memes.append(Meme(f, f.stem, [], f.stem.lower()))

    return sorted(memes, key=lambda meme: meme.title.lower())


class MemeBrowser:
    # Root widgets
    root: Tk
    root_left_frame: Frame
    root_button_frame: Frame
    root_canvas: Canvas

    # Current widgets
    browser: Toplevel
    grid_frame: Frame
    tooltip_label: Label

    # Grid layout
    columns: int
    rows: int
    per_page: int

    # Full meme library (image + title + tags)
    meme_list: list[Meme]

    # List of currently displayed images
    displayed_images: list[Label]

    # Store the selected image id
    selected_image: Label | None

    # Cache of loaded thumbnails, keyed by image path. A value is a PhotoImage
    # for a still image, or (frames, durations) for an animated GIF.
    image_cache: dict[Path, PhotoImage | tuple[list[PhotoImage], list[int]]]

    # Memes matching the current search filter
    processed_memes: list[Meme]

    # Page number (starting to 1)
    page: int

    # Size in pixels of each image
    image_size: int

    # Store the job delay to apply a filter
    debounce_job: str | None

    # The id of the trace for the search var
    search_trace_id: int

    def __init__(self, root: Tk, root_left_frame: Frame, root_button_frame: Frame, root_canvas: Canvas):
        """Opens a new window to browse and filter images."""
        config = Config()
        self.root = root
        self.root_left_frame = root_left_frame
        self.root_button_frame = root_button_frame
        self.root_canvas = root_canvas
        self.page = 1

        # Create the Toplevel window
        self.browser = Toplevel(root)
        self.browser.title("Meme Browser")
        self.browser.configure(bg=WIN98_FACE)

        # Grid of columns x rows memes per page, with the window sized to fit
        # them all so there is no inner scrollbar (paging handles the rest).
        self.columns, self.rows = 5, 5
        self.per_page = self.columns * self.rows

        win_height = int(config.MAXIMUM_HEIGHT * 0.9)
        # Reserve vertical room for the search bar and the navigation row.
        grid_area_height = win_height - 140
        cell = max(60, grid_area_height // self.rows)
        self.image_size = cell - 14
        win_width = self.columns * cell + 40

        # Center the browser over the main window (based on its position).
        root.update_idletasks()
        center_x = root.winfo_x() + root.winfo_width() // 2
        center_y = root.winfo_y() + root.winfo_height() // 2
        x_position = max(0, center_x - win_width // 2)
        y_position = max(0, center_y - win_height // 2)
        self.browser.geometry(f"{win_width}x{win_height}+{x_position}+{y_position}")

        icon = PhotoImage(file=config.SRC_FOLDER / 'memes.png')
        self.browser.iconphoto(False, icon)

        # Search Bar
        self.search_var = StringVar()
        self.debounce_job = None  # To keep track of the debounce timer

        # Pass search_var explicitly
        self.search_trace_id = self.search_var.trace_add(
            "write", lambda *args: self.on_search_change(self.search_var, *args))

        self.search_entry = Entry(self.browser, textvariable=self.search_var, width=40)
        self.placeholder_text = 'Search for a meme'
        self.set_placeholder(None)
        self.search_entry.bind("<FocusIn>", self.clear_placeholder)
        self.search_entry.bind("<FocusOut>", self.set_placeholder)
        self.search_entry.bind('<Control-BackSpace>', self.clear_all)
        self.search_entry.pack(side="top", pady=8)

        # Tooltip on hover of each image
        self.tooltip_label = Label(self.browser, text="...", bg=WIN98_TOOLTIP,
                                   relief="solid", bd=1)
        self.tooltip_label.place_forget()

        # Navigation buttons, centered at the bottom.
        self.left_icon = config.load_resized_icon("left.png")
        self.right_icon = config.load_resized_icon("right.png")
        nav_frame = Frame(self.browser, bg=WIN98_FACE)
        nav_frame.pack(side="bottom", pady=8)
        prev_button = Button(nav_frame, image=self.left_icon, command=self.previous_page)
        prev_button.pack(side="left", padx=10)
        setup_widget(prev_button, self.tooltip_label, text="Previous meme page", packing=False)
        random_button = Button(nav_frame, text="Random memes", command=self.random_memes)
        random_button.pack(side="left", padx=10)
        setup_widget(random_button, self.tooltip_label, text="Shuffle to random memes", packing=False)
        next_button = Button(nav_frame, image=self.right_icon, command=self.next_page)
        next_button.pack(side="left", padx=10)
        setup_widget(next_button, self.tooltip_label, text="Next meme page", packing=False)

        # Grid holding the meme thumbnails (centered, no scrollbar).
        self.grid_frame = Frame(self.browser, bg=WIN98_DESKTOP)
        self.grid_frame.pack(side="top", expand=True)

        # Put the cursor in the search bar as soon as the browser opens.
        self.search_entry.focus_set()

        # Load the meme library (title + tags + images)
        self.meme_list = []
        self.displayed_images = []
        self.image_cache = {}
        self.selected_image = None  # Track the currently selected image
        self.load_images()

    def set_placeholder(self, event):
        """Add the placeholder on the search bar."""
        if not self.search_var.get():
            # Temporarily disable trace
            self.search_var.trace_remove("write", self.search_trace_id)
            self.search_var.set(self.placeholder_text)
            self.search_entry.config(fg='gray')
            # Re-enable trace
            self.search_trace_id = self.search_var.trace_add(
                "write", lambda *args: self.on_search_change(
                    self.search_var, *args)
            )

    def clear_placeholder(self, event):
        """Clear the placeholder from the search bar."""
        if self.search_var.get() == self.placeholder_text:
            # Temporarily disable trace
            self.search_var.trace_remove("write", self.search_trace_id)
            self.search_var.set('')
            self.search_entry.config(fg='black')
            # Re-enable trace
            self.search_trace_id = self.search_var.trace_add(
                "write", lambda *args: self.on_search_change(
                    self.search_var, *args)
            )

    @staticmethod
    def clear_all(event):
        """Clear text from the search Entry."""
        event.widget.delete(0, 'end')  # Delete all text
        return 'break'  # Prevent default behavior

    def load_images(self):
        """Load the meme library and display the first page."""
        config = Config()
        config.loading.play(loops=1)
        self.meme_list = load_meme_library(config.MEME_FOLDER, config.MEME_INDEX)
        self.processed_memes = self.meme_list
        logger.info("Loaded %i memes from the library.", len(self.meme_list))
        self.display_images()
        config.loading.fadeout(200)

    def display_images(self):
        """Display the current page of memes in the grid (animated GIFs play)."""
        # Stop animations from the previous page before rebuilding the grid.
        for lbl in getattr(self, "animated_labels", []):
            job = getattr(lbl, "_anim_job", None)
            if job:
                self.browser.after_cancel(job)
        self.animated_labels = []

        for widget in self.grid_frame.winfo_children():
            widget.destroy()

        self.displayed_images.clear()

        row = 0
        column = 0

        start = (self.page - 1) * self.per_page
        for meme in self.processed_memes[start: start + self.per_page]:
            cached = self.image_cache.get(meme.path)
            if cached is None:
                cached = self._load_thumbnail(meme.path)
                self.image_cache[meme.path] = cached

            if isinstance(cached, tuple):  # animated GIF: (frames, durations)
                frames, durations = cached
                photo = frames[0]
            else:
                frames = durations = None
                photo = cached

            lbl = Label(self.grid_frame, image=photo, cursor="hand2", bg=WIN98_DESKTOP)
            lbl.image = cached  # keep a reference (single PhotoImage or frame list)

            # Use grid to position the images in rows and columns
            lbl.grid(row=row, column=column, padx=5, pady=5)

            setup_widget(lbl, self.tooltip_label,
                         text=meme.title, packing=False)
            lbl.bind("<Double-Button-1>", lambda e,
                     path=meme.path: self.send_back_meme(path))
            lbl.bind("<Button-1>", lambda e,
                     label=lbl: self.select_image(e, label))

            self.displayed_images.append(lbl)
            if frames:
                self.animated_labels.append(lbl)
                self._animate_thumb(lbl, frames, durations, 0)

            # Move to the next column
            column += 1
            if column == self.columns:
                column = 0
                row += 1

    def _load_thumbnail(self, path: Path):
        """Return a thumbnail: a PhotoImage, or (frames, durations) for a GIF."""
        img = Image.open(path)
        if getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1:
            frames = []
            durations = []
            for frame in ImageSequence.Iterator(img):
                thumb = frame.convert("RGBA")
                thumb.thumbnail((self.image_size, self.image_size))
                frames.append(ImageTk.PhotoImage(thumb))
                durations.append(max(20, frame.info.get("duration", 100)))
            return (frames, durations)
        img.thumbnail((self.image_size, self.image_size))
        return ImageTk.PhotoImage(img)

    def _animate_thumb(self, label: Label, frames: list, durations: list, index: int):
        """Advance one animated thumbnail, rescheduling until its label is gone."""
        if not label.winfo_exists():
            return
        label.config(image=frames[index])
        nxt = (index + 1) % len(frames)
        label._anim_job = self.browser.after(
            durations[index], lambda: self._animate_thumb(label, frames, durations, nxt))

    def on_search_change(self, search_var: StringVar, *args) -> None:
        """Apply a delay of a brief moment for the filtering."""
        if search_var.get() == self.placeholder_text:
            return None

        # Cancel any previously scheduled job
        if self.debounce_job is not None:
            self.browser.after_cancel(self.debounce_job)

        # Schedule a new job after a certain time
        self.debounce_job = self.browser.after(
            700, lambda: self.filter_images(search_var))

    def filter_images(self, search_var: StringVar) -> None:
        """Filter memes by matching the query against their title and tags."""
        if search_var.get() == self.placeholder_text:
            return None

        search_text = search_var.get().lower()  # Get the live search text
        config = Config()
        config.loading.play(loops=1)

        # Match every whitespace-separated term against the title+tags blob.
        terms = search_text.split()
        self.processed_memes = [
            meme for meme in self.meme_list
            if all(term in meme.search_key for term in terms)
        ]
        self.page = 1
        self.display_images()
        config.loading.fadeout(200)

    def select_image(self, event, lbl: Label):
        """Highlight the clicked thumbnail in the grid."""
        # Remove the border from the previously selected image
        if self.selected_image:
            self.selected_image.config(borderwidth=0, relief="flat")

        # Add a border to the selected image (groove style)
        lbl.config(borderwidth=3, relief="groove")

        # Store the currently selected image
        self.selected_image = lbl

    def send_back_meme(self, meme_path: Path):
        """Send the selected meme to the main window."""
        logger.info("Sending out meme '%s'", meme_path.name)
        open_image(self.root,
                   self.root_left_frame, self.root_button_frame, self.root_canvas, meme_path)
        self.browser.destroy()

    def random_memes(self):
        """Shuffle the whole library and show a random first page."""
        config = Config()
        config.loading.play(loops=1)
        self.processed_memes = random.sample(self.meme_list, len(self.meme_list))
        self.page = 1
        self.display_images()
        config.loading.fadeout(200)

    def previous_page(self):
        """Previous meme page."""
        if self.page > 1:
            config = Config()
            self.page -= 1
            config.loading.play(loops=1)
            self.display_images()
            config.loading.fadeout(200)

    def next_page(self):
        """Next meme page."""
        last_page = (len(self.processed_memes) + self.per_page - 1) // self.per_page
        if self.page < last_page:
            config = Config()
            self.page += 1
            config.loading.play(loops=1)
            self.display_images()
            config.loading.fadeout(200)
