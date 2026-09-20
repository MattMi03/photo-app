# photo-app/theme.py
"""
移动端风格 UI 组件库（Kivy）

设计目标：
- 面向真机 Android：触控区域 >= 44dp、字号/留白统一
- 现代卡片式设计：柔和阴影、圆角、品牌渐变、分段选择器、步骤条
- 纯 Canvas 绘制图标，不依赖图片资源，避免中文/Emoji 缺字问题
"""

from kivy.properties import (
    ListProperty, NumericProperty, StringProperty, BooleanProperty,
    ObjectProperty,
)
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.image import Image
from kivy.uix.dropdown import DropDown
from kivy.graphics import (
    Color, Rectangle, RoundedRectangle, Line, Ellipse, Mesh,
    StencilPush, StencilPop, StencilUse,
)
from kivy.graphics.instructions import InstructionGroup
from kivy.metrics import dp


# =====================================================
# 颜色
# =====================================================

def _mix(c1, c2, t):
    """c1 -> c2 线性插值，t=0 全 c1，t=1 全 c2"""
    return tuple(c1[i] + (c2[i] - c1[i]) * t for i in range(4))


class C:
    # 页面背景
    BG = (0.949, 0.961, 0.980, 1)

    # 卡片 / 填充
    CARD = (1, 1, 1, 1)
    FIELD = (0.957, 0.965, 0.976, 1)
    FIELD_BORDER = (0.86, 0.886, 0.925, 1)
    TRACK = (0.918, 0.933, 0.957, 1)

    # 品牌色
    PRIMARY = (0.122, 0.404, 0.918, 1)        # #1F67EA
    PRIMARY_DOWN = (0.078, 0.306, 0.761, 1)
    PRIMARY_TOP = (0.235, 0.510, 0.992, 1)    # 渐变上端
    PRIMARY_BOTTOM = (0.098, 0.318, 0.835, 1) # 渐变下端

    # 语义色
    SUCCESS = (0.090, 0.639, 0.290, 1)
    SUCCESS_DOWN = (0.067, 0.490, 0.224, 1)
    DANGER = (0.898, 0.231, 0.255, 1)
    DANGER_DOWN = (0.745, 0.153, 0.176, 1)
    WARN = (0.961, 0.588, 0.031, 1)

    DISABLED = (0.80, 0.827, 0.867, 1)
    DISABLED_TEXT = (1, 1, 1, 0.75)

    # 文字
    TEXT = (0.102, 0.125, 0.173, 1)
    TEXT_SUB = (0.424, 0.463, 0.533, 1)
    WHITE87 = (1, 1, 1, 0.87)
    WHITE70 = (1, 1, 1, 0.70)

    HAIRLINE = (0.890, 0.906, 0.933, 1)

    # 浅底色（图标底/提示底）
    PRIMARY_TINT = (0.910, 0.941, 1.000, 1)
    SUCCESS_TINT = (0.902, 0.961, 0.918, 1)
    DANGER_TINT = (1.000, 0.929, 0.933, 1)
    WARN_TINT = (1.000, 0.957, 0.878, 1)
    NEUTRAL_TINT = (0.929, 0.941, 0.961, 1)


# =====================================================
# Canvas 工具
# =====================================================

# Kivy 2.3 默认 shader 不使用 Mesh 顶点色（vColor），
# 竖向渐变改用 1xN 渐变纹理 + Rectangle，平滑且省资源
_GRAD_TEX = {}


def _gradient_texture(color_top, color_bottom, steps=128):
    key = (tuple(round(c, 3) for c in color_top[:3]),
           tuple(round(c, 3) for c in color_bottom[:3]))
    tex = _GRAD_TEX.get(key)
    if tex is not None:
        return tex
    from kivy.graphics.texture import Texture
    ct, cb = color_top[:3], color_bottom[:3]
    buf = bytearray()
    for i in range(steps):
        t = i / (steps - 1)  # i=0 对应纹理底部
        r = cb[0] + (ct[0] - cb[0]) * t
        g = cb[1] + (ct[1] - cb[1]) * t
        b = cb[2] + (ct[2] - cb[2]) * t
        buf += bytes((int(round(r * 255)),
                      int(round(g * 255)),
                      int(round(b * 255)),
                      255))
    tex = Texture.create(size=(1, steps), colorfmt="rgba")
    tex.blit_buffer(bytes(buf), colorfmt="rgba", bufferfmt="ubyte")
    tex.wrap = "clamp_to_edge"
    _GRAD_TEX[key] = tex
    return tex


def vgradient_mesh(widget, color_top, color_bottom):
    """给当前 canvas（调用方负责 with）加一块竖向渐变，自动跟随尺寸。

    历史名称保留；实现为渐变纹理 Rectangle。
    """
    tex = _gradient_texture(color_top, color_bottom)
    rect = Rectangle(texture=tex)

    def _update(*_):
        rect.pos = widget.pos
        rect.size = widget.size

    widget.bind(pos=_update, size=_update)
    _update()
    return rect


def shadow_card(group, x, y, w, h, radius):
    """在 group 里画三层柔和阴影（画在卡片底色之前）"""
    layers = [
        (dp(7), dp(5), dp(9), 0.045),
        (dp(4), dp(3), dp(6), 0.050),
        (dp(2), dp(1), dp(3), 0.060),
    ]
    for ex, dy, er, alpha in layers:
        group.add(Color(0.05, 0.09, 0.16, alpha))
        group.add(RoundedRectangle(
            pos=(x - ex, y - dy - ex * 0.2),
            size=(w + ex * 2, h + ex * 2),
            radius=[radius + er],
        ))


# =====================================================
# 矢量图标（24x24 网格，纯 Canvas 描边）
# =====================================================

_ICONS = {}


def icon(name):
    """注册图标绘制函数的装饰器"""
    def deco(fn):
        _ICONS[name] = fn
        return fn
    return deco


