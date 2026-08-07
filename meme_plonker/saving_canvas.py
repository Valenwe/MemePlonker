import io
import logging
import os
import shutil
import subprocess
import sys
import threading
import tkinter as ttk
from tkinter import filedialog
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageFont

from meme_plonker.config import Config

logger: logging.Logger = logging.getLogger(__name__)


def crop_image_to_valid_coordinates(image: Image.Image, coords: tuple[int, int, int, int], canvas_width: int, canvas_height: int) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Crops the image to ensure it stays within valid canvas coordinates and returns the new coordinates."""
    x1, y1, x2, y2 = coords

    # Adjust for negative coordinates
    crop_left = max(x1, 0)
    crop_top = max(y1, 0)
    crop_right = min(x2, canvas_width)
    crop_bottom = min(y2, canvas_height)

    # If there's no visible region after cropping, return None (no need to paste)
    if crop_left >= crop_right or crop_top >= crop_bottom:
        return None, (x1, y1, x2, y2)

    # Crop the image to the valid region
    cropped_image = image.crop(
        (crop_left - x1, crop_top - y1, crop_right - x1, crop_bottom - y1))

    # Return the cropped image and the new coordinates
    return cropped_image, (crop_left, crop_top, crop_right, crop_bottom)


def render_canvas_image(canvas: ttk.Canvas) -> Image.Image:
    """Render every object on the canvas into a single flattened RGBA image."""
    config = Config()
    canvas_width = canvas.winfo_width()
    canvas_height = canvas.winfo_height()

    # Create a blank image with the same size as the canvas
    image = Image.new("RGBA", (canvas_width, canvas_height), (255, 255, 255, 255))

    # Loop through the canvas items and draw them on the image
    for obj in config.objects:
        bbox = canvas.bbox(obj.id)
        if not bbox:
            continue
        x1, y1, x2, y2 = bbox

        # TEXT DRAWING
        if isinstance(obj.data, str):
            text = obj.data
            fill = canvas.itemcget(obj.id, 'fill')

            # Match the PIL font to the text's ACTUAL on-screen height in pixels
            # (from Tk's font metrics) instead of converting points->pixels with a
            # fixed DPI guess. The guess renders too big on some displays (e.g.
            # Debian); this keeps the export the same size as the preview.
            tk_font = tkfont.Font(root=canvas, font=canvas.itemcget(obj.id, "font"))
            target_line = max(1, tk_font.metrics("linespace"))

            # Use the exact bundled font file when available so the saved text
            # matches the preview; otherwise look the family up by name.
            if config.FONT_FILE:
                font_source = str(config.FONT_FILE)
            else:
                font_source = f"{config.FONT_FAMILY.lower().replace(' ', '')}.ttf"
            try:
                # Scale so PIL's line height (ascent+descent) equals Tk's linespace.
                pil_font = ImageFont.truetype(font_source, target_line)
                ascent, descent = pil_font.getmetrics()
                pil_size = max(1, round(target_line * target_line / max(1, ascent + descent)))
                pil_font = ImageFont.truetype(font_source, pil_size)
            except OSError:
                logger.error("Could not load font '%s'.", font_source)
                pil_font = ImageFont.load_default()  # Fallback if font file is missing

            # Draw the text exactly where Tk places it: each line horizontally
            # centred and sitting on its baseline (Tk's ascent below the line-box
            # top), with successive lines stacked by Tk's linespace. Drawing the
            # lines one by one (rather than passing the whole block to PIL) keeps
            # the centring and vertical spacing an exact match for the on-screen
            # preview for multi-line text. A small pad avoids clipping.
            pad = 2
            box_w = max(1, x2 - x1) + 2 * pad
            box_h = max(1, y2 - y1) + 2 * pad
            baseline = pad + tk_font.metrics("ascent")
            text_image = Image.new("RGBA", (box_w, box_h), (255, 255, 255, 0))
            text_draw = ImageDraw.Draw(text_image)
            for line_no, line in enumerate(text.split("\n")):
                text_draw.text((box_w / 2, baseline + line_no * target_line),
                               line, font=pil_font, fill=fill, anchor="ms")

            # Rotate around the centre, then place centred on the canvas text.
            pil_image = text_image.rotate(obj.rotation, expand=True, resample=Image.BICUBIC)
            center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
            px = round(center_x - pil_image.width / 2)
            py = round(center_y - pil_image.height / 2)
            coords = (px, py, px + pil_image.width, py + pil_image.height)

        # IMAGE DRAWING (current frame for an animated GIF)
        elif isinstance(obj.data, Image.Image):
            base = obj.frames[obj.frame_index] if obj.frames else obj.data
            if obj.size:
                base = base.resize(obj.size, Image.LANCZOS)
            pil_image = base.rotate(obj.rotation, expand=True, resample=Image.BICUBIC)
            coords = (x1, y1, x2, y2)
        else:
            continue

        pil_image, coords = crop_image_to_valid_coordinates(
            pil_image, coords, canvas_width, canvas_height)
        if pil_image is not None:
            # Use the layer's own alpha as a mask so the transparent area around
            # text (and the corners of rotated images) does not punch holes.
            image.paste(pil_image, coords, pil_image)

    return image


def _frame_at_time(obj, t_ms: int) -> int:
    """Which frame of an animated object is showing at time t (looping)."""
    cycle = sum(obj.frame_durations)
    t = t_ms % cycle if cycle else 0
    elapsed = 0
    for index, duration in enumerate(obj.frame_durations):
        elapsed += duration
        if t < elapsed:
            return index
    return len(obj.frames) - 1


def render_canvas_gif_frames(canvas: ttk.Canvas) -> tuple[list[Image.Image], int]:
    """Composite the canvas across the GIF timeline. Returns (frames, ms per frame)."""
    config = Config()
    animated = [o for o in config.objects if o.frames]
    if not animated:
        return [render_canvas_image(canvas)], 0

    step = max(20, min(min(o.frame_durations) for o in animated))
    total = max(sum(o.frame_durations) for o in animated)
    frame_count = min(200, max(1, round(total / step)))  # cap to keep files sane

    saved_indices = {o.id: o.frame_index for o in animated}
    frames = []
    for i in range(frame_count):
        for o in animated:
            o.frame_index = _frame_at_time(o, i * step)
        frames.append(render_canvas_image(canvas))
    for o in animated:  # restore the live animation state
        o.frame_index = saved_indices[o.id]
    return frames, step


def _save_animated_gif(frames: list[Image.Image], duration: int, file_path: str):
    """Save composited RGBA frames as a looping animated GIF (shared palette)."""
    first = frames[0].convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=256)
    rest = [f.convert("RGB").quantize(palette=first) for f in frames[1:]]
    first.save(file_path, format="GIF", save_all=True, append_images=rest,
               duration=duration, loop=0, disposal=2)


def _run_in_thread(canvas: ttk.Canvas, work, done) -> None:
    """Run the CPU-bound `work()` off the main thread, then call `done` back on it.

    Tkinter is single-threaded, so every canvas read must already have happened on
    the main thread and been captured in `work`'s closure — `work` itself must only
    touch plain Python/PIL/OS objects. When it finishes, `done(result, error)` is
    scheduled on the main thread (exactly one of the two is not None). The loading
    sound (started by the caller) keeps playing on pygame's own audio thread while
    this runs, so the app stays responsive during a slow encode.
    """
    box: dict[str, object] = {}

    def runner():
        try:
            box["result"] = work()
        except BaseException as exc:  # reported to the caller on the main thread
            box["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()

    def poll():
        if thread.is_alive():
            canvas.after(50, poll)
            return
        done(box.get("result"), box.get("error"))

    canvas.after(50, poll)


def save_canvas_as_image(canvas: ttk.Canvas):
    """Render the canvas and save it. Exports an animated GIF if a GIF is present.

    The actual encoding/writing runs in a background thread so the loading sound
    plays and the UI stays responsive while a big image (or GIF) is written.
    """
    config = Config()
    has_gif = any(obj.frames for obj in config.objects)

    default_ext = ".gif" if has_gif else ".png"
    filetypes = [("PNG Image", "*.png *.PNG")]
    if has_gif:
        filetypes = [("GIF Image", "*.gif *.GIF"), *filetypes]
    file_path = filedialog.asksaveasfilename(
        parent=canvas,
        defaultextension=default_ext,
        filetypes=filetypes,
        initialfile="mysupermeme" + default_ext,
    )
    if not file_path:
        return

    # Loop the loading sound for the whole operation (canvas render + threaded
    # encode); fade it out when the thread reports back.
    config.loading.play(loops=-1)
    try:
        # Canvas reads must stay on the main thread; capture the result and let
        # the thread do only the encode/write.
        if has_gif and file_path.lower().endswith(".gif"):
            frames, duration = render_canvas_gif_frames(canvas)
            work = lambda: _save_animated_gif(frames, duration, file_path)  # noqa: E731
        else:
            image = render_canvas_image(canvas)
            work = lambda: image.save(file_path, format="PNG", subsampling=0, quality=100)  # noqa: E731
    except BaseException:
        config.loading.fadeout(200)
        raise

    def done(_result, error):
        config.loading.fadeout(200)
        if error is not None:
            logger.error("Saving the meme failed: %s", error)
            return
        logger.info("File saved as: %s", file_path)
        config.saved.play()

    _run_in_thread(canvas, work, done)


def copy_canvas_to_clipboard(canvas: ttk.Canvas):
    """Copy the meme to the clipboard — an animated GIF when the canvas has one.

    The clipboard write (and any GIF encoding) runs in a background thread while
    the loading sound plays; the canvas is read up-front on the main thread.
    """
    config = Config()
    has_gif = any(obj.frames for obj in config.objects)

    if sys.platform.startswith("win"):
        prepare = _prepare_clipboard_windows
    elif sys.platform.startswith("linux"):
        prepare = _prepare_clipboard_linux
    else:
        logger.error("Copying to the clipboard is not supported on %s.", sys.platform)
        return

    config.loading.play(loops=-1)
    try:
        # Render on the main thread; `commit` does the encode + OS clipboard call.
        commit = prepare(canvas, has_gif)
    except BaseException:
        config.loading.fadeout(200)
        raise

    def done(copied, error):
        config.loading.fadeout(200)
        if error is not None:
            logger.error("Copying the meme failed: %s", error)
            return
        if copied:
            logger.info("Copied the meme to the clipboard%s.", " (animated GIF)" if has_gif else "")
            config.saved.play()

    _run_in_thread(canvas, commit, done)


def _prepare_clipboard_linux(canvas: ttk.Canvas, has_gif: bool):
    """Render on the main thread; return a thread-safe callable that copies it."""
    if has_gif:
        frames, duration = render_canvas_gif_frames(canvas)

        def commit() -> bool:
            with io.BytesIO() as output:
                _save_animated_gif(frames, duration, output)
                return _bytes_to_clipboard_linux(output.getvalue(), "image/gif")
    else:
        image = render_canvas_image(canvas)

        def commit() -> bool:
            with io.BytesIO() as output:
                image.save(output, "PNG")
                return _bytes_to_clipboard_linux(output.getvalue(), "image/png")

    return commit


def _prepare_clipboard_windows(canvas: ttk.Canvas, has_gif: bool):
    """Render on the main thread; return a thread-safe callable that copies it."""
    # A DIB of the current frame is the universal fallback every app understands.
    base_rgb = render_canvas_image(canvas).convert("RGB")
    gif_frames = gif_duration = None
    if has_gif:
        gif_frames, gif_duration = render_canvas_gif_frames(canvas)

    def commit() -> bool:
        import ctypes

        with io.BytesIO() as output:
            base_rgb.save(output, "BMP")
            dib = output.getvalue()[14:]  # strip the 14-byte BMP file header
        CF_DIB = 8
        entries: list[tuple[int, bytes]] = [(CF_DIB, dib)]

        if gif_frames is not None:
            with io.BytesIO() as output:
                _save_animated_gif(gif_frames, gif_duration, output)
                gif_data = output.getvalue()
            # Expose the animated GIF under the "GIF" format for apps that read it inline.
            register = ctypes.windll.user32.RegisterClipboardFormatW
            register.argtypes = [ctypes.c_wchar_p]
            register.restype = ctypes.c_uint
            gif_format = register("GIF")
            if gif_format:
                entries.append((gif_format, gif_data))
            # Most apps only paste an animated GIF when it arrives as a *file*, so also
            # drop a temp .gif via CF_HDROP (chat apps, browsers, Explorer read this).
            hdrop = _gif_hdrop(gif_data)
            if hdrop:
                CF_HDROP = 15
                entries.append((CF_HDROP, hdrop))

        return _set_clipboard_windows(entries)

    return commit


def _gif_hdrop(gif_data: bytes) -> bytes | None:
    """Write a temp .gif and build a CF_HDROP payload referencing it."""
    import ctypes
    import os
    import tempfile
    from ctypes import wintypes

    try:
        path = os.path.join(tempfile.gettempdir(), "plonker_clipboard.gif")
        with open(path, "wb") as handle:
            handle.write(gif_data)
    except OSError:
        return None

    class DROPFILES(ctypes.Structure):
        _fields_ = [
            ("pFiles", wintypes.DWORD),
            ("x", wintypes.LONG),
            ("y", wintypes.LONG),
            ("fNC", wintypes.BOOL),
            ("fWide", wintypes.BOOL),
        ]

    header = DROPFILES(pFiles=ctypes.sizeof(DROPFILES), x=0, y=0, fNC=0, fWide=1)
    # Wide, double-null-terminated file list (one path).
    file_list = path.encode("utf-16-le") + b"\x00\x00\x00\x00"
    return bytes(header) + file_list


def _set_clipboard_windows(entries: list[tuple[int, bytes]]) -> bool:
    """Put one or more (format, bytes) payloads on the Windows clipboard."""
    import ctypes
    from ctypes import wintypes

    GMEM_MOVEABLE = 0x0002
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    # 64-bit safe signatures (handles must not be truncated to 32-bit ints).
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]

    handles = []
    for fmt, data in entries:
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        handles.append((fmt, handle))

    if not user32.OpenClipboard(0):
        return False
    try:
        user32.EmptyClipboard()
        for fmt, handle in handles:
            user32.SetClipboardData(fmt, handle)
    finally:
        user32.CloseClipboard()
    return True


def _bytes_to_clipboard_linux(payload: bytes, mime: str) -> bool:
    """Put raw bytes of a given MIME type on the Linux clipboard.

    A machine can have wl-copy installed while actually running an X11 session
    (Debian defaults to Xorg on plenty of setups), in which case wl-copy fails
    with "failed to connect to a Wayland server". So we don't just pick the first
    tool that exists: we try each available tool, ordered by the running session,
    until one actually succeeds, and only give up if they all fail.
    """
    tools: list[tuple[str, list[str]]] = []
    if shutil.which("wl-copy"):
        tools.append(("wl-copy", ["wl-copy", "-t", mime]))
    if shutil.which("xclip"):
        tools.append(("xclip", ["xclip", "-selection", "clipboard", "-t", mime]))

    if not tools:
        logger.error("Install 'wl-copy' (Wayland) or 'xclip' (X11) to copy images.")
        return False

    # Try the tool matching the live session first (Wayland vs X11).
    if os.environ.get("WAYLAND_DISPLAY"):
        tools.sort(key=lambda tool: tool[0] != "wl-copy")
    elif os.environ.get("DISPLAY"):
        tools.sort(key=lambda tool: tool[0] != "xclip")

    last_error: Exception | None = None
    for name, command in tools:
        try:
            subprocess.run(command, input=payload, check=True, timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            last_error = exc
            logger.warning("Clipboard tool '%s' unavailable (%s); trying the next one.", name, exc)

    logger.error("No working clipboard tool (last error: %s). On X11 install 'xclip'; "
                 "on Wayland install 'wl-clipboard'.", last_error)
    return False
