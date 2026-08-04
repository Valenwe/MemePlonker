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
    # Force UTF-8 at the Tcl/Tk boundary so accented / special characters
    # (é, ç, ...) are handled correctly regardless of the OS locale.
    root.tk.call("encoding", "system", "utf-8")
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

    # All buttons widgets
    memes_button = Button(button_frame, image=memes_icon, command=lambda: MemeBrowser(
        root, left_frame, button_frame, canvas))
    setup_widget(memes_button, tooltip_label, "Browse meme library")

    image_button = Button(button_frame, image=image_icon,
                        command=lambda: open_image(root, left_frame, button_frame, canvas))
    setup_widget(image_button, tooltip_label, "Add image")

    text_button = Button(button_frame, image=text_icon,
                        command=lambda: add_text(canvas))
    setup_widget(text_button, tooltip_label, "Add text")

    bring_up_button = Button(button_frame, image=bring_up_icon,
                        command=lambda: bring_up(canvas))
    setup_widget(bring_up_button, tooltip_label, "Bring selected item to the foreground")

    crop_button = Button(button_frame, image=crop_icon,
                        command=lambda: auto_crop(root, left_frame, button_frame, canvas))
    setup_widget(crop_button, tooltip_label, "Auto crop working zone")

    delete_button = Button(button_frame, image=delete_icon,
                        command=lambda: delete_object(canvas))
    setup_widget(delete_button, tooltip_label, "Delete object")
    root.bind("<Delete>", lambda e: delete_object(canvas))

    save_button = Button(button_frame, image=save_icon,
                        command=lambda: save_canvas_as_image(canvas))
    setup_widget(save_button, tooltip_label, "Save image")

    exit_button = Button(button_frame, image=exit_icon,
                        command=lambda: exit(0))
    setup_widget(exit_button, tooltip_label, "Exit")

    # Shrink the toolbar to exactly fit the buttons and hand the freed width to
    # the canvas, so no desktop background shows to the right of the buttons.
    root.update_idletasks()
    toolbar_width = button_frame.winfo_reqwidth() + 2 * int(left_frame.cget("bd"))
    config.LEFT_FRAME_WIDTH = toolbar_width
    left_frame.pack_propagate(False)
    left_frame.config(width=toolbar_width)
    canvas.config(width=config.WIDTH - toolbar_width)

    root.mainloop()


if __name__ == "__main__":
    main()