class Icon(Widget):
    icon = StringProperty("")
    color = ListProperty(C.TEXT)
    stroke_w = NumericProperty(1.7)

    def __init__(self, **kw):
        # BoxLayout 横排时默认垂直居中（FloatLayout 同样适用）
        kw.setdefault("pos_hint", {"center_y": 0.5})
        super().__init__(**kw)
        self.size_hint = (None, None)
        self._g = InstructionGroup()
        self.canvas.add(self._g)
        self.bind(pos=self._redraw, size=self._redraw,
                 icon=self._redraw, color=self._redraw)

    def _redraw(self, *_):
        g = self._g
        g.clear()
        w, h = self.size
        if w <= 0 or h <= 0 or self.icon not in _ICONS:
            return
        s = min(w, h) / 24.0
        ox, oy = self.x, self.y
        col = self.color
        g.add(Color(*col))

        def P(gx, gy):
            return ox + gx * s, oy + gy * s

        def poly(points, width=None, closed=False):
            # 两点线段在细宽度下偶发只画端帽，插中点规避
            if len(points) == 2:
                (x1, y1), (x2, y2) = points
                points = [(x1, y1), ((x1 + x2) / 2.0, (y1 + y2) / 2.0),
                          (x2, y2)]
            flat = []
            for gx, gy in points:
                px, py = P(gx, gy)
                flat.extend((px, py))
            g.add(Line(
                points=flat, width=(width or self.stroke_w) * s,
                cap="round", joint="round", close=closed,
            ))

        def ring(cx, cy, r, a0=0, a1=360, width=None):
            # Kivy 2.3.1 Line(circle=) 角度在 90° 象限边界有反射 bug，
            # 直接按标准数学角度（东=0，逆时针）采样点。
            import math
            sweep = a1 - a0
            steps = max(12, int(abs(sweep) / 8.0))
            flat = []
            for i in range(steps + 1):
                a = math.radians(a0 + sweep * i / steps)
                flat.append(ox + (cx + math.cos(a) * r) * s)
                flat.append(oy + (cy + math.sin(a) * r) * s)
            g.add(Line(points=flat,
                       width=(width or self.stroke_w) * s, cap="none"))

        def disc(cx, cy, r):
            px, py = P(cx - r, cy - r)
            g.add(Ellipse(pos=(px, py), size=(2 * r * s, 2 * r * s)))

        def box(gx, gy, gw, gh, r=0, width=None):
            px, py = P(gx, gy)
            g.add(Line(rounded_rectangle=(
                px, py, gw * s, gh * s, r * s),
                width=(width or self.stroke_w) * s))

        def fill_rrect(gx, gy, gw, gh, r):
            px, py = P(gx, gy)
            g.add(RoundedRectangle(
                pos=(px, py), size=(gw * s, gh * s), radius=[r * s]))

        _ICONS[self.icon](poly, ring, disc, box, fill_rrect, s)


# ---------- 图标定义 ----------

@icon("camera")
def _i_camera(poly, ring, disc, box, fr, s):
    box(3, 6.5, 18, 13.5, 2.5)
    fr(9.2, 18.6, 5.6, 2.4, 1.0)
    ring(12, 13.2, 3.6)
    disc(17.6, 17.0, 0.9)


@icon("photo")
def _i_photo(poly, ring, disc, box, fr, s):
    box(3, 4, 18, 16, 2.5)
    ring(8.6, 15.2, 2.0)
    poly([(5.5, 8.2), (10.2, 12.6), (12.4, 10.6),
          (14.8, 13.2), (18.5, 8.2)], width=1.7)


@icon("user")
def _i_user(poly, ring, disc, box, fr, s):
    ring(12, 16.8, 3.7)
    ring(12, 13.6, 6.6, 205, 335)


@icon("id")
def _i_id(poly, ring, disc, box, fr, s):
    box(2.5, 4.5, 19, 15, 2.2)
    disc(8.2, 12.0, 2.3)
    poly([(5.6, 7.6), (10.8, 7.6)])
    poly([(12.8, 11.0), (18.2, 11.0)])
    poly([(12.8, 14.2), (18.2, 14.2)])


@icon("folder")
def _i_folder(poly, ring, disc, box, fr, s):
    # y 轴向上：标签在左上
    poly([(3, 7), (21, 7), (21, 18), (10.5, 18),
          (9, 15.5), (3, 15.5)], closed=True)


@icon("sliders")
def _i_sliders(poly, ring, disc, box, fr, s):
    poly([(4, 7), (20, 7)])
    poly([(4, 12), (20, 12)])
    poly([(4, 17), (20, 17)])
    ring(9.0, 7, 2.1)
    ring(15.5, 12, 2.1)
    ring(8.0, 17, 2.1)


@icon("check")
def _i_check(poly, ring, disc, box, fr, s):
    poly([(5.5, 11.6), (10.2, 6.9), (18.5, 16.6)], width=2.0)


@icon("check_circle")
def _i_check_circle(poly, ring, disc, box, fr, s):
    ring(12, 12, 9.2)
    poly([(6.8, 11.8), (10.8, 7.8), (17.4, 15.0)], width=2.0)


@icon("chevron_down")
def _i_chev_d(poly, ring, disc, box, fr, s):
    poly([(7, 14), (12, 9), (17, 14)])


@icon("chevron_right")
def _i_chev_r(poly, ring, disc, box, fr, s):
    poly([(10, 6.5), (15.5, 12), (10, 17.5)])


@icon("upload")
def _i_upload(poly, ring, disc, box, fr, s):
    # 箭头自托盘向上（网格 y 轴向上：托盘 U 的横边在低位）
    poly([(12, 15.0), (12, 7.0)])
    poly([(7.8, 11.2), (12, 7.0), (16.2, 11.2)], width=1.9)
    poly([(5, 12.5), (5, 4.5), (19, 4.5), (19, 12.5)], width=1.8)


@icon("download")
def _i_download(poly, ring, disc, box, fr, s):
    # 箭头向下进入托盘
    poly([(12, 7.0), (12, 14.5)])
    poly([(7.8, 10.3), (12, 14.5), (16.2, 10.3)], width=1.9)
    poly([(5, 12.5), (5, 4.5), (19, 4.5), (19, 12.5)], width=1.8)


@icon("refresh")
def _i_refresh(poly, ring, disc, box, fr, s):
    ring(12, 12, 7.2, 30, 290)
    px = 12 + 7.2 * 0.866
    py = 12 + 7.2 * 0.5
    poly([(px - 2.6, py + 1.7), (px, py), (px - 3.0, py - 1.0)], width=1.7)


