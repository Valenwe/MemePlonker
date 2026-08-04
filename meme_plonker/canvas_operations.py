import logging
import tkinter as ttk
from tkinter import Button, Entry, Label, colorchooser, filedialog, simpledialog

from PIL import Image, ImageGrab, ImageSequence, ImageTk

from meme_plonker.canvas_rotation import render_image, update_selection_geometry
from meme_plonker.canvas_selection import clear_selection_box, create_selection_box
from meme_plonker.config import WIN98_FACE, Config, TkObject

logger: logging.Logger = logging.getLogger(__name__)


def refresh_panels(root: ttk.Tk, left_frame: ttk.Frame, button_frame: ttk.Frame, canvas: ttk.Canvas) -> None:
    """Refresh the panels and buttons."""
    config = Config()
    canvas.config(width=config.WIDTH - config.LEFT_FRAME_WIDTH,
                  height=config.HEIGHT)
    left_frame.pack_propagate(False)  # Prevent shrinking

    # Force left_frame to retain its size and prevent duplications
    left_frame.config(width=config.LEFT_FRAME_WIDTH,
                      height=config.HEIGHT, background=WIN98_FACE)
    left_frame.pack_forget()
    left_frame.pack(side="left", fill="y")

    # Ensure button_frame is refreshed properly
    button_frame.pack_forget()
    button_frame.pack(side="top", fill="x", expand=True)

    # Resize in place: set the size only (no +x+y). Re-applying winfo_x/y would
    # drift the window down by the title-bar height each time on X11/Debian.
    root.geometry(f"{config.WIDTH}x{config.HEIGHT}")


def open_image(root: ttk.Tk, left_frame: ttk.Frame, button_frame: ttk.Frame, canvas: ttk.Canvas, filepath: str | None = None) -> None:
    """Event triggered when adding a new image to the board."""

    if not filepath:
        # Patterns must be space-separated (not ';'-separated) to work on Linux/GTK,
        # and are matched case-sensitively there, so include upper-case variants too.
        image_patterns = " ".join(
            f"*.{ext} *.{ext.upper()}"
            for ext in ("jpg", "jpeg", "png", "gif", "bmp")
        )
        filepath = filedialog.askopenfilename(
            parent=root,
            title="Open Image File",
            filetypes=[("Image Files", image_patterns), ("All Files", "*")])

    if filepath:
        image: Image.Image = Image.open(filepath)
        process_new_image(image, root, left_frame, button_frame, canvas)


def process_new_image(image: Image.Image, root: ttk.Tk, left_frame: ttk.Frame, button_frame: ttk.Frame, canvas: ttk.Canvas):
    """Display a new image to the canvas."""
    config = Config()

    # Pull out every frame first (an animated GIF would otherwise be flattened by
    # convert()); a still image is just a single frame.
    animated = getattr(image, "is_animated", False) and getattr(image, "n_frames", 1) > 1
    if animated:
        frames = [f.convert("RGBA") for f in ImageSequence.Iterator(image)]
        durations = [max(20, f.info.get("duration", 100)) for f in ImageSequence.Iterator(image)]
    else:
        frames = [image.convert("RGBA") if image.mode != "RGBA" else image]
        durations = []
    base_image = frames[0]

    # Resize (keeping ratio) so it takes at most half the screen. All GIF frames
    # scale by the same factor.
    max_img_width = config.MAXIMUM_WIDTH // 2
    max_img_height = config.MAXIMUM_HEIGHT // 2
    scale = min(max_img_width / base_image.width, max_img_height / base_image.height, 1.0)
    if scale < 1.0:
        new_size = (max(1, round(base_image.width * scale)), max(1, round(base_image.height * scale)))
        frames = [f.resize(new_size, Image.LANCZOS) for f in frames]
        base_image = frames[0]

    img_width, img_height = base_image.size

    # Grow the window (up to the screen) so the image fits beside the toolbar.
    new_width = min(config.MAXIMUM_WIDTH, max(config.WIDTH, img_width + config.LEFT_FRAME_WIDTH))
    new_height = min(config.MAXIMUM_HEIGHT, max(config.HEIGHT, img_height))
    if new_width > config.WIDTH or new_height > config.HEIGHT:
        config.WIDTH, config.HEIGHT = new_width, new_height
        refresh_panels(root, left_frame, button_frame, canvas)

    photo_image: ttk.PhotoImage = ImageTk.PhotoImage(base_image)
    img_obj: int = canvas.create_image(0, 0, anchor="nw", image=photo_image)

    # Show a "select" hand cursor while hovering the image.
    canvas.tag_bind(img_obj, "<Enter>", lambda e: canvas.config(cursor="hand2"))
    canvas.tag_bind(img_obj, "<Leave>", lambda e: canvas.config(cursor=""))

    # Remember the picture's on-screen size so later resize/rotation stay crisp.
    tk_object = TkObject(img_obj, base_image)
    tk_object.size = base_image.size
    if animated:
        tk_object.frames = frames
        tk_object.frame_durations = durations
    config.objects.append(tk_object)
    config.images.append((img_obj, photo_image))
    canvas.image = config.images
    config.selected_item = img_obj
    create_selection_box(canvas, img_obj)

    if animated:
        _start_animation(canvas, tk_object)


