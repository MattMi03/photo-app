# photo-app/screens/student_list.py
"""考生列表页：调用 /admin/registrations 分页查询，点击考生进入采集页"""

from io import BytesIO

from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.image import Image as KivyImage
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.graphics import Color, Rectangle, Line
from kivy.uix.behaviors import ButtonBehavior
from PIL import Image as PILImage

from api_client import ApiClient, run_async
from state import get_state, ID_NUMBER_RE
from theme import (
    C, AppButton, Banner, RoundedTextInput, UserChip, Icon, vgradient_mesh,
)


PAGE_SIZE = 20
THUMB_W = 70      # dp
THUMB_H = 88      # dp

# objectKey -> Kivy Texture（整页共享，翻页回来不重复下载）
_THUMB_CACHE = {}
# 正在下载的 objectKey，避免同一图片并发请求
_THUMB_INFLIGHT = set()


def _decode_texture(object_key: str, data: bytes):
    """用 PIL 按真实格式解码（扩展名不可靠，.jpeg 可能是 webp），
    缩放成缩略图后转成 Kivy Texture"""
    try:
        im = PILImage.open(BytesIO(data))
        im.load()
        im = im.convert("RGBA")
        # 2 倍密度足够清晰，同时省内存
        im.thumbnail((THUMB_W * 2, THUMB_H * 2), PILImage.LANCZOS)
        tex = Texture.create(size=(im.width, im.height), colorfmt="rgba")
        tex.blit_buffer(im.tobytes(), colorfmt="rgba", bufferfmt="ubyte")
        # PIL 原点在左上，GL 纹理在左下，需要垂直翻转
        tex.flip_vertical()
    except Exception as e:
        print(f"[缩略图] 解码失败 {object_key}: {e}")
        return None
    _THUMB_CACHE[object_key] = tex
    return tex