@icon("logout")
def _i_logout(poly, ring, disc, box, fr, s):
    poly([(9.5, 5.5), (5, 5.5), (5, 18.5), (9.5, 18.5)])
    poly([(10, 12), (19, 12)])
    poly([(14.5, 7.8), (19, 12), (14.5, 16.2)], width=1.8)


@icon("lock")
def _i_lock(poly, ring, disc, box, fr, s):
    box(4.5, 5.0, 15.0, 12.0, 2.2)
    ring(12, 17.0, 4.2, 0, 180)
    disc(12, 12.2, 1.25)
    fr(11.45, 9.0, 1.1, 2.6, 0.5)


@icon("server")
def _i_server(poly, ring, disc, box, fr, s):
    # 简洁地球（小尺寸下比双层机柜清晰）
    ring(12, 12, 8.6)
    poly([(12, 3.4), (12, 20.6)])
    poly([(3.4, 12), (20.6, 12)])


@icon("briefcase")
def _i_briefcase(poly, ring, disc, box, fr, s):
    box(3, 4.5, 18, 13.0, 2.2)
    box(8.6, 16.8, 6.8, 3.4, 1.6)          # 提手跨在箱体上沿


@icon("eye")
def _i_eye(poly, ring, disc, box, fr, s):
    ring(12, 12, 8.5)
    disc(12, 12, 2.5)


@icon("eye_off")
def _i_eye_off(poly, ring, disc, box, fr, s):
    ring(12, 12, 8.5)
    disc(12, 12, 2.5)
    poly([(4.5, 19.5), (19.5, 4.5)], width=2.0)


@icon("activity")
def _i_activity(poly, ring, disc, box, fr, s):
    poly([(3, 12), (8.5, 12), (10.8, 5.5), (13.4, 18.5),
          (15.6, 12), (21, 12)], width=1.9)


@icon("alert")
def _i_alert(poly, ring, disc, box, fr, s):
    poly([(12, 3.8), (21.2, 19.6), (2.8, 19.6)], closed=True, width=1.9)
    poly([(12, 9.8), (12, 14.6)], width=2.0)
    disc(12, 17.3, 1.05)


@icon("info")
def _i_info(poly, ring, disc, box, fr, s):
    ring(12, 12, 9.0)
    disc(12, 16.6, 1.05)
    poly([(12, 10.6), (12, 7.6)], width=2.0)


@icon("arrow_right")
def _i_arrow(poly, ring, disc, box, fr, s):
    poly([(4, 12), (20, 12)], width=1.9)
    poly([(13.5, 5.8), (20, 12), (13.5, 18.2)], width=1.9)


@icon("arrow_left")
def _i_arrow_left(poly, ring, disc, box, fr, s):
    poly([(20, 12), (4, 12)], width=1.9)
    poly([(10.5, 5.8), (4, 12), (10.5, 18.2)], width=1.9)


@icon("arrow_up")
def _i_arrow_up(poly, ring, disc, box, fr, s):
    poly([(12, 4), (12, 20)], width=1.9)
    poly([(5.8, 13.5), (12, 20), (18.2, 13.5)], width=1.9)


@icon("arrow_down")
def _i_arrow_down(poly, ring, disc, box, fr, s):
    poly([(12, 20), (12, 4)], width=1.9)
    poly([(5.8, 10.5), (12, 4), (18.2, 10.5)], width=1.9)


@icon("search")
def _i_search(poly, ring, disc, box, fr, s):
    ring(10.5, 13.5, 6.2, width=1.9)
    poly([(15.2, 8.8), (20.2, 3.8)], width=2.0)


@icon("image_off")
def _i_image_off(poly, ring, disc, box, fr, s):
    box(3, 4.5, 18, 15, 2)
    ring(8.5, 15, 1.8)
    poly([(6, 8.5), (10, 12.5), (12.5, 10.5), (15, 13), (18, 8.5)])
    poly([(4, 20), (20, 4)], width=2.0)


# =====================================================
# 按钮
# =====================================================

