"""Presentation-only medical green theme: light page, white rounded cards.

Performance rules (measured on Windows at 200 %):
- ttk paints every widget through an off-screen pixmap the size of the widget,
  so a page-sized ttk frame or canvas costs tens of milliseconds per resize
  step. Large areas are classic Tk frames and labels; only small interactive
  controls (buttons, checks, entries, notebook, table) stay ttk.
- The page column snaps to a few widths, so dragging the window edge moves
  the column instead of re-wrapping and re-laying out every label.
- Rounded images are generated lazily and only their corners are supersampled.
All actions remain real ttk widgets with keyboard semantics.
"""
from dataclasses import dataclass
import sys
import tkinter as tk
from tkinter import ttk, font as tkfont
from PIL import Image, ImageDraw, ImageTk
from platform_support import ui_font_family

PAGE = '#f5f8f6'
SURFACE = '#ffffff'
INK = '#192d27'
TEXT = '#374a43'
MUTED = '#66776f'
ACCENT = '#176d5b'
HOVER = '#125746'
LINE = '#e1e8e3'
SIDEBAR = '#edf2ee' if sys.platform == 'darwin' else '#eef3ef'
NAV_SELECTED = '#dbeae0'
NAV_HOVER = '#e4ede7'
TIP = '#e8f3ec'
TIP_INK = '#145846'
DISABLED = '#8c9b92'
TILE_CENTER = 200  # Device pixels of flat centre per bordered background image.

# kind: (size, weight, colour)
TEXT_STYLES = {
    'title': (24, 'bold', INK), 'section': (16, 'bold', INK), 'strong': (14, 'bold', INK),
    'body': (14, 'normal', TEXT), 'small': (12, 'normal', MUTED), 'eyebrow': (12, 'bold', ACCENT),
    'success': (12, 'normal', ACCENT), 'pending': (12, 'normal', '#8a6a1c'),
    'tip-title': (14, 'bold', TIP_INK), 'tip': (12, 'normal', '#3f5a4f'),
    'subtitle': (13, 'normal', MUTED), 'brand': (16, 'bold', INK), 'side': (10, 'normal', MUTED), 'step': (12, 'normal', MUTED),
    'step-current': (12, 'bold', ACCENT),
}


@dataclass(frozen=True)
class Metrics:
    scale: float
    sidebar: int = 196
    # macOS: a wider column. Its window is already 1080 points wide.
    content: int = 780 if sys.platform == 'darwin' else 720
    min_content: int = 420
    snap: int = 60
    gutter: int = 36
    card: int = 22
    radius: int = 12

    def px(self, value):
        return max(1, round(value * self.scale)) if value else 0