class StudentRow(ButtonBehavior, BoxLayout):
    """列表中的单条考生卡片"""

    def __init__(self, row: dict, on_pick, thumb_loader=None, **kwargs):
        super().__init__(orientation="horizontal", **kwargs)
        self.padding = [dp(12), dp(10), dp(14), dp(10)]
        self.spacing = dp(12)
        self.size_hint_y = None
        self.height = dp(108)
        self._row = row
        self._on_pick = on_pick
        self._thumb_key = row.get("latest_photo_key", "") or ""
        self._released = False
        self._g_color = None
        self._draw()
        self.bind(pos=self._redraw, size=self._redraw)

        # ---------- 左侧缩略图（最新一张照片） ----------
        thumb_wrap = BoxLayout(size_hint=(None, 1), width=dp(THUMB_W))
        self._thumb_box = FloatLayout(size_hint=(None, None),
                                      size=(dp(THUMB_W), dp(THUMB_H)),
                                      pos_hint={"center_y": 0.5})
        with self._thumb_box.canvas.before:
            self._thumb_bg = Color(*C.PRIMARY_TINT)
            self._thumb_rect = Rectangle(pos=self._thumb_box.pos,
                                         size=self._thumb_box.size)
        self._thumb_box.bind(
            pos=lambda *a: setattr(self._thumb_rect, "pos", self._thumb_box.pos),
            size=lambda *a: setattr(self._thumb_rect, "size", self._thumb_box.size),
        )
        self._thumb_icon = Icon(icon="user", color=C.TEXT_SUB,
                                size=(dp(30), dp(30)),
                                size_hint=(None, None),
                                pos_hint={"center_x": 0.5, "center_y": 0.5})
        self._thumb_box.add_widget(self._thumb_icon)
        self._thumb_img = None
        thumb_wrap.add_widget(self._thumb_box)
        self.add_widget(thumb_wrap)

        # ---------- 右侧文字 ----------
        texts = BoxLayout(orientation="vertical", spacing=dp(4))
        xm = row.get("xm", "") or "（无姓名）"
        sfzjh = row.get("sfzjh", "") or ""
        ksh = row.get("ksh", "") or ""
        org = " · ".join(p for p in (row.get("xxmc", ""), row.get("bjmc", "")) if p)
        tags = " · ".join(p for p in (row.get("xb", ""), row.get("mz", "")) if p)
        photo = row.get("photo_count", 0)

        line1 = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(8))
        name_lbl = Label(
            text=xm, font_size=dp(16), bold=True, color=C.TEXT,
            halign="left", valign="middle", size_hint_x=None, width=dp(90),
        )
        name_lbl.bind(size=lambda l, s: setattr(l, "text_size", s))
        line1.add_widget(name_lbl)
        id_lbl = Label(
            text=sfzjh, font_size=dp(12.5), color=C.TEXT,
            halign="left", valign="middle",
        )
        id_lbl.bind(size=lambda l, s: setattr(l, "text_size", s))
        line1.add_widget(id_lbl)
        texts.add_widget(line1)

        line2 = Label(
            text=f"考生号：{ksh or '—'}" + (f"　{tags}" if tags else ""),
            font_size=dp(11.5), color=C.TEXT_SUB,
            halign="left", valign="middle",
            size_hint_y=None, height=dp(20),
        )
        line2.bind(size=lambda l, s: setattr(l, "text_size", s))
        texts.add_widget(line2)

        line3 = Label(
            text=(org or "—") + f"　照片：{photo} 张",
            font_size=dp(11.5), color=C.TEXT_SUB,
            halign="left", valign="middle",
            size_hint_y=None, height=dp(20),
        )
        line3.bind(size=lambda l, s: setattr(l, "text_size", s))
        texts.add_widget(line3)
        self.add_widget(texts)

        self.bind(on_release=lambda *_: self._on_pick(self._row))

        if self._thumb_key and thumb_loader:
            thumb_loader(self._thumb_key, self._apply_thumb)

    def _apply_thumb(self, tex):
        """异步回调：仅当行仍在显示时设置图片（防错位），按宽高比居中"""
        if self._released or tex is None:
            return
        if self._thumb_img is not None:
            return
        self._thumb_box.remove_widget(self._thumb_icon)
        self._thumb_bg.a = 0
        # 按纹理宽高比在固定框内 contain 居中（避免拉伸/废弃属性）
        tw, th = tex.size
        box_w, box_h = dp(THUMB_W), dp(THUMB_H)
        scale = min(box_w / max(tw, 1), box_h / max(th, 1))
        img = KivyImage(
            texture=tex,
            size_hint=(None, None),
            size=(tw * scale, th * scale),
            pos_hint={"center_x": 0.5, "center_y": 0.5},
        )
        self._thumb_img = img
        self._thumb_box.add_widget(img)

    def release(self):
        self._released = True

    def _draw(self):
        with self.canvas.before:
            self._g_color = Color(*C.CARD)
            self._g_rect = Rectangle(pos=self.pos, size=self.size)
            self._g_line_color = Color(*C.HAIRLINE)
            self._g_line = Line(rectangle=(self.x, self.y, self.width, self.height),
                                width=1)

    def _redraw(self, *_):
        self._g_rect.pos = self.pos
        self._g_rect.size = self.size
        self._g_line.rectangle = (self.x, self.y, self.width, self.height)

    def on_state(self, *_):
        # 按下高亮
        self._g_color.rgba = C.PRIMARY_TINT if self.state == "down" else C.CARD


class StudentListScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.state = get_state()
        self._page = 1
        self._total_pages = 1
        self._total = 0
        self._loaded = False
        self._build_ui()

    # ==================== UI ====================
    def _build_ui(self):
        with self.canvas.before:
            self._bg_c = Color(*C.BG)
            self._bg_r = Rectangle(pos=self.pos, size=self.size)
        self.bind(
            pos=lambda *a: setattr(self._bg_r, "pos", self.pos),
            size=lambda *a: setattr(self._bg_r, "size", self.size),
        )

        root = BoxLayout(orientation="vertical")
        root.add_widget(self._build_appbar())

        # 搜索区
        search_card = BoxLayout(
            orientation="vertical", padding=[dp(12), dp(10), dp(12), dp(10)],
            spacing=dp(8), size_hint_y=None, height=dp(118),
        )
        with search_card.canvas.before:
            Color(1, 1, 1, 1)
            self._search_rect = Rectangle(pos=search_card.pos,
                                          size=search_card.size)
        search_card.bind(
            pos=lambda *a: setattr(self._search_rect, "pos", search_card.pos),
            size=lambda *a: setattr(self._search_rect, "size", search_card.size),
        )

        search_row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(44))
        self.search_input = RoundedTextInput(
            hint_text="姓名 / 身份证号 / 考生号",
        )
        self.search_input.bind(on_text_validate=lambda *_: self._do_search())
        search_row.add_widget(self.search_input)
        self.search_btn = AppButton(
            text="搜索", kind="filled", icon_name="search",
            icon_size=dp(15), font_size=dp(14),
            size_hint=(None, None), size=(dp(84), dp(44)), radius=dp(10),
        )
        self.search_btn.bind(on_release=lambda *_: self._do_search())
        search_row.add_widget(self.search_btn)
        search_card.add_widget(search_row)

        self.banner = Banner()
        search_card.add_widget(self.banner)
        root.add_widget(search_card)

        # 列表
        self.scroll = ScrollView(do_scroll_x=False, bar_width=dp(2),
                                 scroll_type=["content"])
        self.list_box = BoxLayout(orientation="vertical",
                                  size_hint_y=None,
                                  padding=[dp(12), dp(10), dp(12), dp(10)],
                                  spacing=dp(10))
        self.list_box.bind(minimum_height=self.list_box.setter("height"))

        self.empty_label = Label(
            text="", font_size=dp(13), color=C.TEXT_SUB,
            size_hint_y=None, height=dp(80),
        )
        self.list_box.add_widget(self.empty_label)
        self.scroll.add_widget(self.list_box)
        root.add_widget(self.scroll)

        # 分页栏
        pager = BoxLayout(
            spacing=dp(8), padding=[dp(12), dp(6), dp(12), dp(10)],
            size_hint_y=None, height=dp(54),
        )
        with pager.canvas.before:
            Color(1, 1, 1, 1)
            self._pager_rect = Rectangle(pos=pager.pos, size=pager.size)
        pager.bind(
            pos=lambda *a: setattr(self._pager_rect, "pos", pager.pos),
            size=lambda *a: setattr(self._pager_rect, "size", pager.size),
        )
        self.prev_btn = AppButton(
            text="上一页", kind="outlined", font_size=dp(13),
            size_hint=(None, 1), width=dp(84), radius=dp(10),
        )
        self.prev_btn.bind(on_release=lambda *_: self._turn_page(-1))
        pager.add_widget(self.prev_btn)

        self.page_label = Label(
            text="第 0/0 页 · 共 0 人", font_size=dp(12.5),
            color=C.TEXT, halign="center", valign="middle",
        )
        self.page_label.bind(size=lambda l, s: setattr(l, "text_size", s))
        pager.add_widget(self.page_label)

        self.next_btn = AppButton(
            text="下一页", kind="outlined", font_size=dp(13),
            size_hint=(None, 1), width=dp(84), radius=dp(10),
        )
        self.next_btn.bind(on_release=lambda *_: self._turn_page(1))
        pager.add_widget(self.next_btn)
        root.add_widget(pager)

        self.add_widget(root)

    def _build_appbar(self):
        bar = BoxLayout(
            orientation="horizontal", spacing=dp(10),
            padding=[dp(14), 0, dp(12), 0],
            size_hint_y=None, height=dp(58),
        )
        with bar.canvas.before:
            Color(1, 1, 1, 1)
            vgradient_mesh(bar, C.PRIMARY_TOP, C.PRIMARY_BOTTOM)

        self.back_btn = AppButton(
            text="退出", kind="glass", icon_name="arrow_left",
            icon_size=dp(15), font_size=dp(13),
            size_hint=(None, None), size=(dp(72), dp(38)), radius=dp(19),
        )
        self.back_btn.bind(on_release=self._back_to_login)
        bar.add_widget(self.back_btn)

        title_box = BoxLayout(orientation="vertical", size_hint_x=1,
                              padding=[dp(4), dp(8), 0, dp(8)], spacing=0)
        t = Label(text="考生列表", font_size=dp(16), bold=True,
                  color=(1, 1, 1, 1), halign="left", valign="middle")
        t.bind(size=lambda l, s: setattr(l, "text_size", s))
        st = Label(text="选择考生进入证件照采集", font_size=dp(9.5),
                   color=C.WHITE70, halign="left", valign="middle")
        st.bind(size=lambda l, s: setattr(l, "text_size", s))
        title_box.add_widget(t)
        title_box.add_widget(st)
        bar.add_widget(title_box)

        self.direct_btn = AppButton(
            text="直接采集", kind="glass", icon_name="user",
            icon_size=dp(14), font_size=dp(12.5),
            size_hint=(None, None), size=(dp(90), dp(38)), radius=dp(19),
        )
        self.direct_btn.bind(on_release=self._go_direct_collect)
        bar.add_widget(self.direct_btn)

        chip = UserChip()
        chip.set_text(self.state.username or "已登录")
        bar.add_widget(chip)
        return bar

    # ==================== 生命周期 ====================
    def mark_stale(self):
        """标记列表过期，下次进入页面时重新拉取"""
        self._loaded = False

    def on_pre_enter(self, *_):
        if not self.state.logged_in:
            if self.manager:
                self.manager.current = "login"
            return
        if not self._loaded:
            self._load_page(1)

    # ==================== 搜索 / 分页 ====================
    def _new_api(self):
        api = ApiClient(self.state.server_url)
        api.token = self.state.token
        api.username = self.state.username
        return api

    def _do_search(self):
        self._page = 1
        self._load_page(1)

    def _turn_page(self, delta):
        target = self._page + delta
        if target < 1 or target > max(1, self._total_pages):
            return
        self._page = target
        self._load_page(target)

    @staticmethod
    def _parse_keyword(kw: str):
        """把单个搜索词映射到后端参数：(ksh, sfzjh, xm)"""
        kw = (kw or "").strip()
        if not kw:
            return None, None, None
        if ID_NUMBER_RE.match(kw):
            return None, kw, None
        if kw.isdigit():
            return kw, None, None
        return None, None, kw

    def _load_page(self, page_num: int):
        api = self._new_api()
        ksh, sfzjh, xm = self._parse_keyword(self.search_input.text)

        self.search_btn.disabled = True
        self.prev_btn.disabled = True
        self.next_btn.disabled = True
        self.banner.show(f"正在加载第 {page_num} 页...", "info")

        def on_done(ok, result):
            self.search_btn.disabled = False
            if ok and isinstance(result, dict):
                self._loaded = True
                self._total = result.get("total", 0)
                self._total_pages = max(1, result.get("pages", 1))
                self._render_rows(result.get("list", []))
            else:
                self.banner.show(f"加载失败：{result}", "error")
                self.empty_label.text = f"加载失败：{result}"

        run_async(api.list_students, on_done,
                  page_num, PAGE_SIZE, ksh, sfzjh, xm)

    # ==================== 渲染 ====================
    def _render_rows(self, rows):
        # 标记旧行失效，防止晚到的图片回调写到已移除的行
        for w in list(self.list_box.children):
            if isinstance(w, StudentRow):
                w.release()
        self.list_box.clear_widgets()
        self.page_label.text = (
            f"第 {self._page}/{self._total_pages} 页 · 共 {self._total} 人")
        self.prev_btn.disabled = self._page <= 1
        self.next_btn.disabled = self._page >= self._total_pages

        if not rows:
            self.empty_label.text = "没有查到符合条件的考生"
            self.list_box.add_widget(self.empty_label)
            self.banner.show("无数据", "info")
            return

        self.banner.show(f"已加载 {len(rows)} 条", "success")
        for row in rows:
            self.list_box.add_widget(
                StudentRow(row, self._pick_student,
                           thumb_loader=self._load_thumb))
        # 底部留白
        self.list_box.add_widget(Label(size_hint_y=None, height=dp(4),
                                       text=""))

    # ==================== 缩略图加载 ====================
    def _load_thumb(self, object_key, callback):
        """换签名 URL → 下载字节 → 主线程解码纹理；带缓存/去重"""
        tex = _THUMB_CACHE.get(object_key)
        if tex is not None:
            callback(tex)
            return
        if object_key in _THUMB_INFLIGHT:
            # 同一 key 已在下载：稍后用缓存重试一次
            from kivy.clock import Clock
            Clock.schedule_once(
                lambda dt: callback(_THUMB_CACHE.get(object_key)), 0.4)
            return
        _THUMB_INFLIGHT.add(object_key)
        api = self._new_api()

        def on_done(ok, data):
            _THUMB_INFLIGHT.discard(object_key)
            if not ok:
                print(f"[缩略图] 加载失败 {object_key}: {data}")
                return
            tex = _decode_texture(object_key, data)
            if tex is not None:
                callback(tex)

        run_async(api.download_photo_bytes, on_done, object_key)

    # ==================== 选中考生 → 采集页 ====================
    def _pick_student(self, row: dict):
        if self.state.busy:
            return
        self.state.prefill_from_student(row)
        if self.manager:
            self.manager.transition.direction = "left"
            self.manager.current = "main"

    # ==================== 直接采集（不预选考生） ====================
    def _go_direct_collect(self, *_):
        if self.state.busy:
            return
        # 清空上一人资料，进入空白采集页：手输身份证号查找 或 点身份证照片 OCR
        self.state.reset_for_next()
        self.state.status = "直接采集：请输入身份证号查找考生，或点击身份证照片识别"
        self.state.notify()
        if self.manager:
            self.manager.transition.direction = "left"
            self.manager.current = "main"

    def _back_to_login(self, *_):
        if self.manager:
            self.manager.transition.direction = "right"
            self.manager.current = "login"