class AppButton(ButtonBehavior, BoxLayout):
    text = StringProperty("")
    icon_name = StringProperty("")
    kind = StringProperty("filled")   # filled/tonal/outlined/text/success/danger/white
    radius = NumericProperty(dp(12))
    font_size = NumericProperty(dp(15))
    icon_size = NumericProperty(dp(19))

    def __init__(self, **kw):
        super().__init__(**kw)
        self.orientation = "horizontal"
        self.spacing = dp(8)
        self.padding = [dp(14), 0, dp(14), 0]
        self.size_hint_y = None
        self.height = dp(48)
        self._g = InstructionGroup()
        self.canvas.before.add(self._g)

        self._icon = Icon(icon=self.icon_name,
                          size=(self.icon_size, self.icon_size),
                          pos_hint={"center_y": 0.5})
        self._label = Label(text=self.text, font_size=self.font_size,
                            bold=True, halign="center", valign="middle",
                            size_hint=(None, None))
        self._label.bind(
            texture_size=lambda l, ts: setattr(l, "width", ts[0]))
        # 两侧弹性垫片，让 [图标 + 文字] 整体居中，图标不贴边
        from kivy.uix.widget import Widget
        self._pad_l = Widget(size_hint_x=1)
        self._pad_r = Widget(size_hint_x=1)
        self.add_widget(self._pad_l)
        self.add_widget(self._icon)
        self.add_widget(self._label)
        self.add_widget(self._pad_r)

        self.bind(
            pos=self._redraw, size=self._redraw, state=self._redraw,
            disabled=self._redraw, kind=self._redraw,
        )
        self.bind(text=self._sync, icon_name=self._sync,
                  font_size=self._sync, icon_size=self._sync)
        self._sync()

    def _sync(self, *_):
        self._label.text = self.text
        self._label.font_size = self.font_size
        if self.icon_name and self.icon_name in _ICONS:
            self._icon.icon = self.icon_name
            self._icon.size = (self.icon_size, self.icon_size)
            self._icon.opacity = 1
            self.spacing = dp(8)
        else:
            self._icon.opacity = 0
            self._icon.size = (0, 0)
            self.spacing = 0
        self._apply_text_color()

    def _palette(self):
        down = self.state == "down"
        if self.disabled:
            bg = C.DISABLED
            fg = C.DISABLED_TEXT
            border = None
        elif self.kind == "filled":
            bg = C.PRIMARY_DOWN if down else C.PRIMARY
            fg = (1, 1, 1, 1)
            border = None
        elif self.kind == "success":
            bg = C.SUCCESS_DOWN if down else C.SUCCESS
            fg = (1, 1, 1, 1)
            border = None
        elif self.kind == "danger":
            bg = C.DANGER_DOWN if down else C.DANGER
            fg = (1, 1, 1, 1)
            border = None
        elif self.kind == "tonal":
            bg = _mix(C.PRIMARY_TINT, C.PRIMARY, 0.16 if down else 0.06)
            fg = C.PRIMARY_DOWN
            border = None
        elif self.kind == "outlined":
            bg = _mix((1, 1, 1, 0), C.PRIMARY_TINT, 0.6 if down else 0.0)
            fg = C.PRIMARY
            border = C.FIELD_BORDER
        elif self.kind == "white":
            bg = (0.88, 0.92, 1.0, 1) if down else (1, 1, 1, 1)
            fg = C.PRIMARY
            border = None
        elif self.kind == "glass":
            bg = (1, 1, 1, 0.22 if down else 0.13)
            fg = (1, 1, 1, 0.95)
            border = None
        else:  # text
            bg = _mix((1, 1, 1, 0), C.PRIMARY_TINT, 0.7 if down else 0.0)
            fg = C.PRIMARY
            border = None
        return bg, fg, border

    def _apply_text_color(self):
        _, fg, _ = self._palette()
        self._label.color = fg
        self._icon.color = fg

    def _redraw(self, *_):
        bg, fg, border = self._palette()
        self._label.color = fg
        self._icon.color = fg
        g = self._g
        g.clear()
        x, y = self.pos
        w, h = self.size
        if bg[3] > 0:
            g.add(Color(*bg))
            g.add(RoundedRectangle(pos=(x, y), size=(w, h),
                                   radius=[self.radius]))
        if border:
            g.add(Color(*border))
            g.add(Line(rounded_rectangle=(x + dp(1), y + dp(1),
                                          w - dp(2), h - dp(2),
                          self.radius - dp(1)), width=dp(1.1)))


# 语义别名
class PrimaryButton(AppButton):
    def __init__(self, **kw):
        kw.setdefault("kind", "filled")
        super().__init__(**kw)


class SuccessButton(AppButton):
    def __init__(self, **kw):
        kw.setdefault("kind", "success")
        super().__init__(**kw)


class DangerButton(AppButton):
    def __init__(self, **kw):
        kw.setdefault("kind", "danger")
        super().__init__(**kw)


class GhostButton(AppButton):
    def __init__(self, **kw):
        kw.setdefault("kind", "tonal")
        super().__init__(**kw)


# =====================================================
# 卡片
# =====================================================

class Card(BoxLayout):
    radius = NumericProperty(dp(16))

    def __init__(self, **kw):
        kw.setdefault("orientation", "vertical")
        kw.setdefault("padding", dp(14))
        kw.setdefault("spacing", dp(10))
        super().__init__(**kw)
        self._g = InstructionGroup()
        self.canvas.before.add(self._g)
        self.bind(pos=self._redraw, size=self._redraw)

    def _redraw(self, *_):
        g = self._g
        g.clear()
        x, y = self.pos
        w, h = self.size
        shadow_card(g, x, y, w, h, self.radius)
        g.add(Color(*C.CARD))
        g.add(RoundedRectangle(pos=(x, y), size=(w, h),
                               radius=[self.radius]))
        g.add(Color(*C.HAIRLINE))
        g.add(Line(rounded_rectangle=(
            x + 0.75, y + 0.75, w - 1.5, h - 1.5, self.radius),
            width=1))


# =====================================================
# 区块标题（小图标 + 标题 + 右侧插槽）
# =====================================================

class SectionHeader(BoxLayout):
    def __init__(self, title, icon_name="", trailing=None,
                 tint=None, fg=None, **kw):
        kw.setdefault("orientation", "horizontal")
        kw.setdefault("spacing", dp(9))
        kw.setdefault("size_hint_y", None)
        kw["height"] = dp(28)
        super().__init__(**kw)

        if icon_name:
            badge = FloatLayout(size_hint_x=None, width=dp(28))
            with badge.canvas.before:
                Color(*(tint or C.PRIMARY_TINT))
                self._badge_rect = RoundedRectangle(radius=[dp(8)])
            self._badge = badge
            ic = Icon(icon=icon_name, color=fg or C.PRIMARY,
                      size=(dp(16), dp(16)))
            badge.add_widget(ic)
            badge.bind(pos=self._layout_badge, size=self._layout_badge)
            ic.bind(pos=self._layout_icon, size=self._layout_icon)
            badge._ic = ic
            self.add_widget(badge)

        self.title_label = Label(
            text=title, font_size=dp(15), bold=True, color=C.TEXT,
            halign="left", valign="middle",
        )
        self.title_label.bind(size=lambda l, s: setattr(l, "text_size", s))
        self.add_widget(self.title_label)

        if trailing:
            trailing.size_hint_x = None
            self.add_widget(trailing)

    def _layout_badge(self, *_):
        b = self._badge
        self._badge_rect.pos = b.pos
        self._badge_rect.size = b.size
        ic = getattr(b, "_ic", None)
        if ic:
            ic.pos = (b.x + (b.width - ic.width) / 2,
                      b.y + (b.height - ic.height) / 2)

    def _layout_icon(self, *_):
        self._layout_badge()


# =====================================================
# 输入框
# =====================================================