def _start_animation(canvas: ttk.Canvas, obj: TkObject):
    """Cycle an animated GIF's frames on the canvas via Tk's after loop."""
    config = Config()

    def advance():
        current = config.get_object(obj.id)
        if not current or not current.frames:
            return
        current.frame_index = (current.frame_index + 1) % len(current.frames)
        render_image(canvas, current, fast=True)
        current.anim_id = canvas.after(current.frame_durations[current.frame_index], advance)

    obj.anim_id = canvas.after(obj.frame_durations[0], advance)


def move_selected(canvas: ttk.Canvas, dx: int, dy: int):
    """Move the selected object and its selection outline/handles by (dx, dy).

    Moving the existing items (instead of recreating them) keeps dragging and
    arrow-key nudging smooth even on big images.
    """
    config = Config()
    obj = config.get_object(config.selected_item) if config.selected_item else None
    if not obj:
        return

    canvas.move(obj.id, dx, dy)
    if config.selection_rect:
        canvas.move(config.selection_rect, dx, dy)
    for handle in obj.resize_handles.values():
        canvas.move(handle, dx, dy)
    if obj.rotate_handle:
        canvas.move(obj.rotate_handle, dx, dy)


def nudge_selected(canvas: ttk.Canvas, dx: int, dy: int):
    """Shift the selected object by a small step (used by the arrow keys)."""
    move_selected(canvas, dx, dy)


def on_drag(event, canvas: ttk.Canvas):
    """Event triggered when dragging an object around."""
    config = Config()
    # A resize/rotate handle is driving this drag: let it own the motion.
    if config.interacting_handle or not config.selected_item:
        return None

    dx = event.x - config.last_x
    dy = event.y - config.last_y
    move_selected(canvas, dx, dy)
    config.last_x, config.last_y = event.x, event.y


def finalize_transform(event, canvas: ttk.Canvas):
    """On mouse release, re-render the selected image at full quality."""
    config = Config()

    # Re-render crisply only after a handle interaction (resize/rotate).
    was_transforming = config.interacting_handle
    config.interacting_handle = False

    if was_transforming and config.selected_item and (obj := config.get_object(config.selected_item)):
        if isinstance(obj.data, Image.Image):
            render_image(canvas, obj, fast=False)
            update_selection_geometry(canvas, obj.id)


def on_paste(event, root: ttk.Tk, left_frame: ttk.Frame, button_frame: ttk.Frame, canvas: ttk.Canvas):
    """Pasting image detection (raw bitmap or copied image files)."""
    content = ImageGrab.grabclipboard()

    if isinstance(content, Image.Image):
        logger.info("Pasting bitmap image from clipboard.")
        process_new_image(content, root, left_frame, button_frame, canvas)
    elif isinstance(content, list):
        # Windows copies files as a list of paths; add every readable image.
        for path in content:
            try:
                image = Image.open(path)
            except (OSError, ValueError):
                logger.warning("Clipboard file is not an image: %s", path)
                continue
            logger.info("Pasting image file from clipboard: %s", path)
            process_new_image(image, root, left_frame, button_frame, canvas)


def delete_object(canvas: ttk.Canvas):
    """Action to delete the current selected item."""
    config = Config()
    if config.selected_item and (obj := config.get_object(config.selected_item)):
        if obj.anim_id:
            canvas.after_cancel(obj.anim_id)
        clear_selection_box(canvas)
        canvas.delete(config.selected_item)

        if isinstance(obj.data, Image.Image):
            config.images = [
                item for item in config.images if item[0] != config.selected_item
            ]
            canvas.image = config.images

        config.objects.remove(obj)
        config.selected_item = None
        config.trash.play()
        logger.info("[DELETED] Deleted object n°%i", obj.id)


