import logging
import math
import tkinter as ttk

from PIL import Image

from meme_plonker.canvas_rotation import create_rotation_handle, render_image, update_selection_geometry
from meme_plonker.config import Config, HandlePosition

logger: logging.Logger = logging.getLogger(__name__)


def on_item_click(event, canvas: ttk.Canvas):
    """Event triggered when clicking on the canvas: select, or deselect on empty space."""
    config = Config()

    # Everything sitting directly under the cursor (topmost is last).
    hits = canvas.find_overlapping(event.x, event.y, event.x, event.y)

    # Clicking a resize/rotate handle must not change the current selection.
    for item in reversed(hits):
        tags = canvas.gettags(item)
        if "resize" in tags or "rotate" in tags:
            config.last_x, config.last_y = event.x, event.y
            return None

    # Pick the topmost real object under the cursor (ignore the selection outline).
    target = next((item for item in reversed(hits) if config.get_object(item)), None)

    if target is None:
        # Clicked empty space: deselect everything.
        clear_selection_box(canvas)
        config.selected_item = None
        return None

    config.selected_item = target
    config.last_x, config.last_y = event.x, event.y

    logger.debug("[CLICK] Box created.")
    create_selection_box(canvas, target)


def clear_selection_box(canvas: ttk.Canvas):
    """Remove the selection rectangle and every handle."""
    config = Config()
    if config.selection_rect:
        canvas.delete(config.selection_rect)
        config.selection_rect = None
        logger.debug("[CLEARED] Rectangle.")

    for obj in config.objects:
        for handle in obj.resize_handles.values():
            canvas.delete(handle)
        obj.resize_handles = {}
        if obj.rotate_handle:
            canvas.delete(obj.rotate_handle)
            obj.rotate_handle = None
        logger.debug("[CLEARED] Handles for object n°%i.", obj.id)


def create_selection_box(canvas: ttk.Canvas, obj: int):
    """Create a visible box with handles around the object."""
    config = Config()

    if not obj or not (bbox := canvas.bbox(obj)):
        return None

    if not config.get_object(obj):
        # If we selected no added object (could be a rectangle for instance)
        return None

    # If we actually are selecting something
    x1, y1, x2, y2 = bbox
    clear_selection_box(canvas)

    config.selection_rect = canvas.create_rectangle(
        x1-5, y1-5, x2+5, y2+5, outline="blue", dash=(2, 2))
    create_resize_handles(canvas, obj)
    create_rotation_handle(canvas, obj)


def create_resize_handles(canvas: ttk.Canvas, obj: int):
    """Add handles on the corners of the newly created selection box."""
    config = Config()
    x1, y1, x2, y2 = canvas.bbox(obj)
    handle_positions = {
        HandlePosition.TopLeft: (x1, y1),
        HandlePosition.TopRight: (x2, y1),
        HandlePosition.BottomRight: (x2, y2),
        HandlePosition.BottomLeft: (x1, y2)
    }

    handles: dict[HandlePosition, int] = {}
    half_handle_size = int(config.HANDLE_SIZE / 2)
    for position, (hx, hy) in handle_positions.items():
        handle = canvas.create_rectangle(
            hx-half_handle_size, hy-half_handle_size,
            hx+half_handle_size, hy+half_handle_size,
            fill="red", tags="resize"
        )

        # Flag the interaction so on_drag does not also move the object.
        canvas.tag_bind(handle, "<ButtonPress-1>",
                        lambda event, c=config: setattr(c, "interacting_handle", True))
        # Bind event with specific position info
        canvas.tag_bind(handle, "<B1-Motion>", lambda event, obj=obj,
                        pos=position: resize_object(event, canvas, obj, pos))

        handles[position] = handle
    config.get_object(obj).resize_handles = handles
    logger.debug("[ADDED] Handles.")


def resize_object(event, canvas: ttk.Canvas, obj_id: int, position: HandlePosition):
    """Event triggered when using the handle to resize an object."""
    config = Config()
    x1, y1, x2, y2 = canvas.bbox(obj_id)
    new_x, new_y = event.x, event.y

    match position:
        case HandlePosition.TopLeft:
            new_width = x2 - new_x
            new_height = y2 - new_y
        case HandlePosition.TopRight:
            new_width = new_x - x1
            new_height = y2 - new_y
        case HandlePosition.BottomRight:
            new_width = new_x - x1
            new_height = new_y - y1
        case HandlePosition.BottomLeft:
            new_width = x2 - new_x
            new_height = new_y - y1

    obj = config.get_object(obj_id)
    if isinstance(obj.data, Image.Image):  # Check if it's an image
        if obj.rotation and obj.size:
            # Rotated: the axis-aligned handles no longer correspond to the
            # picture's own width/height, so scale it uniformly about its center
            # (from how much the bounding box grew) to keep its shape.
            center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
            old_diagonal = math.hypot(x2 - x1, y2 - y1) or 1
            new_diagonal = math.hypot(max(10, new_width), max(10, new_height))
            scale = new_diagonal / old_diagonal
            obj.size = (max(10, round(obj.size[0] * scale)),
                        max(10, round(obj.size[1] * scale)))
            render_image(canvas, obj, fast=True)

            # Re-center on the previous center after the size change.
            nx1, ny1, nx2, ny2 = canvas.bbox(obj_id)
            canvas.move(obj_id, center_x - (nx1 + nx2) / 2, center_y - (ny1 + ny2) / 2)
        else:
            # Not rotated: keep the corner opposite the dragged one anchored.
            match position:
                case HandlePosition.TopLeft:
                    canvas.move(obj_id, new_x - x1, new_y - y1)
                case HandlePosition.TopRight:
                    canvas.move(obj_id, 0, new_y - y1)
                case HandlePosition.BottomLeft:
                    canvas.move(obj_id, new_x - x1, 0)

            # Store the intended (unrotated) size and re-render fast for smooth dragging.
            obj.size = (max(10, new_width), max(10, new_height))
            render_image(canvas, obj, fast=True)

    elif isinstance(obj.data, str):  # Resizing text: map the box height to a font size
        # The bounding box spans every line, so divide by the line count to get the
        # per-line height; otherwise multi-line text scales by N lines at once and
        # the font runs away as you drag.
        line_count = obj.data.count("\n") + 1
        new_height = max(10, new_height)
        font_size = max(6, int(new_height / line_count / 1.3))
        canvas.itemconfig(obj_id, font=(config.FONT_FAMILY, font_size))

    else:
        return None

    logger.debug("[RESIZE] Box updated.")

    # Move the outline and handles to match, without recreating them.
    update_selection_geometry(canvas, obj_id)