class RoundedTextInput(TextInput):
    radius = NumericProperty(dp(12))

    def __init__(self, **kw):
        kw.setdefault("font_size", dp(14))
        kw.setdefault("multiline", False)
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(48))
        super().__init__(**kw)

        self.background_normal = ""
        self.background_active = ""
        self.background_disabled_normal = ""
        self.background_color = (0, 0, 0, 0)
        self.foreground_color = C.TEXT
        self.cursor_color = (*C.PRIMARY[:3], 1)
        self.hint_text_color = C.TEXT_SUB
        self.selection_color = (*C.PRIMARY[:3], 0.25)
        self.padding = [dp(14), dp(12), dp(14), dp(12)]

        self._g = InstructionGroup()
        self.canvas.before.add(self._g)
        self.bind(pos=self._redraw, size=self._redraw,
                 focus=self._redraw, readonly=self._redraw,
                 disabled=self._redraw, text=self._redraw,
                 foreground_color=self._redraw)

    def _redraw(self, *_):
        g = self._g
        g.clear()
        x, y = self.pos
        w, h = self.size
        if self.disabled or self.readonly:
            fill = C.NEUTRAL_TINT
            border = (0, 0, 0, 0)
            self.foreground_color = C.TEXT_SUB
        elif self.focus:
            fill = (1, 1, 1, 1)
            border = C.PRIMARY
            self.foreground_color = C.TEXT
        else:
            fill = C.FIELD
            border = C.FIELD_BORDER
            self.foreground_color = C.TEXT
        g.add(Color(*fill))
        g.add(RoundedRectangle(pos=(x, y), size=(w, h),
                               radius=[self.radius]))
        if border[3] > 0:
            g.add(Color(*border))
            g.add(Line(rounded_rectangle=(
                x + dp(1), y + dp(1), w - dp(2), h - dp(2),
                self.radius - dp(1)), width=dp(1.4)))
        # Kivy 2.3.1 的文字纹理是白色，主 canvas 绘制 glyph 时不自带
        # Color，会沿用 canvas.before 中最后一条 Color（上面是浅色
        # 边框），导致文字被染浅。这里在末尾显式压入文字色。
        if self.disabled or self.readonly:
            text_tint = C.TEXT_SUB
        elif not self.text:
            text_tint = C.TEXT_SUB  # hint 占位文字
        else:
            text_tint = self.foreground_color
        g.add(Color(*text_tint))


class IconField(BoxLayout):
    """左侧带图标的输入框（Icon 覆盖在 TextInput 上）"""

    def __init__(self, icon_name, input_widget, trailing=None, **kw):
        kw.setdefault("orientation", "horizontal")
        kw.setdefault("size_hint_y", None)
        super().__init__(**kw)
        self.height = input_widget.height
        self._input = input_widget
        input_widget.size_hint = (1, 1)
        # 给图标和尾部控件留空间
        pad_left = dp(42)
        pad_right = dp(42) if trailing is not None else dp(14)
        input_widget.padding = [pad_left, input_widget.padding[1],
                                pad_right, input_widget.padding[3]]

        wrap = BoxLayout(size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        wrap.add_widget(input_widget)

        holder = FloatLayout(size_hint=(1, 1))
        holder.add_widget(wrap)

        ic = Icon(icon=icon_name, color=C.TEXT_SUB,
                  size=(dp(19), dp(19)))
        holder.add_widget(ic)

        def place(*_):
            ic.pos = (wrap.x + dp(13),
                      wrap.y + (wrap.height - ic.height) / 2)

        wrap.bind(pos=place, size=place)

        if trailing is not None:
            trailing.size_hint = (None, None)
            trailing.size = (dp(38), dp(38))
            holder.add_widget(trailing)

            def place_trail(*_):
                trailing.pos = (wrap.right - dp(40),
                                wrap.y + (wrap.height - trailing.height) / 2)

            wrap.bind(pos=place_trail, size=place_trail)
            place_trail()

        self.add_widget(holder)

    def __getattr__(self, name):
        # 透传到底层 TextInput（text/password/focus/readonly...）
        # 注意：超类 __init__ 阶段 _input 尚不存在，必须正常抛 AttributeError
        try:
            inp = object.__getattribute__(self, "_input")
        except AttributeError:
            raise AttributeError(name)
        return getattr(inp, name)


# =====================================================
# 下拉选择（自绘，替代默认 Spinner）
# =====================================================

class _Menu(DropDown):
    radius_val = dp(14)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.background_color = (0, 0, 0, 0)
        self.container.padding = [dp(6), dp(6)]
        self.container.spacing = 0
        self._g = InstructionGroup()
        self.canvas.before.insert(0, self._g)
        self.bind(pos=self._redraw, size=self._redraw)

    def _redraw(self, *_):
        g = self._g
        g.clear()
        x, y = self.pos
        w, h = self.size
        shadow_card(g, x, y, w, h, self.radius_val)
        g.add(Color(*C.CARD))
        g.add(RoundedRectangle(pos=(x, y), size=(w, h),
                               radius=[self.radius_val]))


class DropdownField(ButtonBehavior, BoxLayout):
    value = StringProperty("")
    options = ListProperty([])
    on_select_cb = ObjectProperty(None)

    def __init__(self, options=None, selected="", on_select=None, **kw):
        kw.setdefault("orientation", "horizontal")
        kw.setdefault("spacing", dp(8))
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(46))
        super().__init__(**kw)
        self.options = list(options or [])
        self.value = selected
        self.on_select_cb = on_select
        self.padding = [dp(14), 0, dp(10), 0]

        self._g = InstructionGroup()
        self.canvas.before.add(self._g)
        self._label = Label(text=selected, font_size=dp(14),
                            color=C.TEXT, halign="left", valign="middle")
        self._label.bind(size=lambda l, s: setattr(l, "text_size", s))
        self._chev = Icon(icon="chevron_down", color=C.TEXT_SUB,
                          size=(dp(18), dp(18)), size_hint=(None, None))
        self.add_widget(self._label)
        self.add_widget(self._chev)

        self.bind(pos=self._redraw, size=self._redraw,
                  state=self._redraw, value=self._sync)
        self.bind(on_release=self._open)

    def _sync(self, *_):
        self._label.text = self.value

    @property
    def text(self):
        return self.value

    @text.setter
    def text(self, v):
        self.value = v

    def _redraw(self, *_):
        g = self._g
        g.clear()
        x, y = self.pos
        w, h = self.size
        down = self.state == "down"
        g.add(Color(*C.FIELD if not down else (1, 1, 1, 1)))
        g.add(RoundedRectangle(pos=(x, y), size=(w, h), radius=[dp(12)]))
        g.add(Color(*(C.PRIMARY if down else C.FIELD_BORDER)))
        g.add(Line(rounded_rectangle=(
            x + dp(1), y + dp(1), w - dp(2), h - dp(2), dp(11)),
            width=dp(1.4 if down else 1.1)))

    def _open(self, *_):
        dd = _Menu()
        for opt in self.options:
            item = AppButton(text=opt, kind="text", radius=dp(8),
                             height=dp(44), font_size=dp(14))
            if opt == self.value:
                item._label.color = C.PRIMARY
            item.bind(on_release=lambda b, v=opt: (
                setattr(self, "value", v),
                self._fire(v),
                dd.dismiss(),
            ))
            dd.add_widget(item)
        dd.width = max(self.width, dp(200))
        for ch in dd.container.children:
            ch.width = dd.width - dp(12)
        dd.open(self)

    def _fire(self, value):
        if self.on_select_cb:
            self.on_select_cb(value)