class TextColorDialog(simpledialog.Dialog):
    """A single dialog to type text and pick its color (defaults to black)."""

    def __init__(self, parent, title: str, initial_text: str = "", initial_color: str = "black"):
        self.initial_text = initial_text
        self.chosen_color = initial_color or "black"
        super().__init__(parent, title)

    def body(self, master):
        Label(master, text="Enter your text:").grid(row=0, column=0, columnspan=2, sticky="w")
        self.entry = Entry(master, width=32)
        self.entry.insert(0, self.initial_text)
        self.entry.grid(row=1, column=0, columnspan=2, pady=(0, 8))

        Label(master, text="Color:").grid(row=2, column=0, sticky="w", pady=(0, 4))
        self.color_button = Button(master, width=12, bg=self.chosen_color,
                                   relief="raised", bd=3, command=self._pick_color)
        self.color_button.grid(row=2, column=1, sticky="w", pady=(0, 4))
        return self.entry  # initial focus on the text field

    def _pick_color(self):
        color = colorchooser.askcolor(title="Choose a color",
                                      initialcolor=self.chosen_color, parent=self)[1]
        if color:
            self.chosen_color = color
            self.color_button.config(bg=color)

    def apply(self):
        self.result = (self.entry.get(), self.chosen_color)


def add_text(canvas: ttk.Canvas):
    """Event triggered to add text (with a color picker, default black)."""
    config = Config()
    dialog = TextColorDialog(canvas, "Add text", initial_color=config.pen_color)
    if not dialog.result:
        return

    text, color = dialog.result
    if not text:
        return

    text_obj = canvas.create_text(
        100, 100, text=text, fill=color, font=(config.FONT_FAMILY, 20))
    config.objects.append(TkObject(text_obj, text))
    canvas.tag_bind(text_obj, "<Double-Button-1>",
                    lambda event, obj=text_obj: edit_text(canvas, obj))
    config.selected_item = text_obj
    create_selection_box(canvas, text_obj)
    logger.debug("[TEXT] Box created.")


def edit_text(canvas: ttk.Canvas, text_obj: int):
    """Open a dialog to edit the text and its color."""
    config = Config()
    dialog = TextColorDialog(canvas, "Edit text",
                             initial_text=canvas.itemcget(text_obj, 'text'),
                             initial_color=canvas.itemcget(text_obj, 'fill'))
    if not dialog.result:
        return

    new_text, new_color = dialog.result
    if new_text:
        canvas.itemconfig(text_obj, text=new_text)
        config.get_object(text_obj).data = new_text
    if new_color:
        canvas.itemconfig(text_obj, fill=new_color)

    # The text may have changed size: refresh the selection outline.
    update_selection_geometry(canvas, text_obj)


def bring_up(canvas: ttk.Canvas):
    """Bring selected item to the foreground."""
    config = Config()
    if obj := config.get_object(config.selected_item):
        config.ding.play()
        # Change the display order of the clicked object
        canvas.tag_raise(config.selected_item)
        config.objects.remove(obj)
        config.objects.append(obj)

        # Keep the selection outline and handles above the raised object.
        for handle in obj.resize_handles.values():
            canvas.tag_raise(handle)
        if obj.rotate_handle:
            canvas.tag_raise(obj.rotate_handle)
        if config.selection_rect:
            canvas.tag_raise(config.selection_rect)


def auto_crop(root: ttk.Tk, left_frame: ttk.Frame, button_frame: ttk.Frame, canvas: ttk.Canvas):
    """Auto crop the canvas working zone."""
    config = Config()
    config.crop.play()
    maximum_width = 0
    maximum_height = 0

    for obj in config.objects:
        _x1, _y1, x2, y2 = canvas.bbox(obj.id)
        x2 = min(config.MAXIMUM_WIDTH, x2 + config.LEFT_FRAME_WIDTH)
        y2 = min(config.MAXIMUM_HEIGHT, y2)
        if x2 > maximum_width:
            maximum_width = x2
        if y2 > maximum_height:
            maximum_height = y2

    # Make that the auto crop doesnt go below the minimum
    config.HEIGHT = max(config.MINIMUM_HEIGHT, maximum_height)
    config.WIDTH = max(config.MINIMUM_WIDTH, maximum_width)
    refresh_panels(root, left_frame, button_frame, canvas)
