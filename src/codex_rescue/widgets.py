"""Small native widgets; no web server, external fonts or network resources."""
from __future__ import annotations
import tkinter as tk

COLORS = {
    "background": "#F4F7F8", "surface": "#FFFFFF", "ink": "#18342E",
    "text": "#304740", "muted": "#62756E", "line": "#DEE7E2",
    "accent": "#226B51", "hover": "#19543F", "soft": "#E8F2EB",
    "quiet": "#F2F6F3", "disabled": "#E5ECE8", "error": "#973F30",
}
BODY = "Microsoft YaHei UI"
UTILITY = "Segoe UI"


def rounded(canvas, x1, y1, x2, y2, radius=14, **options):
    points = [x1+radius, y1, x2-radius, y1, x2, y1, x2, y1+radius,
              x2, y2-radius, x2, y2, x2-radius, y2, x1+radius, y2,
              x1, y2, x1, y2-radius, x1, y1+radius, x1, y1]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **options)


class Panel(tk.Frame):
    def __init__(self, parent, padding=22, **kwargs):
        super().__init__(parent, bg=COLORS["background"], **kwargs)
        self.canvas = tk.Canvas(self, bg=COLORS["background"], bd=0, highlightthickness=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.content = tk.Frame(self, bg=COLORS["surface"])
        self.content.pack(fill="both", expand=True, padx=padding, pady=padding)
        self.bind("<Configure>", self.draw)

    def draw(self, event=None):
        self.canvas.delete("all")
        rounded(self.canvas, 1, 1, self.winfo_width()-1, self.winfo_height()-1,
                fill=COLORS["surface"], outline=COLORS["line"], width=1)


class Button(tk.Canvas):
    def __init__(self, parent, text, command, kind="secondary", width=150, state="normal"):
        self.label, self.command, self.kind = text, command, kind
        self.enabled, self.hovered, self.focused = state != "disabled", False, False
        super().__init__(parent, width=width, height=44, bg=parent.cget("bg"),
                         highlightthickness=0, bd=0, takefocus=state != "disabled")
        self.bind("<Configure>", self.draw)
        self.bind("<Enter>", lambda _: self.hover(True))
        self.bind("<Leave>", lambda _: self.hover(False))
        self.bind("<Button-1>", self.click)
        self.bind("<Return>", self.click)
        self.bind("<space>", self.click)
        self.bind("<FocusIn>", lambda _: self.focus(True))
        self.bind("<FocusOut>", lambda _: self.focus(False))

    def configure(self, cnf=None, **kwargs):
        if "state" in kwargs:
            self.enabled = kwargs.pop("state") != "disabled"
            super().configure(takefocus=self.enabled)
        if "text" in kwargs:
            self.label = kwargs.pop("text")
        if "kind" in kwargs:
            self.kind = kwargs.pop("kind")
        result = super().configure(cnf, **kwargs)
        self.draw()
        return result

    def hover(self, value):
        self.hovered = value
        self.draw()

    def focus(self, value):
        self.focused = value
        self.draw()

    def click(self, event=None):
        if self.enabled:
            self.focus_set()
            self.command()
        return "break"

    def draw(self, event=None):
        self.delete("all")
        accent = self.kind == "primary"
        fill = COLORS["accent"] if accent else COLORS["surface"]
        foreground = "#FFFFFF" if accent else COLORS["text"]
        if self.hovered and self.enabled:
            fill = COLORS["hover"] if accent else COLORS["quiet"]
        if not self.enabled:
            fill, foreground = COLORS["disabled"], COLORS["muted"]
        outline = COLORS["accent"] if self.focused and self.enabled else fill if accent else COLORS["line"]
        rounded(self, 2, 2, max(10, self.winfo_width()-2), 42, radius=9,
                fill=fill, outline=outline, width=2 if self.focused else 1)
        self.create_text(self.winfo_width()/2, 22, text=self.label, fill=foreground,
                         font=(BODY, 10, "bold" if accent else "normal"))
        super().configure(cursor="hand2" if self.enabled else "arrow")


def folder_symbol(canvas, scale=1.0):
    """Original folder/chat mark used only for this community utility."""
    s = scale
    def p(values):
        return [v*s for v in values]
    canvas.create_polygon(*p([12, 26, 12, 17, 31, 17, 38, 25, 68, 25, 68, 63, 12, 63]),
                          fill=COLORS["soft"], outline=COLORS["accent"], width=2*s, joinstyle="round")
    canvas.create_line(*p([13, 31, 68, 31]), fill=COLORS["accent"], width=2*s)
    rounded(canvas, 38*s, 43*s, 76*s, 69*s, radius=6*s,
            fill=COLORS["surface"], outline=COLORS["accent"], width=2*s)
    for x in (49, 57, 65):
        canvas.create_oval(*p([x-1.5, 54, x+1.5, 57]), fill=COLORS["accent"], outline="")