# =====================================================
# 分段选择器
# =====================================================

class _Seg(ButtonBehavior, Label):
    selected = BooleanProperty(False)

    def __init__(self, text, value, **kw):
        kw.setdefault("font_size", dp(13))
        kw.setdefault("bold", True)
        kw.setdefault("halign", "center")
        kw.setdefault("valign", "middle")
        super().__init__(text=text, **kw)
        self.value = value
        self._g = InstructionGroup()
        self.canvas.before.add(self._g)
        self.bind(pos=self._redraw, size=self._redraw,
                 selected=self._redraw, state=self._redraw)
        self._redraw()

    def _redraw(self, *_):
        g = self._g
        g.clear()
        x, y = self.pos
        w, h = self.size
        pad = dp(3.5)
        if self.selected:
            g.add(Color(0.05, 0.09, 0.16, 0.10))
            g.add(RoundedRectangle(
                pos=(x + pad, y + pad - dp(1)),
                size=(w - pad * 2, h - pad * 2),
                radius=[dp(9)]))
            g.add(Color(1, 1, 1, 1))
            g.add(RoundedRectangle(
                pos=(x + pad, y + pad),
                size=(w - pad * 2, h - pad * 2),
                radius=[dp(9)]))
            self.color = C.PRIMARY
        else:
            self.color = C.TEXT_SUB if self.state == "normal" else C.TEXT


class Segmented(BoxLayout):
    selection = StringProperty("")
    on_change_cb = ObjectProperty(None)

    def __init__(self, choices, selected="", on_change=None, **kw):
        """choices: [(label, value), ...]"""
        kw.setdefault("orientation", "horizontal")
        kw.setdefault("spacing", 0)
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(44))
        super().__init__(**kw)
        self.on_change_cb = on_change
        self._segs = {}
        self._g = InstructionGroup()
        self.canvas.before.add(self._g)
        for label, value in choices:
            seg = _Seg(label, value)
            seg.bind(on_release=lambda b, v=value: self._choose(v))
            self.add_widget(seg)
            self._segs[value] = seg
        self.bind(pos=self._redraw_bg, size=self._redraw_bg)
        self.selection = selected

    def _choose(self, value):
        self.selection = value
        if self.on_change_cb:
            self.on_change_cb(value)

    def on_selection(self, *_):
        for v, seg in self._segs.items():
            seg.selected = (v == self.selection)

    def _redraw_bg(self, *_):
        g = self._g
        g.clear()
        x, y = self.pos
        w, h = self.size
        g.add(Color(*C.TRACK))
        g.add(RoundedRectangle(pos=(x, y), size=(w, h), radius=[dp(11)]))
        self.on_selection()


# =====================================================
# 步骤条
# =====================================================

class StepCell(Widget):
    done = BooleanProperty(False)
    current = BooleanProperty(False)
    num = NumericProperty(1)

    def __init__(self, caption, **kw):
        super().__init__(**kw)
        self.size_hint_y = None
        self.height = dp(58)
        self._g = InstructionGroup()
        self.canvas.add(self._g)

        self.num_label = Label(
            text=str(self.num), font_size=dp(12), bold=True,
            size_hint=(None, None), size=(dp(22), dp(22)),
            halign="center", valign="middle",
        )
        self.cap_label = Label(
            text=caption, font_size=dp(10.5),
            size_hint=(None, None), halign="center", valign="middle",
        )
        self.add_widget(self.num_label)
        self.add_widget(self.cap_label)
        self.bind(pos=self._layout, size=self._layout)
        self.bind(done=self._redraw, current=self._redraw)
        self._redraw()

    def _center(self):
        return self.x + self.width / 2

    def _layout(self, *_):
        cx = self._center()
        cy = self.top - dp(16)
        self.num_label.pos = (cx - dp(11), cy - dp(11))
        self.num_label.size = (dp(22), dp(22))
        self.cap_label.pos = (self.x, self.y)
        self.cap_label.size = (self.width, dp(22))
        self._redraw()

    def set_left_done(self, flag):
        self._left_done = flag
        self._redraw()

    def set_right_done(self, flag):
        self._right_done = flag
        self._redraw()

    def _redraw(self, *_):
        g = self._g
        g.clear()
        w, h = self.size
        if w <= 0:
            return
        cx = self._center()
        cy = self.top - dp(16)
        r = dp(11)
        line_y = cy
        lw = dp(1.6)
        left_done = getattr(self, "_left_done", False)
        right_done = getattr(self, "_right_done", False)

        if self.num > 1:
            g.add(Color(*(C.SUCCESS if left_done else C.HAIRLINE)))
            g.add(Line(points=[self.x, line_y, cx - r, line_y], width=lw))
        if not getattr(self, "_last", False):
            g.add(Color(*(C.SUCCESS if right_done else C.HAIRLINE)))
            g.add(Line(points=[cx + r, line_y, self.right, line_y], width=lw))

        if self.done:
            g.add(Color(*C.SUCCESS))
            g.add(Ellipse(pos=(cx - r, cy - r), size=(r * 2, r * 2)))
            self.cap_label.color = C.SUCCESS
            # 白色对勾
            g.add(Color(1, 1, 1, 1))
            g.add(Line(points=[cx - dp(5.2), cy - dp(0.4),
                               cx - dp(1.8), cy - dp(3.8),
                               cx + dp(5.4), cy + dp(4.2)],
                       width=dp(2.0), cap="round", joint="round"))
            self.num_label.text = ""
        elif self.current:
            g.add(Color(*C.PRIMARY))
            g.add(Ellipse(pos=(cx - r, cy - r), size=(r * 2, r * 2)))
            g.add(Color(1, 1, 1, 1))
            g.add(Ellipse(pos=(cx - r + dp(2.4), cy - r + dp(2.4), ),
                          size=(r * 2 - dp(4.8), r * 2 - dp(4.8))))
            self.num_label.text = str(self.num)
            self.num_label.color = C.PRIMARY
            self.cap_label.color = C.PRIMARY
        else:
            g.add(Color(*C.HAIRLINE))
            g.add(Ellipse(pos=(cx - r, cy - r), size=(r * 2, r * 2)))
            g.add(Color(1, 1, 1, 1))
            g.add(Ellipse(pos=(cx - r + dp(1.6), cy - r + dp(1.6)),
                          size=(r * 2 - dp(3.2), r * 2 - dp(3.2))))
            self.num_label.text = str(self.num)
            self.num_label.color = C.TEXT_SUB
            self.cap_label.color = C.TEXT_SUB


