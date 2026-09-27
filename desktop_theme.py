"""Presentation-only medical green theme; CSS dimensions convert to pixels once.

Reference: ui-design-kit-20260927/index.html. Rounded backgrounds are local
Pillow assets; all actions remain real ttk widgets with keyboard semantics.
"""
from dataclasses import dataclass
import sys
import tkinter as tk
from tkinter import ttk, font as tkfont
from PIL import Image, ImageDraw, ImageTk
from platform_support import ui_font_family

SURFACE = '#ffffff'
INK = '#192d27'
TEXT = '#374a43'
MUTED = '#62736c'
ACCENT = '#176d5b'
HOVER = '#125746'
LINE = '#e2e8e4'
SIDEBAR = '#f0f3f0' if sys.platform == 'darwin' else '#f3f6f3'
NAV_SELECTED = '#dce9df' if sys.platform == 'darwin' else '#e1ece4'


@dataclass(frozen=True)
class Metrics:
    scale: float
    sidebar: int = 184
    content: int = 746
    gutter: int = 58

    def px(self, value):
        return max(1, round(value * self.scale)) if value else 0


class Theme:
    def __init__(self, window):
        self.window = window
        self.metrics = Metrics(max(.75, window.winfo_fpixels('1i') / 96))
        self.px = self.metrics.px
        self.family = ui_font_family(tkfont.families(window),
            tkfont.nametofont('TkDefaultFont', root=window).actual('family'))
        self.images = []
        self.icons = {}
        self.style = ttk.Style(window)
        # Aqua draws native button faces over custom palette values. Keep clam
        # for the shared light controls; window chrome and dialogs stay native.
        self.style.theme_use('clam')
        self.prefix = 'Medical' + str(len(self.style.element_names()))
        self.configure()

    def font(self, size=14, weight='normal'):
        # Negative sizes are device pixels. Do not multiply point sizes by DPI.
        return (self.family, -self.px(size), weight)

    def tile(self, fill, border=LINE, radius=8, stripe=False):
        side = self.px(24)
        outer = SIDEBAR if fill in (SIDEBAR, NAV_SELECTED, '#e9efe9') else SURFACE
        image = Image.new('RGBA', (side * 3, side * 3), outer)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((1, 1, side * 3 - 2, side * 3 - 2),
            radius=self.px(radius) * 3, fill=fill, outline=border, width=3)
        if stripe:
            draw.rounded_rectangle((3, 15, self.px(3) * 3 + 3, side * 3 - 15),
                                   radius=3, fill=ACCENT)
        photo = ImageTk.PhotoImage(image.resize((side, side), Image.Resampling.LANCZOS), master=self.window)
        self.images.append(photo)
        return photo

    def button_style(self, name, fill, border, hover, *, foreground=TEXT, size=14, bold=False, padding=(14, 9)):
        element = self.prefix + name + '.border'
        self.style.element_create(element, 'image', self.tile(fill, border),
            ('disabled', self.tile('#f2f5f3', LINE)),
            ('focus', self.tile(fill, ACCENT)),
            ('pressed', self.tile(hover, ACCENT)),
            ('active', self.tile(hover, border)),
            border=self.px(9), padding=0, sticky='nsew')
        self.style.layout(name, [(element, {'sticky':'nsew', 'children':[
            ('Button.focus', {'sticky':'nsew', 'children':[
                ('Button.padding', {'sticky':'nsew', 'children':[('Button.label', {'sticky':'nsew'})]})]})]})])
        self.style.configure(name, foreground=foreground, font=self.font(size, 'bold' if bold else 'normal'),
                             padding=tuple(self.px(n) for n in padding), anchor='center',
                             focuscolor=foreground, focusthickness=1)
        self.style.map(name, foreground=[('disabled', '#8c9b92')])

    def frame_style(self, name, fill=SURFACE, border=LINE):
        element = self.prefix + name + '.border'
        self.style.element_create(element, 'image', self.tile(fill, border, 10),
                                  border=self.px(11), padding=0, sticky='nsew')
        self.style.layout(name, [(element, {'sticky':'nsew'})])
        self.style.configure(name, background=fill)

    def check_image(self, selected=False, disabled=False):
        size=self.px(14)
        image=Image.new('RGBA',(size+self.px(7),size),SURFACE)
        draw=ImageDraw.Draw(image)
        color='#a5b5ad' if disabled else ACCENT
        draw.rounded_rectangle((1,1,size-2,size-2),radius=self.px(2),
                               fill=color if selected else SURFACE,
                               outline=color if selected else '#a9b9af',width=max(1,self.px(1)))
        if selected:
            draw.line([(self.px(3),self.px(7)),(self.px(6),self.px(10)),(self.px(11),self.px(4))],
                      fill=SURFACE,width=max(1,self.px(1.5)))
        photo=ImageTk.PhotoImage(image,master=self.window)
        self.images.append(photo)
        return photo

    def configure(self):
        s = self.style
        s.configure('.', font=self.font(), background=SURFACE, foreground=TEXT)
        for name, background in [('TFrame', SURFACE), ('Card.TFrame', SURFACE), ('Sidebar.TFrame', SIDEBAR),
                                  ('Notice.TFrame', '#f4f7f4')]:
            s.configure(name, background=background)
        for name, size, color, weight, bg in [
            ('TLabel',14,TEXT,'normal',SURFACE), ('Body.TLabel',14,TEXT,'normal',SURFACE),
            ('Small.TLabel',12,MUTED,'normal',SURFACE), ('Muted.TLabel',12,MUTED,'normal',SURFACE),
            ('Title.TLabel',27,INK,'bold',SURFACE), ('Section.TLabel',18,INK,'bold',SURFACE),
            ('Brand.TLabel',11,'#79877f','normal',SIDEBAR), ('SideSmall.TLabel',10,MUTED,'normal',SIDEBAR),
            ('NoticeTitle.TLabel',14,INK,'bold','#f4f7f4'), ('NoticeBody.TLabel',12,MUTED,'normal','#f4f7f4'),
            ('Success.TLabel',12,ACCENT,'normal',SURFACE), ('Pending.TLabel',12,'#737b5d','normal',SURFACE)]:
            s.configure(name, font=self.font(size, weight), foreground=color, background=bg)
        self.button_style('TButton', SURFACE, '#d6e0d8', '#f3f7f3', size=12)
        self.button_style('Primary.TButton', ACCENT, ACCENT, HOVER,
                          foreground=SURFACE, size=14, bold=True, padding=(21, 13))
        self.button_style('Link.TButton', SURFACE, SURFACE, '#f3f7f3', foreground=ACCENT, size=12, padding=(2, 5))
        self.button_style('Term.TButton', SURFACE, SURFACE, '#fafdfb', foreground=INK, size=18, bold=True, padding=(0, 2))
        self.frame_style('Panel.TFrame')
        self.frame_style('Term.TFrame', border='#ccd9cf')
        self.frame_style('Callout.TFrame', '#f4f7f4', '#e6ece7')
        element = self.prefix + 'Nav.border'
        stripe = sys.platform != 'darwin'
        s.element_create(element, 'image', self.tile(SIDEBAR, SIDEBAR, 7),
            ('disabled', self.tile(SIDEBAR, SIDEBAR, 7)),
            ('selected focus', self.tile(NAV_SELECTED, ACCENT, 7, stripe)),
            ('selected', self.tile(NAV_SELECTED, NAV_SELECTED, 7, stripe)),
            ('focus', self.tile(SIDEBAR, ACCENT, 7)),
            ('active', self.tile('#e9efe9', '#e9efe9', 7)), border=self.px(8), padding=0, sticky='nsew')
        s.layout('Nav.TButton', [(element, {'sticky':'nsew','children':[
            ('Button.padding', {'sticky':'nsew','children':[('Button.label', {'sticky':'w'})]})]})])
        s.configure('Nav.TButton', font=self.font(13), foreground='#52665a', anchor='w',
                    padding=(self.px(15),self.px(11)))
        s.map('Nav.TButton', foreground=[('disabled','#99a69e'),('selected','#1d5843')])
        s.configure('TEntry', padding=self.px(7), fieldbackground=SURFACE, bordercolor=LINE)
        s.configure('TCombobox', padding=self.px(7), fieldbackground=SURFACE)
        s.configure('TCheckbutton', font=self.font(11), background=SURFACE)
        check=self.prefix+'Check.indicator'
        s.element_create(check,'image',self.check_image(),
                         ('disabled selected',self.check_image(True,True)),
                         ('selected',self.check_image(True)),('disabled',self.check_image(False,True)),sticky='w')
        s.layout('TCheckbutton',[('Checkbutton.padding',{'sticky':'nsew','children':[
            (check,{'side':'left','sticky':'w'}),
            ('Checkbutton.focus',{'side':'left','sticky':'w','children':[('Checkbutton.label',{'sticky':'w'})]})]})])
        s.configure('TNotebook', background=SURFACE, borderwidth=0)
        s.configure('TNotebook.Tab', padding=(self.px(16),self.px(9)))
        s.map('TNotebook.Tab', background=[('selected','#e1ece4')])
        self.table_font = tkfont.Font(root=self.window, family=self.family, size=-self.px(12))
        s.configure('Treeview', font=self.table_font, rowheight=self.table_font.metrics('linespace') + self.px(10),
                    background=SURFACE, fieldbackground=SURFACE, bordercolor=LINE)
        s.configure('Treeview.Heading', font=self.font(12,'bold'), background=SIDEBAR)
        s.configure('Vertical.TScrollbar', arrowsize=self.px(10), background='#d4ddd5', troughcolor=SURFACE,
                    borderwidth=0, relief='flat')
        s.configure('TSeparator', background=LINE,lightcolor=LINE,darkcolor=LINE,bordercolor=LINE)
        s.configure('Horizontal.TProgressbar', background=ACCENT, troughcolor='#edf3ef', borderwidth=0)

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
        elif name == 'arrow': line([(4,12),(19,12)]); line([(13,6),(19,12),(13,18)])
        elif name == 'folder': line([(3,10),(21,10),(21,19),(19,21),(5,21),(3,19),(3,6),(5,4),(10,4),(12,7),(19,7),(21,9)])
        elif name == 'shield': line([(12,3),(20,6),(20,12),(18,16),(12,21),(6,16),(4,12),(4,6),(12,3)]); line([(8,12),(11,15),(16,9)])
        elif name == 'book': line([(12,5),(7,3.6),(2,4),(2,19),(7,18.5),(12,20),(17,18.5),(22,19),(22,4),(17,3.6),(12,5),(12,20)])
        else: raise ValueError(name)
        photo = ImageTk.PhotoImage(image.resize((dim,dim),Image.Resampling.LANCZOS), master=self.window)
        self.icons[key] = photo
        return photo


def walk_widgets(parent):
    """Bounded to a page/dialog, never searches a different window."""
    for child in parent.winfo_children():
        yield child
        yield from walk_widgets(child)