class Theme:
    def __init__(self, window):
        self.window = window
        # Aqua Tk reports 72 dpi and already draws in points (Retina included).
        floor = 1 if sys.platform == 'darwin' else .75
        self.metrics = Metrics(max(floor, window.winfo_fpixels('1i') / 96))
        self.px = self.metrics.px
        self.family = ui_font_family(tkfont.families(window),
            tkfont.nametofont('TkDefaultFont', root=window).actual('family'))
        self.images = {}
        self.icons = {}
        self.button_styles = {}
        self.style = ttk.Style(window)
        # Aqua draws native button faces over custom palette values. Keep clam
        # for the shared light controls; window chrome and dialogs stay native.
        self.style.theme_use('clam')
        self.prefix = 'Medical' + str(len(self.style.element_names()))
        self.configure()

    def font(self, size=14, weight='normal'):
        # Negative sizes are device pixels. Do not multiply point sizes by DPI.
        return (self.family, -self.px(size), weight)

    def text(self, kind):
        size, weight, colour = TEXT_STYLES[kind]
        return self.font(size, weight), colour

    # -- images -----------------------------------------------------------

    def _corner(self, radius, fill, border, outer):
        """Top-left corner patch, radius x radius, supersampled 4x."""
        s = 4
        big = Image.new('RGB', (radius * s, radius * s), outer)
        draw = ImageDraw.Draw(big)
        box = (0, 0, radius * 2 * s - 1, radius * 2 * s - 1)
        draw.ellipse(box, fill=border)
        if border != fill:
            draw.ellipse((s, s, box[2] - s, box[3] - s), fill=fill)
        return big.resize((radius, radius), Image.Resampling.LANCZOS)

    def rounded(self, width, height, radius, fill, border, outer, stripe=False):
        """Opaque rounded rectangle; straight edges are exact 1 px lines."""
        key = 'rounded', width, height, radius, fill, border, outer, stripe
        if key in self.images:
            return self.images[key]
        image = Image.new('RGB', (width, height), border)
        draw = ImageDraw.Draw(image)
        if border != fill:
            draw.rectangle((1, 1, width - 2, height - 2), fill=fill)
        if radius:
            corner = self._corner(radius, fill, border, outer)
            image.paste(corner, (0, 0))
            image.paste(corner.transpose(Image.Transpose.FLIP_LEFT_RIGHT), (width - radius, 0))
            image.paste(corner.transpose(Image.Transpose.FLIP_TOP_BOTTOM), (0, height - radius))
            image.paste(corner.transpose(Image.Transpose.ROTATE_180), (width - radius, height - radius))
        if stripe:
            bar = max(2, self.px(3))
            draw.rectangle((0, radius, bar - 1, height - radius - 1), fill=ACCENT)
        photo = ImageTk.PhotoImage(image, master=self.window)
        self.images[key] = photo
        return photo

    def tile(self, fill, border=LINE, radius=8, stripe=False, outer=SURFACE):
        # ttk fills a bordered image element by *tiling* its centre, not by
        # stretching it. A 2-3 px centre meant tens of thousands of image draws
        # per repaint, which stalled Windows scrolling for seconds.
        side = self.px(24) + TILE_CENTER
        return self.rounded(side, side, self.px(radius), fill, border, outer, stripe)

    def tile_options(self, border):
        # Keep a 24 px minimum; an image element otherwise requests its full
        # (much larger) image size.
        return {'border': border, 'padding': 0, 'sticky': 'nsew', 'width': self.px(24), 'height': self.px(24)}

    def corners(self, radius, fill, border, outer):
        key = 'corners', radius, fill, border, outer
        if key not in self.images:
            corner = self._corner(radius, fill, border, outer)
            self.images[key] = [ImageTk.PhotoImage(image, master=self.window) for image in (
                corner, corner.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
                corner.transpose(Image.Transpose.FLIP_TOP_BOTTOM), corner.transpose(Image.Transpose.ROTATE_180))]
        return self.images[key]

    def dot(self, state, background=PAGE):
        """Round marker behind a step number: 'current', 'done', 'todo' or 'number'."""
        key = 'dot', state, background
        if key not in self.images:
            size, s = self.px(26), 4
            big = Image.new('RGB', (size * s, size * s), background)
            draw = ImageDraw.Draw(big)
            box = (0, 0, size * s - 1, size * s - 1)
            if state == 'current':
                draw.ellipse(box, fill=ACCENT)
            elif state in ('done', 'number'):
                draw.ellipse(box, fill=TIP)
            else:
                draw.ellipse(box, fill='#c9d5cd')
                draw.ellipse((s * 2, s * 2, box[2] - s * 2, box[3] - s * 2), fill=background)
            self.images[key] = ImageTk.PhotoImage(big.resize((size, size), Image.Resampling.LANCZOS),
                                                  master=self.window)
        return self.images[key]

    # -- ttk styles -------------------------------------------------------

    def button_style(self, kind='', background=SURFACE):
        """Style for a button on the given background, created on first use.

        Rounded images are opaque (alpha blending is slow on Windows Tk), so
        their outer corners must match the container they sit on.
        """
        key = kind, background
        if key in self.button_styles:
            return self.button_styles[key]
        tag = {SURFACE: '', PAGE: 'Page', SIDEBAR: 'Side', TIP: 'Tip'}.get(background, 'X' + background[1:])
        name = f'{tag}{kind}.TButton' if (tag or kind) else 'TButton'
        s = self.style
        if kind == 'Link':
            s.configure(name, background=background, foreground=ACCENT, borderwidth=0, relief='flat',
                        font=self.font(12), padding=(self.px(2), self.px(5)), focuscolor=ACCENT,
                        focusthickness=1, anchor='w', lightcolor=background, darkcolor=background,
                        bordercolor=background)
            s.map(name, background=[('active', background), ('pressed', background)],
                  foreground=[('disabled', DISABLED), ('pressed', HOVER), ('active', HOVER)],
                  lightcolor=[('active', background)], darkcolor=[('active', background)])
            s.layout(name, [('Button.background', {'sticky': 'nsew'}), ('Button.focus', {'sticky': 'nsew', 'children': [
                ('Button.padding', {'sticky': 'nsew', 'children': [('Button.label', {'sticky': 'nsew'})]})]})])
        elif kind == 'Nav':
            element = self.prefix + name + '.border'
            stripe = sys.platform != 'darwin'
            t = lambda fill, border, stripe=False: self.tile(fill, border, 8, stripe, outer=background)
            s.element_create(element, 'image', t(background, background),
                ('disabled', t(background, background)),
                ('selected focus', t(NAV_SELECTED, ACCENT, stripe)),
                ('selected', t(NAV_SELECTED, NAV_SELECTED, stripe)),
                ('focus', t(background, ACCENT)),
                ('active', t(NAV_HOVER, NAV_HOVER)), **self.tile_options(self.px(9)))
            s.layout(name, [(element, {'sticky': 'nsew', 'children': [
                ('Button.padding', {'sticky': 'nsew', 'children': [('Button.label', {'sticky': 'w'})]})]})])
            s.configure(name, font=self.font(13), foreground='#4d6157', anchor='w',
                        padding=(self.px(14), self.px(10)))
            s.map(name, foreground=[('disabled', '#9aa79f'), ('selected', '#16503d')])
        else:
            primary = kind == 'Primary'
            fill, border, hover = ((ACCENT, ACCENT, HOVER) if primary else (SURFACE, '#d3ddd6', '#f1f6f2'))
            element = self.prefix + name + '.border'
            t = lambda fill, border: self.tile(fill, border, 8, outer=background)
            s.element_create(element, 'image', t(fill, border),
                ('disabled', t('#eef2ef', '#e3e9e5')),
                ('pressed', t(hover, ACCENT)),
                ('focus', t(fill, HOVER if primary else ACCENT)),
                ('active', t(hover, hover if primary else border)),
                **self.tile_options(self.px(9)))
            s.layout(name, [(element, {'sticky': 'nsew', 'children': [
                ('Button.focus', {'sticky': 'nsew', 'children': [
                    ('Button.padding', {'sticky': 'nsew', 'children': [('Button.label', {'sticky': 'nsew'})]})]})]})])
            foreground = SURFACE if primary else TEXT
            padding = (20, 12) if primary else (14, 8)
            s.configure(name, foreground=foreground, font=self.font(14 if primary else 12, 'bold' if primary else 'normal'),
                        padding=tuple(self.px(n) for n in padding), anchor='center',
                        focuscolor=foreground, focusthickness=1)
            s.map(name, foreground=[('disabled', DISABLED)])
        self.button_styles[key] = name
        return name

    def check_image(self, selected=False, disabled=False):
        size = self.px(15)
        s = 4
        image = Image.new('RGB', ((size + self.px(7)) * s, size * s), SURFACE)
        draw = ImageDraw.Draw(image)
        color = '#a5b5ad' if disabled else ACCENT
        draw.rounded_rectangle((s, s, size * s - s - 1, size * s - s - 1), radius=self.px(3) * s,
                               fill=color if selected else SURFACE,
                               outline=color if selected else '#a9b9af', width=max(1, self.px(1)) * s)
        if selected:
            draw.line([(self.px(4) * s, self.px(7.5) * s), (self.px(6.5) * s, self.px(10) * s),
                       (self.px(11) * s, self.px(4.5) * s)], fill=SURFACE, width=max(1, self.px(1.6)) * s,
                      joint='curve')
        photo = ImageTk.PhotoImage(image.resize((size + self.px(7), size), Image.Resampling.LANCZOS),
                                   master=self.window)
        self.images['check', selected, disabled] = photo
        return photo

    def configure(self):
        s = self.style
        s.configure('.', font=self.font(), background=SURFACE, foreground=TEXT)
        for name, background in [('TFrame', SURFACE), ('Card.TFrame', SURFACE), ('Sidebar.TFrame', SIDEBAR)]:
            s.configure(name, background=background)
        # Dialogs keep a few ttk labels; pages use classic labels.
        for name, kind in [('TLabel', 'body'), ('Small.TLabel', 'small'), ('Title.TLabel', 'title'),
                           ('Section.TLabel', 'section')]:
            font, colour = self.text(kind)
            s.configure(name, font=font, foreground=colour, background=SURFACE)
        s.configure('TEntry', padding=self.px(7), fieldbackground=SURFACE, bordercolor='#cfd9d2',
                    lightcolor=SURFACE, darkcolor=SURFACE)
        s.map('TEntry', bordercolor=[('focus', ACCENT)], lightcolor=[('focus', ACCENT)])
        s.configure('TCombobox', padding=self.px(7), fieldbackground=SURFACE)
        s.configure('TCheckbutton', font=self.font(12), background=SURFACE, foreground=TEXT)
        s.map('TCheckbutton', background=[('active', SURFACE)], foreground=[('disabled', DISABLED)])
        check = self.prefix + 'Check.indicator'
        s.element_create(check, 'image', self.check_image(),
                         ('disabled selected', self.check_image(True, True)),
                         ('selected', self.check_image(True)), ('disabled', self.check_image(False, True)), sticky='w')
        s.layout('TCheckbutton', [('Checkbutton.padding', {'sticky': 'nsew', 'children': [
            (check, {'side': 'left', 'sticky': 'w'}),
            ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children': [('Checkbutton.label', {'sticky': 'w'})]})]})])
        s.configure('TNotebook', background=SURFACE, borderwidth=0, tabmargins=0)
        s.configure('TNotebook.Tab', padding=(self.px(18), self.px(9)), background=PAGE,
                    foreground=MUTED, bordercolor=LINE, lightcolor=PAGE)
        s.map('TNotebook.Tab', background=[('selected', SURFACE)], foreground=[('selected', ACCENT)],
              lightcolor=[('selected', SURFACE)])
        self.table_font = tkfont.Font(root=self.window, family=self.family, size=-self.px(12))
        s.configure('Treeview', font=self.table_font, rowheight=self.table_font.metrics('linespace') + self.px(10),
                    background=SURFACE, fieldbackground=SURFACE, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
        s.configure('Treeview.Heading', font=self.font(12, 'bold'), background=PAGE, relief='flat',
                    bordercolor=LINE, lightcolor=PAGE, darkcolor=LINE)
        s.configure('TSeparator', background=LINE)
        s.configure('Horizontal.TProgressbar', background=ACCENT, troughcolor='#e3ece6', borderwidth=0,
                    lightcolor=ACCENT, darkcolor=ACCENT, bordercolor='#e3ece6', thickness=self.px(6))
        # Default buttons (dialogs) sit on white; page buttons pick their own.
        self.button_style('')
        self.button_style('Primary')

    def icon(self, name, size=20, color=ACCENT):
        key = name, size, color
        if key in self.icons:
            return self.icons[key]
        # Normalized line coordinates from the prototype SVG symbols. These are
        # decorative; labels and native controls carry all interaction semantics.
        dim = self.px(size)
        image = Image.new('RGBA', (dim*3, dim*3))
        draw = ImageDraw.Draw(image)
        factor = dim*3/24
        def line(points):
            draw.line([(round(x*factor),round(y*factor)) for x,y in points], fill=color,
                      width=max(1,round(1.7*factor)), joint='curve')
        def circle(box):
            draw.ellipse(tuple(round(x*factor) for x in box), outline=color, width=max(1,round(1.7*factor)))
        if name == 'calendar':
            draw.rounded_rectangle(tuple(round(n*factor) for n in (4,5,20,21)), radius=3*factor, outline=color, width=round(1.7*factor))
            for p in [[(8,3),(8,7)],[(16,3),(16,7)],[(4,10),(20,10)],[(8,14),(9,14)],[(15,14),(16,14)],[(8,18),(9,18)],[(15,18),(16,18)]]: line(p)
        elif name == 'home':
            line([(3,10),(12,3),(21,10)]); line([(5,9),(5,20),(10,20),(10,14),(14,14),(14,20),(19,20),(19,9)])
        elif name == 'settings':
            line([(10,4),(9.3,6.4),(7.1,7.4),(4.8,6.9),(3.6,9.1),(5.2,10.9),(5.1,13.5),(3.6,15.3),(4.9,17.6),(7.2,17.2),(9.4,18.2),(10.1,20.7),(12.7,20.7),(13.4,18.2),(15.7,17.2),(17.9,17.6),(19.2,15.3),(17.7,13.5),(17.6,10.9),(19.2,9.1),(19,7.1),(16.7,7.5),(14.5,6.5),(13.7,4),(10,4)]); circle((9,9,15,15))
        elif name in ('info','help','clock'):
            circle((3,3,21,21))
            if name == 'clock': line([(12,6),(12,12),(16,14)])
            elif name == 'info': line([(12,11),(12,17)]); circle((11.5,6.5,12.5,7.5))
            else: line([(9.6,9),(10.3,7.8),(12,7.3),(13.8,8),(14.4,10),(13.5,11.4),(12,12.2),(12,13.5)]); circle((11.5,16.5,12.5,17.5))
        elif name == 'check': line([(5,12),(9,16),(19,6)])
        elif name == 'chevron': line([(6,9),(12,15),(18,9)])
        elif name == 'right': line([(9,6),(15,12),(9,18)])
        elif name == 'arrow': line([(4,12),(19,12)]); line([(13,6),(19,12),(13,18)])
        elif name == 'folder': line([(3,10),(21,10),(21,19),(19,21),(5,21),(3,19),(3,6),(5,4),(10,4),(12,7),(19,7),(21,9)])
        elif name == 'shield': line([(12,3),(20,6),(20,12),(18,16),(12,21),(6,16),(4,12),(4,6),(12,3)]); line([(8,12),(11,15),(16,9)])
        elif name == 'book': line([(12,5),(7,3.6),(2,4),(2,19),(7,18.5),(12,20),(17,18.5),(22,19),(22,4),(17,3.6),(12,5),(12,20)])
        elif name == 'copy': draw.rounded_rectangle(tuple(round(n*factor) for n in (8,8,20,20)), radius=2*factor, outline=color, width=round(1.7*factor)); line([(16,8),(16,4),(4,4),(4,16),(8,16)])
        else: raise ValueError(name)
        photo = ImageTk.PhotoImage(image.resize((dim,dim),Image.Resampling.LANCZOS), master=self.window)
        self.icons[key] = photo
        return photo


class Card(tk.Canvas):
    """White (or tinted) rounded card; put children in ``card.body``.

    Every Tk child window costs about a millisecond to create and map on
    Windows, and repainting a card-sized photo costs more. A canvas container
    draws the border and four anti-aliased corner images as items under the
    padded body frame, for close to the cost of a plain square frame.
    """
    def __init__(self, parent, theme, *, fill=SURFACE, border=LINE, outer=PAGE, padding=None, radius=None):
        super().__init__(parent, bg=outer, bd=0, highlightthickness=0, width=1, height=1)
        pad = theme.px(theme.metrics.card if padding is None else padding)
        radius = theme.px(theme.metrics.radius if radius is None else radius)
        self.box = self.create_rectangle(0, 0, 1, 1, fill=fill, outline=border)
        self.corner_items = [self.create_image(0, 0, image=image, anchor=anchor) for image, anchor in
                             zip(theme.corners(radius, fill, border, outer), ('nw', 'ne', 'sw', 'se'))]
        self.painted = None
        self.body = tk.Frame(self, bg=fill, bd=0, highlightthickness=0)
        self.body.pack(fill='both', expand=True, padx=pad, pady=pad)
        self.body.background = fill
        outer_width = getattr(parent, 'inner_width', None)
        if outer_width:
            self.body.inner_width = outer_width - 2 * pad
        self.bind('<Configure>', self._paint)

    def _paint(self, event):
        width, height = event.width, event.height
        if (width, height) == self.painted:
            return
        self.painted = width, height
        self.coords(self.box, 0, 0, width - 1, height - 1)
        for item, x, y in zip(self.corner_items, (0, width, 0, width), (0, 0, height, height)):
            self.coords(item, x, y)


class SlimScrollbar(tk.Frame):
    """Thin rounded thumb on a classic frame: a ttk scrollbar costs ~10 ms
    per window-resize step on Windows. Drag, click-to-page and wheel remain."""
    COLOURS = {'normal': '#cdd7d0', 'active': '#aebab2', 'pressed': '#8f9d94'}

    def __init__(self, parent, theme, command):
        super().__init__(parent, bg=PAGE, width=theme.px(14), bd=0, highlightthickness=0)
        self.theme = theme
        self.command = command
        self.pill, self.min_length, self.margin = theme.px(7), theme.px(40), theme.px(4)
        self.first, self.last = 0.0, 1.0
        self.state_name = 'normal'
        self.geometry = None
        self.drag = None
        self.thumb = tk.Label(self, bg=PAGE, bd=0, highlightthickness=0)
        self.bind('<Configure>', lambda event: self._place())
        self.bind('<Button-1>', self._page)
        self.thumb.bind('<Button-1>', self._press)
        self.thumb.bind('<B1-Motion>', self._motion)
        self.thumb.bind('<ButtonRelease-1>', self._release)
        self.thumb.bind('<Enter>', lambda event: self._colour('pressed' if self.drag else 'active'))
        self.thumb.bind('<Leave>', lambda event: None if self.drag else self._colour('normal'))

    def get(self):
        return self.first, self.last

    def set(self, first, last):
        first, last = float(first), float(last)
        if (first, last) != (self.first, self.last):
            self.first, self.last = first, last
            self._place()

    def thumb_box(self):
        """(y, height) of the thumb in track pixels, or None when hidden."""
        size = self.last - self.first
        track = self.winfo_height() - 2 * self.margin
        if size >= 1 or track <= self.min_length:
            return None
        length = max(self.min_length, round(size * track))
        return self.margin + round(self.first / (1 - size) * (track - length)), length

    def _place(self):
        box = self.thumb_box()
        if box is None:
            if self.geometry is not None:
                self.thumb.place_forget()
                self.geometry = None
            return
        if box != self.geometry:
            self.geometry = box
            self._colour(self.state_name, force=True)
            self.thumb.place(x=(self.winfo_width() - self.pill) // 2, y=box[0], width=self.pill, height=box[1])

    def _colour(self, name, force=False):
        if name == self.state_name and not force:
            return
        self.state_name = name
        if self.geometry:
            self.thumb.configure(image=self.theme.rounded(self.pill, self.geometry[1], self.pill // 2,
                                                          self.COLOURS[name], self.COLOURS[name], PAGE))

    def _page(self, event):
        box = self.thumb_box()
        if box:
            self.command('scroll', -1 if event.y < box[0] else 1, 'pages')

    def _press(self, event):
        self.drag = event.y_root, self.first
        self._colour('pressed')
        return 'break'

    def _motion(self, event):
        box = self.thumb_box()
        if not self.drag or not box:
            return
        track = self.winfo_height() - 2 * self.margin - box[1]
        if track > 0:
            size = self.last - self.first
            self.command('moveto', self.drag[1] + (event.y_root - self.drag[0]) / track * (1 - size))

    def _release(self, event):
        self.drag = None
        self._colour('normal')


class ScrollArea:
    """Vertical scroller that moves one placed frame instead of a canvas.

    The content column has a fixed width that only changes at a few
    breakpoints, and is centred by moving it; see the module docstring.
    Offers the subset of the canvas yview protocol the window uses.
    """
    def __init__(self, parent, theme):
        self.theme = theme
        m = theme.metrics
        self.max_width, self.min_width, self.snap = theme.px(m.content), theme.px(m.min_content), theme.px(m.snap)
        self.increment = theme.px(24)
        self.frame = tk.Frame(parent, bg=PAGE, bd=0, highlightthickness=0)
        self.scrollbar = SlimScrollbar(self.frame, theme, self.yview)
        self.scrollbar.pack(side='right', fill='y')
        self.viewport = tk.Frame(self.frame, bg=PAGE, bd=0, highlightthickness=0)
        self.viewport.pack(side='left', fill='both', expand=True)
        gutter = theme.px(m.gutter)
        self.content = tk.Frame(self.viewport, bg=PAGE, bd=0, highlightthickness=0,
                                padx=gutter, pady=gutter)
        self.content.background = PAGE
        self.gutter = gutter
        self.offset = 0
        self.geometry = None
        self.on_width = None
        self.content.place(x=0, y=0, width=self.max_width)
        self.content.inner_width = self.max_width - 2 * gutter
        self.viewport.bind('<Configure>', self._layout)
        self.content.bind('<Configure>', lambda event: self._set(self.offset))

    def column_width(self, available):
        if available >= self.max_width:
            return self.max_width
        if available <= self.min_width:
            return max(1, available)
        return max(self.min_width, available // self.snap * self.snap)

    def _layout(self, event=None):
        available = self.viewport.winfo_width()
        width = self.column_width(available)
        geometry = width, max(0, (available - width) // 2)
        if geometry != self.geometry:
            changed = self.geometry is None or geometry[0] != self.geometry[0]
            self.geometry = geometry
            self.content.place_configure(x=geometry[1], width=width)
            if changed:
                self.content.inner_width = width - 2 * self.gutter
                if self.on_width:
                    self.on_width()
        self._set(self.offset)

    def _metrics(self):
        return max(1, self.content.winfo_reqheight()), max(1, self.viewport.winfo_height())

    def yview(self, *args):
        if not args:
            total, view = self._metrics()
            return self.offset / total, min(1.0, (self.offset + view) / total)
        if args[0] == 'moveto':
            self.yview_moveto(float(args[1]))
        elif args[0] == 'scroll':
            self.yview_scroll(int(args[1]), args[2])

    def yview_moveto(self, fraction):
        self._set(round(float(fraction) * self._metrics()[0]))

    def yview_scroll(self, number, what='units'):
        view = self._metrics()[1]
        step = self.increment if str(what).startswith('unit') else max(self.increment, view - self.increment)
        self._set(self.offset + int(number) * step)

    def _set(self, offset):
        total, view = self._metrics()
        offset = min(max(0, int(offset)), max(0, total - view))
        if offset != self.offset:
            self.offset = offset
            self.content.place_configure(y=-offset)
        self.scrollbar.set(*self.yview())

    def reset(self):
        self.offset = 0
        self.content.place_configure(y=0)
        self.scrollbar.set(0, 1)

    def ensure_visible(self, widget, margin):
        top = widget.winfo_rooty() - self.content.winfo_rooty()
        bottom = top + widget.winfo_height()
        view = self._metrics()[1]
        if top - self.offset < margin:
            self._set(top - margin)
        elif bottom - self.offset > view - margin:
            self._set(bottom - view + margin)


def walk_widgets(parent):
    """Bounded to a page/dialog, never searches a different window."""
    for child in parent.winfo_children():
        yield child
        yield from walk_widgets(child)