class Stepper(BoxLayout):
    def __init__(self, captions, **kw):
        kw.setdefault("orientation", "horizontal")
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(58))
        super().__init__(**kw)
        self._cells = []
        for i, cap in enumerate(captions, 1):
            cell = StepCell(cap, num=i)
            if i == len(captions):
                cell._last = True
            self.add_widget(cell)
            self._cells.append(cell)

    def set_states(self, done_flags, current=0):
        """done_flags: list[bool]；current: 1-based 进行中步骤"""
        n = len(self._cells)
        for i, cell in enumerate(self._cells):
            idx = i + 1
            cell.done = bool(done_flags[i])
            cell.current = (idx == current and not cell.done)
            cell.set_left_done(i > 0 and done_flags[i - 1])
            cell.set_right_done(done_flags[i] if i < n - 1 else False)


# =====================================================
# 照片框（圆角裁剪 + 空占位）
# =====================================================

class _RoundedClip(FloatLayout):
    radius_val = NumericProperty(dp(12))

    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            StencilPush()
            Color(1, 1, 1, 1)
            self._stencil = RoundedRectangle(radius=[self.radius_val])
            StencilUse()
        with self.canvas.after:
            StencilPop()
        self.bind(pos=self._upd, size=self._upd, radius_val=self._upd)

    def _upd(self, *_):
        self._stencil.pos = self.pos
        self._stencil.size = self.size
        self._stencil.radius = [self.radius_val]


class PhotoBox(ButtonBehavior, FloatLayout):
    source = StringProperty("")
    radius_val = NumericProperty(dp(12))

    def __init__(self, hint="暂无图片", icon_name="photo", **kw):
        super().__init__(**kw)
        self.size_hint_y = None
        self._g = InstructionGroup()
        self.canvas.before.add(self._g)

        self._clip = _RoundedClip(radius_val=self.radius_val)
        self.add_widget(self._clip)

        self._img = Image(fit_mode="contain", size_hint=(1, 1),
                          pos_hint={"x": 0, "y": 0})
        self._clip.add_widget(self._img)

        self._ph_icon = Icon(icon=icon_name, color=C.TEXT_SUB,
                             size=(dp(38), dp(38)),
                             pos_hint={"center_x": 0.5, "center_y": 0.58})
        self._clip.add_widget(self._ph_icon)
        self._ph_label = Label(
            text=hint, font_size=dp(11.5), color=C.TEXT_SUB,
            size_hint=(1, None), height=dp(20),
            pos_hint={"center_x": 0.5, "center_y": 0.30},
            halign="center",
        )
        self._clip.add_widget(self._ph_label)

        self.bind(pos=self._redraw, size=self._redraw,
                  source=self._on_source)
        self._on_source()

    def _on_source(self, *_):
        if self.source:
            self._img.source = self.source
            self._img.opacity = 1
            self._ph_icon.opacity = 0
            self._ph_label.opacity = 0
        else:
            self._img.source = ""
            self._img.opacity = 0
            self._ph_icon.opacity = 0.55
            self._ph_label.opacity = 1

    def reload(self):
        self._img.reload()

    def _redraw(self, *_):
        g = self._g
        g.clear()
        x, y = self.pos
        w, h = self.size
        g.add(Color(*C.FIELD))
        g.add(RoundedRectangle(pos=(x, y), size=(w, h),
                               radius=[self.radius_val]))
        g.add(Color(*C.FIELD_BORDER))
        g.add(Line(rounded_rectangle=(
            x + 0.75, y + 0.75, w - 1.5, h - 1.5, self.radius_val),
            width=1))
        self._clip.pos = (x, y)
        self._clip.size = (w, h)
        self._clip.radius_val = self.radius_val


# =====================================================
# 提示横幅
# =====================================================

_BANNER_STYLE = {
    "error": (C.DANGER_TINT, C.DANGER, "alert"),
    "success": (C.SUCCESS_TINT, C.SUCCESS, "check_circle"),
    "warn": (C.WARN_TINT, C.WARN, "alert"),
    "info": (C.PRIMARY_TINT, C.PRIMARY, "info"),
}


