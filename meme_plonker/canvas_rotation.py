import logging
import math
import tkinter as ttk

from PIL import Image, ImageTk

from meme_plonker.config import Config, HandlePosition

logger: logging.Logger = logging.getLogger(__name__)


def update_canvas_image(canvas: ttk.Canvas, obj_id: int, pil_image: Image.Image) -> None:
    """Swap the picture displayed for an object and keep a reference to avoid garbage collection."""
    config = Config()
    new_image = ImageTk.PhotoImage(pil_image)
    canvas.itemconfig(obj_id, image=new_image)

    for idx, (existing_id, _) in enumerate(config.images):
        if existing_id == obj_id:
            config.images[idx] = (obj_id, new_image)
            break
    else:
        config.images.append((obj_id, new_image))
    canvas.image = config.images


def render_image(canvas: ttk.Canvas, obj, fast: bool = True) -> None:
    """Re-render an image object from its original data at its stored size and rotation.

    ``fast`` uses cheap filters for smooth live dragging; pass ``False`` on release
    for a crisp final render.
    """
    resize_filter = Image.BILINEAR if fast else Image.LANCZOS
    rotate_filter = Image.BILINEAR if fast else Image.BICUBIC

    # Animated GIFs render their current frame; still images use their data.
    base = obj.frames[obj.frame_index] if obj.frames else obj.data
    if obj.size:
        base = base.resize((max(1, obj.size[0]), max(1, obj.size[1])), resize_filter)
    if obj.rotation:
        base = base.rotate(obj.rotation, expand=True, resample=rotate_filter)
    update_canvas_image(canvas, obj.id, base)


def update_selection_geometry(canvas: ttk.Canvas, obj_id: int) -> None:
    """Reposition the selection rectangle and every handle to the object's current bbox."""
    config = Config()
    obj = config.get_object(obj_id)
    if not obj or not (bbox := canvas.bbox(obj_id)):
        return

    x1, y1, x2, y2 = bbox
    half_handle_size = config.HANDLE_SIZE // 2

    if config.selection_rect:
        canvas.coords(config.selection_rect, x1 - 5, y1 - 5, x2 + 5, y2 + 5)

    handle_positions = {
        HandlePosition.TopLeft: (x1, y1),
        HandlePosition.TopRight: (x2, y1),
        HandlePosition.BottomRight: (x2, y2),
        HandlePosition.BottomLeft: (x1, y2),
    }
    for position, (hx, hy) in handle_positions.items():
        if handle := obj.resize_handles.get(position):
            canvas.coords(handle, hx - half_handle_size, hy - half_handle_size,
                          hx + half_handle_size, hy + half_handle_size)

    if obj.rotate_handle:
        canvas.coords(obj.rotate_handle, *get_bbox_rotation_handle(canvas, obj_id))


def create_rotation_handle(canvas: ttk.Canvas, obj: int):
    """Create the small button responsible of the rotation of the object."""
    config = Config()
    rotation_handle = canvas.create_oval(
        *get_bbox_rotation_handle(canvas, obj), fill="lime", outline="black",
        tags="rotate"
    )

    config.get_object(obj).rotate_handle = rotation_handle

    # Bind the rotate handle to drag event
    canvas.tag_bind(rotation_handle, "<ButtonPress-1>",
                    lambda event: start_rotate(event, canvas, obj))
    canvas.tag_bind(rotation_handle, "<B1-Motion>",
                    lambda event: rotate_object(event, canvas, obj))


def get_bbox_rotation_handle(canvas: ttk.Canvas, obj: int) -> tuple[int, int, int, int]:
    """Get the rotation handle bbox coordinates."""
    config = Config()
    half_handle_size = int(config.HANDLE_SIZE / 2)
    x1, y1, x2, _y2 = canvas.bbox(obj)

    # Create rotation handle (outside the bounding box)
    center_x = (x1 + x2) / 2
    center_y = y1 - config.HANDLE_SIZE
    return (
        center_x - half_handle_size,
        center_y - half_handle_size,
        center_x + half_handle_size,
        center_y + half_handle_size
    )


def start_rotate(event, canvas: ttk.Canvas, obj: int):
    """Start the rotation by saving the initial position."""
    config = Config()
    # Flag the interaction so on_drag does not also move the object.
    config.interacting_handle = True

    # Calculate the center
    x1, y1, x2, y2 = canvas.bbox(obj)
    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2

    # Store the initial mouse position and angle
    config.rotate_x, config.rotate_y = event.x, event.y
    config.initial_angle = get_angle(event.x, event.y, center_x, center_y)

    logger.debug("Rotating from clicked coordinates [%i, %i], angle of %f",
                 config.rotate_x, config.rotate_y, config.initial_angle)


def rotate_object(event, canvas: ttk.Canvas, obj: int):
    """Rotate the object when the mouse is dragged."""
    config = Config()

    # Get center
    x1, y1, x2, y2 = canvas.bbox(obj)
    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2

    # Get the current angle
    current_angle = get_angle(event.x, event.y, center_x, center_y)
    delta_angle = current_angle - config.initial_angle

    # Apply rotation
    config.get_object(obj).rotation += delta_angle  # Store accumulated rotation
    rotate(canvas, obj)  # Apply new rotation

    # Update initial angle for the next movement
    config.initial_angle = current_angle


def get_angle(x: int, y: int, center_x: int, center_y: int) -> float:
    """Calculate the angle between the center of the object and the mouse position."""
    return - math.atan2(y - center_y, x - center_x) * 180 / math.pi


def rotate(canvas: ttk.Canvas, obj_id: int, fast: bool = True):
    """Rotate the object (image or text) around its center from its rotation attribute."""
    config = Config()

    if obj := config.get_object(obj_id):
        if isinstance(obj.data, Image.Image):
            render_image(canvas, obj, fast=fast)
        elif isinstance(obj.data, str):
            canvas.itemconfig(obj.id, angle=obj.rotation)

        # Keep the selection outline and handles glued to the rotated object
        update_selection_geometry(canvas, obj_id)
