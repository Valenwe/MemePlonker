import logging
from os import environ
from sys import exit
from tkinter import Button, Canvas, Frame, Label, PhotoImage, Tk

from screeninfo.screeninfo import get_monitors

from meme_plonker.canvas_operations import (
    add_text,
    auto_crop,
    bring_up,
    delete_object,
    finalize_transform,
    nudge_selected,
    on_drag,
    on_paste,
    open_image,
    refresh_panels,
)
from meme_plonker.canvas_selection import on_item_click
from meme_plonker.config import WIN98_DESKTOP, WIN98_FACE, WIN98_TOOLTIP, Config, setup_widget
from meme_plonker.meme_browsing import MemeBrowser
from meme_plonker.saving_canvas import copy_canvas_to_clipboard, save_canvas_as_image


def main():
    config = Config()
    # Verbose per-frame logs are opt-in via MEMEPLONKER_DEBUG (1/true/yes/on);
    # otherwise only INFO and above are shown.
    debug = environ.get("MEMEPLONKER_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    root = Tk()
    # NOTE: do NOT override Tcl's system encoding here. On Tk 8.6 (Windows) the
    # OS delivers characters through the ANSI (cp1252) narrow-char path; forcing
    # it to "utf-8" misdecodes typed accents (é è ê ë), which is the opposite of
    # what we want. The cp1252 default already covers Western-European accents,
    # and Python/PIL keep the text as proper Unicode for the saved image.
    root.configure(bg=WIN98_DESKTOP)

    # Calculate the window ratio depending on the screen size
    monitor = get_monitors()[0]
    screen_width, screen_height = monitor.width, monitor.height
    config.update_dimensions(screen_width, screen_height)

    # Calculate the position to center the window
    x_position = (screen_width // 2) - (config.WIDTH // 2)
    y_position = (screen_height // 2) - (config.HEIGHT // 2)
    root.geometry(f"{config.WIDTH}x{config.HEIGHT}+{x_position}+{y_position}")

    root.title("Meme Plonker")
    root.resizable(0, 0)
    # Play the click sounds for any click anywhere in the app (all windows):
    # click.mp3 on press and click_release.mp3 on release.
    root.bind_all("<Button-1>", lambda event: config.click.play(), add="+")
    root.bind_all("<ButtonRelease-1>", lambda event: config.click_release.play(), add="+")
    root.bind('<Control-v>', lambda event: on_paste(event, root, left_frame, button_frame, canvas))
    root.bind('<Control-c>', lambda event: copy_canvas_to_clipboard(canvas))
    icon = PhotoImage(file=config.SRC_FOLDER / 'icon.png')
    root.iconphoto(False, icon)

    # Left side panel (raised gray toolbar, Windows 98 style)
    left_frame = Frame(root, width=config.LEFT_FRAME_WIDTH,
                    height=config.HEIGHT, background=WIN98_FACE,
                    relief="raised", bd=2)
    left_frame.pack(side="left", fill="y")

    # Create a frame inside left_frame for centering the buttons
    button_frame = Frame(left_frame, background=WIN98_FACE)
    button_frame.pack(side="top", fill="x", expand=True)

    # Image editing canvas (highlightthickness=0 avoids a stray border strip
    # showing beside the content, e.g. on the right after auto-crop)
    canvas = Canvas(root, width=config.WIDTH - config.LEFT_FRAME_WIDTH,
                    height=config.HEIGHT, bg="white", highlightthickness=0)
    canvas.pack(side="right")

    canvas.bind("<ButtonPress-1>", lambda event: on_item_click(event, canvas))
    canvas.bind("<B1-Motion>", lambda event: on_drag(event, canvas))
    canvas.bind("<ButtonRelease-1>", lambda event: finalize_transform(event, canvas))

    # Arrow keys nudge the selected element in the matching direction.
    nudge_step = 1
    root.bind("<Left>", lambda event: nudge_selected(canvas, -nudge_step, 0))
    root.bind("<Right>", lambda event: nudge_selected(canvas, nudge_step, 0))
    root.bind("<Up>", lambda event: nudge_selected(canvas, 0, -nudge_step))
    root.bind("<Down>", lambda event: nudge_selected(canvas, 0, nudge_step))

    # All used icons
    memes_icon = config.load_resized_icon("memes.png")
    image_icon = config.load_resized_icon("new_image.png")
    text_icon = config.load_resized_icon("text.png")
    bring_up_icon = config.load_resized_icon("ding.png")
    crop_icon = config.load_resized_icon("crop.png")
    delete_icon = config.load_resized_icon("delete.png")
    save_icon = config.load_resized_icon("save.png")
    exit_icon = config.load_resized_icon("exit.png")

    # Tooltip window (classic pale-yellow bordered hint)
    tooltip_label = Label(root, text="...", bg=WIN98_TOOLTIP,
                        relief="solid", bd=1)
    tooltip_label.place_forget()

    # All button widgets. They are gridded (not packed) by relayout_toolbar below,
    # so when the window is too short to stack them in one column they reflow into
    # extra columns and the toolbar widens to keep every button visible.
    memes_button = Button(button_frame, image=memes_icon, command=lambda: MemeBrowser(
        root, left_frame, button_frame, canvas))
    setup_widget(memes_button, tooltip_label, "Browse meme library", packing=False)

    image_button = Button(button_frame, image=image_icon,
                        command=lambda: open_image(root, left_frame, button_frame, canvas))
    setup_widget(image_button, tooltip_label, "Add image", packing=False)

    text_button = Button(button_frame, image=text_icon,
                        command=lambda: add_text(canvas))
    setup_widget(text_button, tooltip_label, "Add text", packing=False)

    bring_up_button = Button(button_frame, image=bring_up_icon,
                        command=lambda: bring_up(canvas))
    setup_widget(bring_up_button, tooltip_label, "Bring selected item to the foreground", packing=False)

    crop_button = Button(button_frame, image=crop_icon,
                        command=lambda: auto_crop(root, left_frame, button_frame, canvas))
    setup_widget(crop_button, tooltip_label, "Auto crop working zone", packing=False)

    delete_button = Button(button_frame, image=delete_icon,
                        command=lambda: delete_object(canvas))
    setup_widget(delete_button, tooltip_label, "Delete object", packing=False)
    root.bind("<Delete>", lambda e: delete_object(canvas))

    save_button = Button(button_frame, image=save_icon,
                        command=lambda: save_canvas_as_image(canvas))
    setup_widget(save_button, tooltip_label, "Save image", packing=False)

    exit_button = Button(button_frame, image=exit_icon,
                        command=lambda: exit(0))
    setup_widget(exit_button, tooltip_label, "Exit", packing=False)

    toolbar_buttons = [memes_button, image_button, text_button, bring_up_button,
                       crop_button, delete_button, save_button, exit_button]

    # --- Reflowing toolbar --------------------------------------------------
    btn_padx, btn_pady = 6, 4
    border = 2 * int(left_frame.cget("bd"))
    left_frame.pack_propagate(False)

    root.update_idletasks()  # so the buttons report their real icon size
    slot_w = toolbar_buttons[0].winfo_reqwidth() + 2 * btn_padx
    slot_h = toolbar_buttons[0].winfo_reqheight() + 2 * btn_pady

    # The window may shrink until only one row of buttons is left; below that the
    # buttons reflow sideways instead of disappearing.
    config.MINIMUM_HEIGHT = slot_h + border
    canvas_min = config.MINIMUM_WIDTH  # smallest slice of canvas kept visible

    toolbar_state = {"rows": 0}

    def reflow_buttons(available_height: int) -> None:
        """Grid the buttons to fit the height and size the toolbar.

        Sets config.LEFT_FRAME_WIDTH but leaves the window/canvas width alone, so a
        caller can settle the toolbar width for a target height *before* it sizes the
        window (auto-crop relies on this to hug the content exactly).
        """
        rows = max(1, int(available_height) // slot_h)
        if rows == toolbar_state["rows"]:
            return
        toolbar_state["rows"] = rows
        for index, button in enumerate(toolbar_buttons):
            button.grid_configure(row=index % rows, column=index // rows,
                                  padx=btn_padx, pady=btn_pady)
        columns = -(-len(toolbar_buttons) // rows)  # ceil division
        config.LEFT_FRAME_WIDTH = columns * slot_w + border
        left_frame.config(width=config.LEFT_FRAME_WIDTH)

    def relayout_toolbar(available_height: int) -> None:
        """Reflow the toolbar, then keep the window wide enough to show it plus a
        little canvas and resize the canvas to fill the rest."""
        reflow_buttons(available_height)
        # Keep the window wide enough for the whole toolbar plus a little canvas so
        # the reflowed buttons are never clipped.
        min_total = config.LEFT_FRAME_WIDTH + canvas_min
        if config.WIDTH < min_total:
            config.WIDTH = min(config.MAXIMUM_WIDTH, min_total)
            root.geometry(f"{config.WIDTH}x{config.HEIGHT}")
        canvas.config(width=max(1, config.WIDTH - config.LEFT_FRAME_WIDTH))

    # Let canvas_operations (auto-crop / add image) settle the toolbar width for a
    # new height before it sizes the window.
    config.reflow_buttons = reflow_buttons

    # Re-flow on any height change (grip drag, auto-crop, add image all resize
    # left_frame). Drive it off config.HEIGHT — the authoritative value, since the
    # window resizes only through our own code — so every path stays consistent.
    left_frame.bind("<Configure>", lambda event: relayout_toolbar(config.HEIGHT))
    relayout_toolbar(config.HEIGHT)  # initial layout

    # Bottom-right resize grip: drag to freely resize the window/working area,
    # clamped to the configured minimum and maximum (the window is otherwise fixed
    # via resizable(0, 0), so we drive the config-based layout ourselves).
    grip_size = config.HANDLE_SIZE + 8
    grip = Canvas(root, width=grip_size, height=grip_size, bg=WIN98_FACE,
                  highlightthickness=0, cursor="bottom_right_corner")
    # Classic Windows 98 sizegrip: diagonal white highlight + gray shadow lines.
    for line_offset in range(3, grip_size, 4):
        grip.create_line(grip_size, line_offset, line_offset, grip_size, fill="white")
        grip.create_line(grip_size, line_offset + 1, line_offset + 1, grip_size, fill="#808080")
    grip.place(relx=1.0, rely=1.0, anchor="se")

    resize_origin: dict[str, tuple[int, int, int, int]] = {}

    def raise_grip():
        # Canvas.lift() is shadowed by tag_raise (which raises canvas *items* and
        # needs an id), so raise the grip *widget* in the window stacking order.
        grip.tk.call("raise", grip._w)

    def start_window_resize(event):
        resize_origin["at"] = (event.x_root, event.y_root, config.WIDTH, config.HEIGHT)

    def do_window_resize(event):
        if "at" not in resize_origin:
            return
        start_x, start_y, start_w, start_h = resize_origin["at"]
        config.WIDTH = max(config.MINIMUM_WIDTH,
                           min(config.MAXIMUM_WIDTH, start_w + event.x_root - start_x))
        config.HEIGHT = max(config.MINIMUM_HEIGHT,
                            min(config.MAXIMUM_HEIGHT, start_h + event.y_root - start_y))
        # Lightweight live update (avoids the toolbar re-pack flicker of a full
        # refresh). relayout_toolbar reflows the buttons and sets the toolbar/canvas
        # widths (growing the window if the buttons wrapped).
        canvas.config(height=config.HEIGHT)
        root.geometry(f"{config.WIDTH}x{config.HEIGHT}")
        relayout_toolbar(config.HEIGHT)
        raise_grip()

    def end_window_resize(event):
        resize_origin.clear()
        refresh_panels(root, left_frame, button_frame, canvas)
        relayout_toolbar(config.HEIGHT)
        raise_grip()

    grip.bind("<ButtonPress-1>", start_window_resize)
    grip.bind("<B1-Motion>", do_window_resize)
    grip.bind("<ButtonRelease-1>", end_window_resize)

    root.mainloop()


if __name__ == "__main__":
    main()