class Banner(BoxLayout):
    kind = StringProperty("info")
    message = StringProperty("")

    def __init__(self, **kw):
        kw.setdefault("orientation", "horizontal")
        kw.setdefault("spacing", dp(8))
        kw.setdefault("padding", [dp(12), 0, dp(12), 0])
        kw.setdefault("size_hint_y", None)
        kw["height"] = 0
        super().__init__(**kw)
        self._g = InstructionGroup()
        self.canvas.before.add(self._g)
        self._icon = Icon(icon="info", size=(dp(17), dp(17)),
                          size_hint=(None, None))
        self._label = Label(font_size=dp(12.5), halign="left", valign="middle",
                            markup=False)
        self._label.bind(size=lambda l, s: setattr(l, "text_size", s))
        self.add_widget(self._icon)
        self.add_widget(self._label)
        self.bind(pos=self._redraw, size=self._redraw)
        self._shown = False
        self.show("")  # 初始即彻底隐藏（含子图标）

    # 兼容旧代码对 .text / .color 的赋值
    @property
    def text(self):
        return self.message

    @text.setter
    def text(self, v):
        self.show(v, self.kind)

    @property
    def color(self):
        return self._icon.color

    @color.setter
    def color(self, v):
        pass

    def show(self, message, kind="info"):
        self.message = message or ""
        self.kind = kind if kind in _BANNER_STYLE else "info"
        if message:
            self.height = dp(42)
            self.opacity = 1
            self._shown = True
        else:
            self.height = 0
            self.opacity = 0
            self._shown = False
        self._redraw()

    def hide(self):
        self.show("")

    def _redraw(self, *_):
        g = self._g
        g.clear()
        x, y = self.pos
        w, h = self.size
        if h <= dp(1) or not self.message:
            return
        tint, fg, ic = _BANNER_STYLE[self.kind]
        g.add(Color(*tint))
        g.add(RoundedRectangle(pos=(x, y), size=(w, h), radius=[dp(10)]))
        self._icon.icon = ic
        self._icon.color = fg
        self._label.color = fg
        self._label.text = self.message
        self._icon.pos = (x + dp(12), y + (h - dp(17)) / 2)


# =====================================================
# 品牌标识 / 用户胶囊
# =====================================================

class LogoMark(FloatLayout):
    def __init__(self, size_dp=48, bg=(1, 1, 1, 1), fg=None, **kw):
        kw.setdefault("size_hint", (None, None))
        kw["size"] = (dp(size_dp), dp(size_dp))
        super().__init__(**kw)
        self._bg = bg
        self._fg = fg or C.PRIMARY
        self._r = dp(size_dp * 0.28)
        ic_size = dp(size_dp * 0.56)
        self._icon = Icon(icon="camera", color=self._fg,
                          size=(ic_size, ic_size))
        self.add_widget(self._icon)
        with self.canvas.before:
            self._c = Color(*bg)
            self._rect = RoundedRectangle(radius=[self._r])
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size
        self._rect.radius = [self._r]
        self._icon.pos = (self.x + (self.width - self._icon.width) / 2,
                          self.y + (self.height - self._icon.height) / 2)


class UserChip(ButtonBehavior, BoxLayout):
    def __init__(self, **kw):
        kw.setdefault("orientation", "horizontal")
        kw.setdefault("spacing", dp(6))
        kw.setdefault("padding", [dp(10), 0, dp(12), 0])
        kw.setdefault("size_hint", (None, None))
        kw.setdefault("height", dp(32))
        super().__init__(**kw)
        self._g = InstructionGroup()
        self.canvas.before.add(self._g)
        self._icon = Icon(icon="user", color=(1, 1, 1, 0.92),
                          size=(dp(15), dp(15)), size_hint=(None, None))
        self._label = Label(font_size=dp(12), color=(1, 1, 1, 0.95),
                            halign="center", valign="middle", bold=True)
        self.add_widget(self._icon)
        self.add_widget(self._label)
        self.bind(pos=self._redraw, size=self._redraw,
                  state=self._redraw)

    def set_text(self, text):
        self._label.text = text
        self._label.texture_update()
        tw = self._label.texture_size[0] if self._label.texture else dp(40)
        self.width = tw + dp(15) + dp(22)

    def _redraw(self, *_):
        g = self._g
        g.clear()
        x, y = self.pos
        w, h = self.size
        a = 0.22 if self.state == "down" else 0.15
        g.add(Color(1, 1, 1, a))
        g.add(RoundedRectangle(pos=(x, y), size=(w, h), radius=[dp(16)]))
        self._icon.pos = (x + dp(10), y + (h - dp(15)) / 2)


# =====================================================
# 弹窗
# =====================================================

def make_dialog(title, body, buttons, width=dp(310), height=None):
    """body: Widget 或 str；buttons: [(text, kind, cb), ...]
    返回 (popup, {text: button})"""
    from kivy.uix.popup import Popup

    content = BoxLayout(orientation="vertical",
                        padding=[dp(20), dp(18), dp(20), dp(16)],
                        spacing=dp(12), size_hint_y=None)
    content.bind(minimum_height=content.setter("height"))

    if title:
        t = Label(text=title, font_size=dp(17), bold=True, color=C.TEXT,
                  size_hint_y=None, height=dp(28),
                  halign="left", valign="middle")
        t.bind(size=lambda l, s: setattr(l, "text_size", s))
        content.add_widget(t)

    if isinstance(body, str):
        msg = Label(text=body, font_size=dp(13.5), color=C.TEXT_SUB,
                    size_hint_y=None, halign="left", valign="top")
        msg.bind(
            width=lambda l, wv: setattr(
                l, "text_size", (wv - dp(4), None)),
        )
        msg.bind(texture_size=lambda l, ts: setattr(l, "height", ts[1]))
        content.add_widget(msg)
    else:
        content.add_widget(body)

    btn_row = BoxLayout(spacing=dp(10), size_hint_y=None, height=dp(44))
    content.add_widget(btn_row)

    card = Card(orientation="vertical", padding=0)
    card.clear_widgets()
    # Card 自带 padding，需要重置后放内容
    card.padding = 0
    card.add_widget(content)

    popup = Popup(
        title="", content=card,
        size_hint=(None, None), size=(width, height or dp(230)),
        separator_height=0, title_size=0,
        background="", background_color=(0, 0, 0, 0),
        auto_dismiss=True,
    )
    if height is None:
        def resize(*_):
            popup.height = max(dp(200), content.height + dp(8))
        content.bind(height=resize)
        Clock = __import__("kivy.clock", fromlist=["Clock"]).Clock
        Clock.schedule_once(resize, -1)

    mapping = {}
    for text, kind, cb in buttons:
        b = AppButton(text=text, kind=kind, height=dp(44))
        b.bind(on_release=lambda btn, fn=cb: (fn() if fn else None,
                                              popup.dismiss()))
        btn_row.add_widget(b)
        mapping[text] = b
    return popup, mapping
