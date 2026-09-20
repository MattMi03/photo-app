# photo-app/screens/main_screen.py
"""采集主页（移动端卡片式布局）

布局（自上而下）：
    渐变 AppBar（Logo + 标题 + 用户胶囊）
    细状态条
    ScrollView：预览卡片 / 流程卡片 / 文件卡片 / 参数卡片 / 身份证表单卡片
    白色底部操作栏（主操作 + 两个二级操作排）

业务逻辑完全保留：select_face / auto_compare / submit_face / reset_for_next ...
"""

import os
import re
import sys
import time
import base64
import tempfile

from kivy.utils import platform
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line
from kivy.graphics.instructions import InstructionGroup

from filedialog_helper import open_file as fd_open_file, save_file as fd_save_file

from api_client import ApiClient, PhotoComposer, run_async
from state import (
    get_state, STANDARD_SIZES,
    SIMILARITY_PASS, SIMILARITY_WARN, NUDGE_STEP,
    SCALE_STEP,
)
from theme import (
    C, Card, Icon, AppButton, Banner,
    SectionHeader, RoundedTextInput,
    DropdownField, Stepper, PhotoBox,
    LogoMark, UserChip, make_dialog, vgradient_mesh,
)

TEMP_DIR = os.path.join(tempfile.gettempdir(), "photo_app")
os.makedirs(TEMP_DIR, exist_ok=True)


def _resource_path(*parts):
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


# 固定背景图（随 App 打包，不可更换）
DEFAULT_BG_IMAGE = _resource_path("assets", "default_bg.jpg")


class MainScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.state = get_state()
        self._updating = False
        self._was_logged_in = False
        self._composer = PhotoComposer(DEFAULT_BG_IMAGE)
        self._dragging = False
        self._drag_start = None
        self._preview_scale = 1.0
        # 双指捏合缩放
        self._touch_points = {}      # touch.uid -> (x, y)
        self._pinching = False
        self._pinch_start_dist = 0.0
        self._pinch_start_scale = 1.0

        self._build_ui()
        self.state.subscribe(self.on_state_changed)
        Clock.schedule_once(lambda dt: self.on_state_changed(self.state), 0)

    # ==================== API ====================
    def _make_api(self):
        api = ApiClient(self.state.server_url)
        api.token = self.state.token
        api.username = self.state.username
        return api

    # ==================== UI 构建 ====================
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
        root.add_widget(self._build_status_strip())

        scroll = ScrollView(do_scroll_x=False, bar_width=dp(0),
                            scroll_type=["content"])
        content = BoxLayout(
            orientation="vertical",
            padding=[dp(12), dp(10), dp(12), dp(14)],
            spacing=dp(12),
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter("height"))
        self._content = content

        content.add_widget(self._build_preview_card())
        content.add_widget(self._build_flow_card())
        content.add_widget(self._build_param_card())
        content.add_widget(self._build_id_form_card())

        scroll.add_widget(content)
        root.add_widget(scroll)

        root.add_widget(self._build_bottom_bar())

        self.add_widget(root)

    # ---------- 顶栏 ----------
    def _build_appbar(self):
        bar = BoxLayout(
            orientation="horizontal", spacing=dp(10),
            padding=[dp(14), 0, dp(12), 0],
            size_hint_y=None, height=dp(58),
        )
        with bar.canvas.before:
            Color(1, 1, 1, 1)
            vgradient_mesh(bar, C.PRIMARY_TOP, C.PRIMARY_BOTTOM)

        logo = LogoMark(38)
        bar.add_widget(logo)

        title_box = BoxLayout(orientation="vertical", size_hint_x=1,
                              padding=[0, dp(8), 0, dp(8)], spacing=0)
        t = Label(text="证件照采集助手", font_size=dp(16), bold=True,
                  color=(1, 1, 1, 1), halign="left", valign="middle")
        t.bind(size=lambda l, s: setattr(l, "text_size", s))
        st = Label(text="Photo Collection Terminal", font_size=dp(9.5),
                   color=C.WHITE70, halign="left", valign="middle")
        st.bind(size=lambda l, s: setattr(l, "text_size", s))
        title_box.add_widget(t)
        title_box.add_widget(st)
        bar.add_widget(title_box)

        self.back_list_btn = AppButton(
            text="列表", kind="glass", icon_name="arrow_left",
            icon_size=dp(14), font_size=dp(12.5),
            size_hint=(None, None), size=(dp(62), dp(36)), radius=dp(18),
        )
        self.back_list_btn.bind(on_release=self._back_to_list)
        bar.add_widget(self.back_list_btn)

        self.login_chip = UserChip()
        self.login_chip.set_text("未登录")
        self.login_chip.bind(on_release=self._back_to_login)
        bar.add_widget(self.login_chip)
        return bar

    def _back_to_list(self, *_):
        if self.manager:
            self.manager.transition.direction = "right"
            self.manager.current = "students"

    def _after_submit_back_to_list(self):
        self.reset_for_next()
        # 列表页重新进入时刷新（照片数等状态已变化）
        if self.manager:
            list_scr = self.manager.get_screen("students")
            if list_scr:
                list_scr.mark_stale()
            self.manager.transition.direction = "right"
            self.manager.current = "students"

    def _back_to_login(self, *_):
        if self.manager:
            self.manager.transition.direction = "right"
            self.manager.current = "login"

    # ---------- 状态条 ----------
    def _build_status_strip(self):
        strip = BoxLayout(
            orientation="horizontal", spacing=dp(7),
            padding=[dp(16), 0, dp(14), 0],
            size_hint_y=None, height=dp(30),
        )
        self.status_icon = Icon(icon="info", color=C.TEXT_SUB,
                                size=(dp(14), dp(14)), size_hint=(None, None))
        self.status_label = Label(
            text="就绪", font_size=dp(12), color=C.TEXT_SUB,
            halign="left", valign="middle",
        )
        self.status_label.bind(
            size=lambda l, s: setattr(l, "text_size", s))
        strip.add_widget(self.status_icon)
        strip.add_widget(self.status_label)
        return strip

    # ---------- 预览卡片 ----------
    def _build_preview_card(self):
        card = self._new_card()

        card.add_widget(SectionHeader("照片预览", "photo"))

        row = BoxLayout(size_hint_y=None, height=dp(212), spacing=dp(10))

        left = BoxLayout(orientation="vertical", spacing=dp(6))
        cap1 = self._caption_row("user", "人脸实时图（点击选图）")
        left.add_widget(cap1)
        self.face_preview = PhotoBox(hint="点击选择人脸照片",
                                     icon_name="user")
        self.face_preview.size_hint_y = 1
        self.face_preview.bind(on_release=self.select_face)
        left.add_widget(self.face_preview)
        row.add_widget(left)

        right = BoxLayout(orientation="vertical", spacing=dp(6))
        cap2 = self._caption_row("photo", "成品证件照（拖动移动·双指缩放）")
        right.add_widget(cap2)
        self.result_preview = PhotoBox(hint="生成后在此预览",
                                       icon_name="photo")
        self.result_preview.size_hint_y = 1
        right.add_widget(self.result_preview)
        row.add_widget(right)

        card.add_widget(row)

        id_box = BoxLayout(orientation="vertical", spacing=dp(6),
                           size_hint_y=None, height=dp(118))
        id_box.add_widget(self._caption_row("id", "身份证照片（点击选图，可跳过）"))
        self.id_preview = PhotoBox(hint="点击选择身份证照片，自动 OCR（也可直接手输号码）",
                                   icon_name="id", height=dp(88))
        self.id_preview.bind(on_release=self.select_id)
        id_box.add_widget(self.id_preview)
        card.add_widget(id_box)

        return card

    def _caption_row(self, icon_name, text):
        row = BoxLayout(size_hint_y=None, height=dp(20), spacing=dp(6))
        ic = Icon(icon=icon_name, color=C.PRIMARY,
                  size=(dp(14), dp(14)), size_hint=(None, None))
        lbl = Label(text=text, font_size=dp(12), bold=True, color=C.TEXT_SUB,
                    halign="left", valign="middle")
        lbl.bind(size=lambda l, s: setattr(l, "text_size", s))
        row.add_widget(ic)
        row.add_widget(lbl)
        return row

    # ---------- 流程卡片 ----------
    def _new_card(self):
        """滚动区里的卡片：高度由内容撑开"""
        card = Card()
        card.size_hint_y = None
        card.bind(minimum_height=card.setter("height"))
        return card

    def _build_flow_card(self):
        card = self._new_card()
        card.add_widget(SectionHeader("采集流程", "check_circle",
                                      tint=C.SUCCESS_TINT, fg=C.SUCCESS))

        self.stepper = Stepper(["身份证号", "查考生", "处理", "提交"])
        card.add_widget(self.stepper)

        locked_box, self._locked_icon, self.locked_label = \
            self._wrap_icon_label("id", dp(15))
        card.add_widget(locked_box)

        sim_box, self._sim_icon, self.similarity_label = \
            self._wrap_icon_label("user", dp(15))
        card.add_widget(sim_box)

        self.locked_label.text = "当前锁定考生：无"
        self.similarity_label.text = "人脸相似度：等待照片..."
        return card

    def _wrap_icon_label(self, icon_name, icon_dp=dp(15)):
        box = BoxLayout(orientation="horizontal", spacing=dp(8),
                        size_hint_y=None, height=dp(22))
        ic = Icon(icon=icon_name, color=C.TEXT_SUB,
                  size=(icon_dp, icon_dp), size_hint=(None, None),
                  pos_hint={"center_y": 0.5})
        lbl = Label(text="", font_size=dp(12), bold=True, color=C.TEXT_SUB,
                    halign="left", valign="middle",
                    size_hint=(None, None), height=dp(22))

        def place(*_):
            lbl.width = max(0, box.width - icon_dp - dp(8))
            lbl.text_size = (lbl.width, None)
            lbl.y = box.y + (box.height - lbl.height) / 2

        box.bind(pos=place, size=place)

        def grow(inst, ts):
            box.height = max(dp(22), ts[1] + dp(4))
            lbl.height = box.height
            place()

        lbl.bind(texture_size=grow)
        box.add_widget(ic)
        box.add_widget(lbl)
        return box, ic, lbl

    # ---------- 参数卡片 ----------
    def _build_param_card(self):
        card = self._new_card()
        card.add_widget(SectionHeader("证件照参数", "sliders"))

        # 规格
        cap = self._mini_caption("规格尺寸")
        card.add_widget(cap)
        self.size_drop = DropdownField(
            options=list(STANDARD_SIZES.keys()),
            selected=self.state.size_name,
            on_select=lambda v: self.on_size_change(None, v),
        )
        card.add_widget(self.size_drop)

        # 背景固定提示
        hint = Label(
            text="背景：内置背景图（固定，不可更换）",
            font_size=dp(12), color=C.TEXT_SUB,
            size_hint_y=None, height=dp(22),
            halign="left", valign="middle",
        )
        hint.bind(size=lambda l, s: setattr(l, "text_size", s))
        card.add_widget(hint)

        return card

    def _mini_caption(self, text):
        lbl = Label(
            text=text, font_size=dp(12), bold=True, color=C.TEXT_SUB,
            size_hint_y=None, height=dp(20),
            halign="left", valign="middle",
        )
        lbl.bind(size=lambda l, s: setattr(l, "text_size", s))
        return lbl

    # ---------- 身份证表单 ----------
    def _build_id_form_card(self):
        card = self._new_card()
        card.add_widget(SectionHeader("身份证信息", "id"))
        hint = Label(
            text="可点身份证照片自动识别；识别有误可直接改号码后点“查找考生”；也可手输号码直接提交证件照",
            font_size=dp(11.5), color=C.TEXT_SUB,
            size_hint_y=None, height=dp(32),
            halign="left", valign="middle",
        )
        hint.bind(size=lambda l, s: setattr(l, "text_size", s))
        card.add_widget(hint)

        self.id_inputs = {}

        # 身份证号码放第一位：输入框 + 手动查找按钮
        card.add_widget(self._mini_caption("身份证号码"))
        num_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        num_ti = RoundedTextInput(
            text="", font_size=dp(14),
            hint_text="18 位身份证号，可手动输入",
        )
        num_ti.bind(text=lambda inst, val:
                    self.on_id_field_change("id_number", val))
        self.id_inputs["id_number"] = num_ti
        num_row.add_widget(num_ti)

        self.query_btn = AppButton(
            text="查找考生", kind="tonal", icon_name="search",
            icon_size=dp(15), font_size=dp(13),
            size_hint=(None, None), size=(dp(104), dp(44)), radius=dp(10),
        )
        self.query_btn.bind(on_release=self.manual_query_student)
        num_row.add_widget(self.query_btn)
        card.add_widget(num_row)

        # 其余字段（OCR 识别后填入，全部可手动修改）
        specs = [
            ("name", "姓名", True),
            ("gender", "性别", True),
            ("ethnicity", "民族", True),
            ("birth", "出生日期", True),
            ("address", "住址", True),
        ]
        for key, label_text, editable in specs:
            cap = self._mini_caption(label_text)
            card.add_widget(cap)
            ti = RoundedTextInput(
                text="", font_size=dp(14), height=dp(44),
                readonly=not editable,
                hint_text="识别后自动填入",
            )
            if editable:
                ti.bind(text=lambda inst, val, k=key:
                        self.on_id_field_change(k, val))
            self.id_inputs[key] = ti
            card.add_widget(ti)

        self.id_status_label = Label(
            text="", font_size=dp(12), color=C.TEXT_SUB,
            size_hint_y=None, height=dp(22),
            halign="left", valign="middle",
        )
        self.id_status_label.bind(
            size=lambda l, s: setattr(l, "text_size", s))
        card.add_widget(self.id_status_label)

        return card

    # ---------- 底部操作栏 ----------
    def _build_bottom_bar(self):
        bar = BoxLayout(
            orientation="vertical",
            padding=[dp(14), dp(10), dp(14), dp(12)],
            spacing=dp(8),
            size_hint_y=None,
        )
        # 高度随内容
        bar.height = dp(10) + dp(50) + dp(36) + dp(44) + dp(40) + dp(16) + dp(16)
        bar._g = InstructionGroup()
        bar.canvas.before.add(bar._g)

        def paint(*_):
            g = bar._g
            g.clear()
            x, y = bar.pos
            w, h = bar.size
            g.add(Color(*C.CARD))
            g.add(RoundedRectangle(
                pos=(x, y), size=(w, h),
                radius=[dp(20), dp(20), 0, 0]))
            g.add(Color(*C.HAIRLINE))
            g.add(Line(points=[x + dp(16), y + h - dp(0.6),
                               x + w - dp(16), y + h - dp(0.6)],
                       width=1))

        bar.bind(pos=paint, size=paint)

        self.start_btn = AppButton(
            text="开始生成证件照", kind="filled",
            icon_name="photo", icon_size=dp(18),
            font_size=dp(15.5), height=dp(50), radius=dp(14),
        )
        self.start_btn.bind(on_release=self.start_process)
        bar.add_widget(self.start_btn)

        # 拖动微调 + 缩放控制行
        adj_row = BoxLayout(spacing=dp(6), size_hint_y=None, height=dp(36))
        self.offset_label = Label(
            text="偏移：0, 0　缩放：100%", font_size=dp(11), color=C.TEXT_SUB,
            halign="left", valign="middle", size_hint_x=1,
        )
        self.offset_label.bind(
            size=lambda l, s: setattr(l, "text_size", s))
        adj_row.add_widget(self.offset_label)

        # 缩小 / 放大（也可在成品图上双指捏合）
        for txt, factor in [("−", 1.0 / SCALE_STEP), ("＋", SCALE_STEP)]:
            b = AppButton(text=txt, kind="outlined",
                          font_size=dp(16), size_hint=(None, None),
                          size=(dp(36), dp(36)), radius=dp(8))
            b.bind(on_release=lambda *_a, f=factor: self._zoom(f))
            adj_row.add_widget(b)

        for icon, ddx, ddy in [("arrow_left", -NUDGE_STEP, 0),
                               ("arrow_up", 0, -NUDGE_STEP),
                               ("arrow_down", 0, NUDGE_STEP),
                               ("arrow_right", NUDGE_STEP, 0)]:
            b = AppButton(text="", icon_name=icon, kind="outlined",
                          icon_size=dp(16), size_hint=(None, None),
                          size=(dp(36), dp(36)), radius=dp(8))
            b.bind(on_release=lambda *_a, dx=ddx, dy=ddy: self._nudge(dx, dy))
            adj_row.add_widget(b)

        self.reset_offset_btn = AppButton(
            text="复位", kind="outlined", icon_name="refresh",
            icon_size=dp(14), font_size=dp(11),
            size_hint=(None, None), size=(dp(56), dp(36)), radius=dp(8),
        )
        self.reset_offset_btn.bind(on_release=self._reset_offset)
        adj_row.add_widget(self.reset_offset_btn)
        bar.add_widget(adj_row)

        row = BoxLayout(spacing=dp(10), size_hint_y=None, height=dp(44))
        self.upload_btn = AppButton(
            text="上传身份证（可选）", kind="tonal", icon_name="upload",
            font_size=dp(14),
        )
        self.upload_btn.bind(on_release=self.upload_identity)
        row.add_widget(self.upload_btn)

        self.submit_btn = AppButton(
            text="提交采集", kind="success", icon_name="check",
            font_size=dp(14),
        )
        self.submit_btn.bind(on_release=self.submit_face)
        row.add_widget(self.submit_btn)
        bar.add_widget(row)

        row2 = BoxLayout(spacing=dp(10), size_hint_y=None, height=dp(40))
        self.save_btn = AppButton(
            text="保存照片", kind="outlined", icon_name="download",
            font_size=dp(13),
        )
        self.save_btn.bind(on_release=self.save_photo)
        row2.add_widget(self.save_btn)

        self.reset_btn = AppButton(
            text="复位下一位", kind="outlined", icon_name="refresh",
            font_size=dp(13),
        )
        self.reset_btn.bind(on_release=self.reset_for_next)
        row2.add_widget(self.reset_btn)
        bar.add_widget(row2)

        return bar

    # ==================== 工具 ====================
    def _toast(self, msg):
        self.state.update(status=msg)

    def _status_style(self, text):
        t = text or ""
        if any(k in t for k in ("失败", "异常", "错误", "告警")):
            return C.DANGER, "alert", "error"
        if t.startswith("正在"):
            return C.PRIMARY, "activity", "info"
        if any(k in t for k in ("完成", "成功", "通过", "已锁定", "已复位")):
            return C.SUCCESS, "check_circle", "success"
        if "⚠" in t or "偏低" in t:
            return C.WARN, "alert", "warn"
        return C.TEXT_SUB, "info", "info"

    # ==================== 图片选择 ====================
    def select_face(self, *_):
        def on_sel(sel):
            if not sel:
                return
            self.state.face_path = sel[0]
            self.state.seg_fg_b64 = None
            self.state.seg_meta = None
            self.state.drag_dx = 0.0
            self.state.drag_dy = 0.0
            self.state.drag_scale = 1.0
            self.state.face_processed = False
            self.state.processed_b64 = None
            self.state.processed_path = None
            self._touch_points.clear()
            self._pinching = False
            self.state.notify()
            self.auto_compare()
        fd_open_file(
            on_selection=on_sel,
            filters=[("图片", "*.jpg", "*.jpeg", "*.png", "*.bmp")],
        )

    def select_id(self, *_):
        def on_sel(sel):
            if not sel:
                return
            self.state.id_path = sel[0]
            self.state.id_info = None
            self.state.identity_sfzjh = None
            self.state.identity_ksbs = None
            self.state.identity_mismatched = []
            self.state.reset_student_query(notify=False)
            self.state.notify()
            self.auto_recognize_id()
            self.auto_compare()
        fd_open_file(
            on_selection=on_sel,
            filters=[("图片", "*.jpg", "*.jpeg", "*.png", "*.bmp")],
        )

    # ==================== 参数 ====================
    def on_size_change(self, spinner, text):
        self.state.size_name = text
        # 规格变化时重新合成（如果已有抠图结果）
        if self.state.seg_fg_b64 and self.state.seg_meta:
            self._render_result()

    # ==================== 身份证字段 ====================
    def on_id_field_change(self, key, value):
        if self._updating:
            return
        if key == "id_number":
            value = value.strip().upper()
        if not self.state.id_info:
            # 没有 OCR 时也允许直接手动输入身份证号码
            if key != "id_number":
                return
            self.state.id_info = {}
        if self.state.id_info.get(key) == value:
            return
        self.state.id_info[key] = value
        if key == "id_number":
            # 号码被手动修改：旧校验结果/考生查询/身份锁定全部失效，需重新查找
            self.state.id_info["valid"] = False
            self.state.reset_student_query(notify=False)
        self._validate_id_local()
        # 号码合法时（手输或 OCR）自动推断性别、生日
        if key == "id_number" and self.state.id_number_ready:
            self._derive_from_id_number()

    def _derive_from_id_number(self):
        """根据 18 位身份证号第 7-14 位、第 17 位推断生日和性别，写入表单"""
        info = self.state.id_info or {}
        num = (info.get("id_number", "") or "").strip().upper()
        if not re.match(r"^\d{17}[\dX]$", num):
            return
        try:
            year, month, day = int(num[6:10]), int(num[10:12]), int(num[12:14])
            gender = "男" if int(num[16]) % 2 == 1 else "女"
            birth = f"{year}年{month}月{day}日"
        except ValueError:
            return
        changed = False
        if info.get("gender", "") != gender:
            info["gender"] = gender
            changed = True
        if info.get("birth", "") != birth:
            info["birth"] = birth
            changed = True
        if changed:
            self.state.notify()

    def _validate_id_local(self):
        info = self.state.id_info or {}
        id_num = info.get("id_number", "").strip().upper()

        if not id_num:
            self.id_status_label.text = ""
            self.id_status_label.color = C.TEXT_SUB
            return

        if len(id_num) != 18:
            self.id_status_label.text = f"身份证号还差 {18 - len(id_num)} 位"
            self.id_status_label.color = C.TEXT_SUB
            return

        if not re.match(r"^\d{17}[\dX]$", id_num):
            self.id_status_label.text = "⚠ 身份证号格式错误"
            self.id_status_label.color = C.DANGER
            return

        weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
        check_map = ['1', '0', 'X', '9', '8', '7', '6', '5', '4', '3', '2']
        try:
            total = sum(int(id_num[i]) * weights[i] for i in range(17))
            expected = check_map[total % 11]
            if id_num[17] != expected:
                self.id_status_label.text = f"⚠ 校验位错误（应为 {expected}）"
                self.id_status_label.color = C.DANGER
                return
        except ValueError:
            self.id_status_label.text = "⚠ 身份证号含无效字符"
            self.id_status_label.color = C.DANGER
            return

        try:
            year, month, day = int(id_num[6:10]), int(id_num[10:12]), int(id_num[12:14])
            gender = "男" if int(id_num[16]) % 2 == 1 else "女"
            birth = f"{year}年{month}月{day}日"
            warnings = []
            if info.get("gender") and info["gender"] != gender:
                warnings.append(f"性别应为「{gender}」")
            if info.get("birth") and info["birth"] != birth:
                warnings.append(f"出生应为「{birth}」")
            if warnings:
                self.id_status_label.text = "⚠ " + "；".join(warnings)
                self.id_status_label.color = C.WARN
            else:
                self.id_status_label.text = "✓ 身份证号校验通过"
                self.id_status_label.color = C.SUCCESS
        except ValueError:
            pass

        info["valid"] = True
        self.state.notify()

    # ==================== 识别 / 比对 ====================
    def auto_recognize_id(self):
        if not self.state.id_path:
            return
        api = self._make_api()
        self.state.update(status="正在识别身份证...")

        def on_done(ok, result):
            if ok and isinstance(result, dict):
                self.state.id_info = result
                self.state.update(status="身份证识别完成")
                # 识别后立即做本地身份证号校验，设置 valid（上传按钮依赖）
                self._validate_id_local()
                # 以身份证号为准推断性别/生日（OCR 可能识别错）
                if self.state.id_number_ready:
                    self._derive_from_id_number()
                # 自动查询后端是否存在该考生（不存在则禁止上传）
                self.auto_query_student()
            else:
                self.state.update(status=f"识别失败：{result}")
                self._alert("识别失败", str(result))

        run_async(api.recognize_id_card, on_done, self.state.id_path)

    # ==================== 考生存在性查询 ====================
    def auto_query_student(self, force=False):
        """按身份证号查询后端考生，存在才允许上传/提交

        OCR 识别后自动调用；手动修改号码后由“查找考生”按钮 force 调用。
        """
        sfzjh = self.state.id_number
        if not self.state.logged_in:
            return
        if not self.state.id_number_ready or not sfzjh:
            return
        # 已针对当前号码查询过就不重复查（手动查找除外）
        if (not force
                and self.state.student_query_sfzjh == sfzjh
                and not self.state.student_querying):
            return
        api = self._make_api()
        self.state.student_querying = True
        self.state.student_query_sfzjh = sfzjh
        self.state.student_exists = False
        self.state.student_ksbs = None
        self.state.student_xm = ""
        self.state.update(status="正在查询考生信息...")

        def on_done(ok, result):
            # 结果回来时用户已换了身份证/号码，则丢弃过期结果
            if self.state.id_number != sfzjh:
                return
            if ok and isinstance(result, dict):
                if result.get("exists"):
                    self.state.apply_student_query(
                        sfzjh, True,
                        ksbs=result.get("ksbs"), xm=result.get("xm", ""),
                        xb=result.get("xb", ""), mz=result.get("mz", ""))
                    self.state.update(
                        status=f"已查到考生：{result.get('xm','')}，可处理并提交证件照")
                else:
                    self.state.apply_student_query(sfzjh, False)
                    self.state.update(status="未查询到该考生，禁止上传/提交")
                    self._alert("无此考生",
                                "后端未查询到该身份证号对应的考生，请核对号码后重新查找。")
            else:
                self.state.student_querying = False
                self.state.update(status=f"考生查询失败：{result}")

        run_async(api.query_student, on_done, sfzjh)

    def manual_query_student(self, *_):
        """“查找考生”按钮：按输入框当前身份证号手动查询"""
        if not self.state.logged_in:
            self._alert("提示", "请先登录")
            return
        sfzjh = self.state.id_number
        if not sfzjh:
            self._alert("提示", "请先输入身份证号码")
            return
        if not self.state.id_number_ready:
            self._alert("身份证号无效", "请输入 18 位且校验位正确的身份证号码。")
            return
        self.auto_query_student(force=True)

    def auto_compare(self):
        if not (self.state.face_path and self.state.id_path):
            return
        api = self._make_api()
        self.state.update(
            status="正在比对...",
            similarity=None, similarity_msg="比对中...",
            similarity_level="unknown",
        )

        def on_done(ok, result):
            if ok and isinstance(result, dict):
                self.state.apply_similarity(
                    result.get("similarity"),
                    msg=result.get("msg", ""),
                    level=result.get("level", "unknown"),
                )
                self.state.update(status="比对完成")
            else:
                self.state.apply_similarity(None, msg=str(result))
                self.state.update(status=f"比对失败：{result}")

        run_async(api.compare_face, on_done,
                  self.state.id_path, self.state.face_path)

    # ==================== 开始处理 ====================
    def start_process(self, *_):
        if not self.state.face_path:
            self._alert("提示", "请先选择人脸照片")
            return

        api = self._make_api()
        self.state.update(busy=True, status="正在抠图处理...",
                          face_processed=False, processed_b64=None,
                          seg_fg_b64=None, seg_meta=None,
                          drag_dx=0.0, drag_dy=0.0, drag_scale=1.0)
        self._touch_points.clear()
        self._pinching = False

        def on_done(ok, result):
            self.state.busy = False
            if ok and isinstance(result, dict):
                fg_b64 = result.get("fgPngBase64", "")
                if not fg_b64:
                    self.state.update(status="抠图失败：空结果")
                    self._alert("失败", "服务端返回空抠图结果")
                    return
                self.state.seg_fg_b64 = fg_b64
                self.state.seg_meta = result
                self.state.drag_dx = 0.0
                self.state.drag_dy = 0.0
                self._render_result()
                self.state.update(status="证件照已生成，可拖动调整位置")
            else:
                self.state.update(status=f"抠图失败：{result}")
                self._alert("抠图失败", str(result))
            self.state.notify()

        run_async(api.segment, on_done, self.state.face_path)

    def _render_result(self):
        """按当前拖动偏移本地合成证件照，更新预览"""
        if not self.state.seg_fg_b64 or not self.state.seg_meta:
            return
        try:
            target_w, target_h = STANDARD_SIZES[self.state.size_name]
            composed = self._composer.compose(
                self.state.seg_fg_b64,
                self.state.seg_meta,
                target_w, target_h,
                dx=self.state.drag_dx, dy=self.state.drag_dy,
                scale_extra=self.state.drag_scale,
            )
            from io import BytesIO
            buf = BytesIO()
            composed.save(buf, format="JPEG", quality=95)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")

            # 每次渲染用唯一文件名，避免 Kivy 按路径缓存导致拖动后预览不刷新
            self._render_seq = getattr(self, "_render_seq", 0) + 1
            old_path = self.state.processed_path
            tmp = os.path.join(TEMP_DIR, f"processed_{self._render_seq}.jpg")
            with open(tmp, "wb") as f:
                f.write(buf.getvalue())

            self.state.processed_b64 = b64
            self.state.processed_path = tmp
            self.state.face_processed = True

            # 直接强制刷新预览（拖动时也立即生效，不依赖状态监听）
            self.result_preview.source = tmp
            self.result_preview.reload()
            # 用 contain 模式下图片的真实显示宽度做手指→照片坐标映射
            img = getattr(self.result_preview, "_img", None)
            disp_w = (img.norm_image_size[0] if img is not None
                      else self.result_preview.width) or 1
            self._preview_scale = disp_w / target_w if target_w > 0 else 1.0

            # 清理上一帧临时文件
            if old_path and old_path != tmp:
                try:
                    os.remove(old_path)
                except OSError:
                    pass
        except Exception as e:
            self.state.update(status=f"合成失败：{e}")
            self._alert("合成失败", str(e))

    # ==================== 拖动微调 ====================
    def _nudge(self, dx, dy):
        if not self.state.face_processed:
            return
        g = self._current_geometry()
        limit_x = g.get("tw", 400)
        limit_y = g.get("th", 500)
        self.state.drag_dx = max(-limit_x, min(limit_x, self.state.drag_dx + dx))
        self.state.drag_dy = max(-limit_y, min(limit_y, self.state.drag_dy + dy))
        self._render_result()
        self._refresh_offset_label()
        self.state.notify()

    def _reset_offset(self, *_):
        if not self.state.face_processed:
            return
        self.state.drag_dx = 0.0
        self.state.drag_dy = 0.0
        self.state.drag_scale = 1.0
        self._render_result()
        self._refresh_offset_label()
        self.state.notify()

    def _zoom(self, factor):
        """按钮缩放：factor>1 放大，<1 缩小"""
        if not self.state.face_processed:
            return
        ns = self.state.clamp_scale(self.state.drag_scale * factor)
        if abs(ns - self.state.drag_scale) < 1e-6:
            return
        self.state.drag_scale = ns
        self._render_result()
        self._refresh_offset_label()
        self.state.notify()

    def _current_geometry(self):
        if not self.state.seg_meta:
            return {}
        tw, th = STANDARD_SIZES[self.state.size_name]
        return {"tw": tw, "th": th}

    @staticmethod
    def _points_dist(p1, p2):
        return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5

    def _refresh_offset_label(self):
        if hasattr(self, "offset_label"):
            self.offset_label.text = (
                f"偏移：{int(self.state.drag_dx)}, {int(self.state.drag_dy)}"
                f"　缩放：{self.state.drag_scale * 100:.0f}%")

    def on_touch_down(self, touch):
        if self.state.face_processed and self._is_on_result_preview(touch):
            touch.grab(self)
            self._touch_points[touch.uid] = (touch.x, touch.y)
            if len(self._touch_points) >= 2:
                # 第二指落下：进入捏合缩放，取消单指拖动
                pts = list(self._touch_points.values())
                self._pinch_start_dist = self._points_dist(pts[0], pts[1])
                self._pinch_start_scale = self.state.drag_scale
                self._pinching = self._pinch_start_dist > 1
                self._dragging = False
            else:
                self._pinching = False
                self._dragging = True
                self._drag_start = (touch.x, touch.y)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            self._touch_points[touch.uid] = (touch.x, touch.y)
            if self._pinching and len(self._touch_points) >= 2:
                pts = list(self._touch_points.values())
                dist = self._points_dist(pts[0], pts[1])
                if self._pinch_start_dist > 0:
                    ns = self._pinch_start_scale * dist / self._pinch_start_dist
                    self.state.drag_scale = self.state.clamp_scale(ns)
                    self._render_result()
                    self._refresh_offset_label()
            elif self._dragging and self._drag_start is not None:
                scale = self._preview_scale if self._preview_scale > 0 else 1.0
                dx_px = (touch.x - self._drag_start[0]) / scale
                # Kivy 触摸 y 轴向上，照片合成坐标 y 轴向下，垂直分量取反
                dy_px = -(touch.y - self._drag_start[1]) / scale
                self._drag_start = (touch.x, touch.y)
                g = self._current_geometry()
                limit_x = g.get("tw", 400)
                limit_y = g.get("th", 500)
                self.state.drag_dx = max(-limit_x, min(limit_x, self.state.drag_dx + dx_px))
                self.state.drag_dy = max(-limit_y, min(limit_y, self.state.drag_dy + dy_px))
                self._render_result()
                self._refresh_offset_label()
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self._touch_points.pop(touch.uid, None)
            if len(self._touch_points) < 2:
                self._pinching = False
            if not self._touch_points:
                self._dragging = False
                self._drag_start = None
            else:
                # 还剩一根手指：继续用它拖动
                self._dragging = True
                self._drag_start = next(iter(self._touch_points.values()))
            self.state.notify()
            return True
        return super().on_touch_up(touch)

    def _is_on_result_preview(self, touch):
        if not hasattr(self, "result_preview"):
            return False
        return self.result_preview.collide_point(*touch.pos)

    # ==================== 保存 ====================
    def _android_pictures_dir(self):
        """安卓应用专属图片目录：/Android/data/<包名>/files/Pictures（无需授权）"""
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Environment = autoclass("android.os.Environment")
        pic_dir = PythonActivity.mActivity.getExternalFilesDir(
            Environment.DIRECTORY_PICTURES)
        if pic_dir is None:
            # 极少数设备外置目录不可用时退回应用内部存储
            return TEMP_DIR
        return pic_dir.getAbsolutePath()

    @staticmethod
    def _android_scan_media(path):
        """通知媒体扫描，让照片立即出现在系统相册/文件管理器"""
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            MediaScannerConnection = autoclass(
                "android.media.MediaScannerConnection")
            MediaScannerConnection.scanFile(
                PythonActivity.mActivity, [path], None, None)
        except Exception as e:
            print(f"[保存] 媒体扫描失败（不影响文件）：{e}")

    def save_photo(self, *_):
        if not self.state.processed_b64:
            self._alert("提示", "还没有可保存的照片")
            return

        # 安卓：直接保存到应用图片目录（SAF 的 content:// 无法用普通文件 API 写）
        if platform == "android":
            try:
                save_dir = os.path.join(self._android_pictures_dir(), "证件照")
                os.makedirs(save_dir, exist_ok=True)
                name = "IDPhoto_" + time.strftime("%Y%m%d_%H%M%S") + ".jpg"
                path = os.path.join(save_dir, name)
                if not ApiClient.b64_to_file(self.state.processed_b64, path):
                    self._alert("保存失败", "写入文件失败")
                    return
                self._android_scan_media(path)
                self._alert("保存成功", f"已保存到：\n{path}")
            except Exception as e:
                self._alert("保存失败", str(e))
            return

        def on_sel(sel):
            if not sel:
                return
            path = sel[0]
            if not path.lower().endswith((".jpg", ".jpeg", ".png")):
                path += ".jpg"
            if ApiClient.b64_to_file(self.state.processed_b64, path):
                self._alert("保存成功", f"已保存到：\n{path}")
            else:
                self._alert("保存失败", "写入文件失败")

        fd_save_file(
            on_selection=on_sel,
            filters=[("JPEG", "*.jpg"), ("PNG", "*.png")],
        )

    # ==================== 上传身份证 ====================
    def _collect_identity_payload(self):
        """汇总当前页面的身份证信息（OCR + 手动修改 + 推断兜底）"""
        info = self.state.id_info or {}
        id_num = (info.get("id_number", "") or "").strip().upper()
        xm = (info.get("name", "") or "").strip() or self.state.student_xm
        xb = (info.get("gender", "") or "").strip()
        if not xb and len(id_num) == 18 and id_num[:17].isdigit():
            xb = "男" if int(id_num[16]) % 2 == 1 else "女"
        mz = (info.get("ethnicity", "") or "").strip()
        csrq = (info.get("birth", "") or "").strip()
        return {"id_num": id_num, "xm": xm, "xb": xb, "mz": mz, "csrq": csrq}

    def _diff_with_student(self, p: dict):
        """当前信息 vs 考生库，返回 [(字段, 当前值, 考生库值), ...]"""
        diffs = []
        pairs = [
            ("姓名", p["xm"], self.state.student_xm),
            ("性别", self._norm_gender(p["xb"]), self._norm_gender(self.state.student_xb)),
            ("民族", self._norm_mz(p["mz"]), self._norm_mz(self.state.student_mz)),
        ]
        for label, cur, ref in pairs:
            if ref and cur and cur != ref:
                diffs.append((label, cur, ref))
        return diffs

    @staticmethod
    def _norm_gender(v):
        v = (v or "").strip()
        if v in ("男", "男性", "M", "m"):
            return "男"
        if v in ("女", "女性", "F", "f"):
            return "女"
        return v

    @staticmethod
    def _norm_mz(v):
        v = (v or "").strip().replace(" ", "")
        # “汉”与“汉族”视为相同
        if v.endswith("族"):
            v = v[:-1]
        return v

    def upload_identity(self, *_):
        info = self.state.id_info or {}
        if not info.get("valid"):
            self._alert("提示", "身份证信息不完整或校验失败")
            return
        if not self.state.logged_in:
            self._alert("提示", "请先登录")
            return
        if not (self.state.student_exists
                and self.state.student_query_sfzjh == self.state.id_number):
            self._alert("无此考生", "后端未查询到该考生信息，禁止上传。")
            return
        if not self.state.id_path:
            self._alert("提示", "请先选择身份证照片")
            return

        p = self._collect_identity_payload()

        # 与考生库逐项比对，不一致要明确提示，由人工核对身份证原件后确认
        diffs = self._diff_with_student(p)
        if diffs:
            lines = "\n".join(
                f"• {label}：当前「{cur}」，考生库「{ref}」"
                for label, cur, ref in diffs
            )
            text = (
                "以下信息与考生库不一致，请务必对照身份证原件核对：\n\n"
                f"{lines}\n\n"
                "确认无误后，将按当前页面（识别/修改后）的信息上传。\n"
                "是否确认上传？"
            )
            self._confirm("信息与考生库不一致", text,
                          on_yes=self._do_upload_identity,
                          confirm_text="核对无误，确认上传")
        else:
            self._do_upload_identity()

    def _do_upload_identity(self):
        p = self._collect_identity_payload()
        api = self._make_api()
        self.state.update(busy=True, status="正在上传身份证信息...")

        def on_done(ok, result):
            self.state.busy = False
            if ok and isinstance(result, dict):
                self.state.identity_sfzjh = p["id_num"]
                self.state.identity_ksbs = result.get("ksbs", "")
                self.state.identity_mismatched = result.get("mismatchedFields") or []
                self.state.update(
                    status=f"身份已锁定 ksbs={self.state.identity_ksbs}"
                )
                msg = f"考生 ksbs：{self.state.identity_ksbs}"
                if self.state.identity_mismatched:
                    msg += "\n\n⚠ 与考籍不一致字段：\n" + \
                           "、".join(self.state.identity_mismatched)
                self._alert("上传成功", msg)
            else:
                self.state.update(status=f"上传失败：{result}")
                self._alert("上传失败", str(result))

        run_async(
            api.upload_identity, on_done,
            self.state.id_path,
            p["id_num"], p["xm"], p["xb"], p["mz"],
        )

    # ==================== 提交人脸 ====================
    def submit_face(self, *_):
        if not self.state.processed_b64:
            self._alert("提示", "请先生成证件照")
            return
        if not self.state.student_confirmed:
            self._alert("提示", "请先输入身份证号并点“查找考生”，确认后端存在该考生")
            return

        sim = self.state.similarity
        if sim is not None and sim < SIMILARITY_WARN:
            self._confirm(
                "人脸相似度告警",
                f"相似度仅 {sim*100:.1f}%，疑似不是同一个人。\n\n"
                "确认继续提交？",
                on_yes=self._show_final_submit_confirm, danger=True,
            )
        elif sim is not None and sim < SIMILARITY_PASS:
            self._confirm(
                "相似度偏低",
                f"相似度 {sim*100:.1f}%，低于推荐阈值。\n\n"
                "确认继续提交？",
                on_yes=self._show_final_submit_confirm, danger=True,
            )
        else:
            self._show_final_submit_confirm()

    def _show_final_submit_confirm(self):
        sim = self.state.similarity
        info = self.state.id_info or {}
        disp_name = info.get("name") or self.state.student_xm or ""
        ksbs = self.state.effective_ksbs or ""
        sim_line = f"\n人脸相似度：{sim*100:.1f}%\n" if sim is not None else ""
        text = (
            f"考生 ksbs：{ksbs}\n"
            f"姓名：{disp_name}\n"
            f"身份证号：{self.state.id_number}"
            + sim_line +
            "\n确认是同一个人，再点确认提交。"
        )
        self._confirm("提交前最后核对", text,
                      on_yes=self._do_submit_face)

    def _do_submit_face(self):
        info = self.state.id_info or {}
        disp_name = info.get("name") or self.state.student_xm or ""
        api = self._make_api()
        self.state.update(busy=True, status="正在提交人脸采集...")

        def on_done(ok, result):
            self.state.busy = False
            if ok and isinstance(result, dict):
                self.state.just_submitted = True
                msg = result.get("extract_msg", "已提交")
                self.state.update(status=f"提交完成：{msg}")
                self._confirm(
                    "提交成功",
                    f"考生 {disp_name} 人脸采集已提交。\n\n"
                    "是否返回考生列表，采集下一位？",
                    on_yes=self._after_submit_back_to_list,
                    confirm_text="返回列表",
                )
            else:
                self.state.update(status=f"提交失败：{result}")
                self._alert("提交失败", str(result))

        run_async(
            api.submit_face, on_done,
            self.state.processed_path,
            self.state.id_number,
        )

    # ==================== 复位 ====================
    def reset_for_next(self, *_):
        self.state.reset_for_next()

    # ==================== 状态刷新 ====================
    def on_state_changed(self, state):
        # 登录成功后若已有身份证号，自动补查考生（覆盖"先输号后登录"）
        became_logged_in = state.logged_in and not self._was_logged_in
        self._was_logged_in = state.logged_in
        if became_logged_in and state.id_number_ready:
            self.auto_query_student()

        if self._updating:
            return
        self._updating = True
        try:
            self._refresh_login()
            self._refresh_params()
            self._refresh_flow()
            self._refresh_previews()
            self._refresh_id_form()
            self._refresh_buttons()
            self._refresh_status()
        finally:
            self._updating = False

    def _refresh_login(self):
        if self.state.logged_in:
            self.login_chip.set_text(f"  {self.state.username}  ")
        else:
            self.login_chip.set_text("未登录")

    def _refresh_params(self):
        if self.size_drop.value != self.state.size_name:
            self.size_drop.value = self.state.size_name
        self._refresh_offset_label()

    def _refresh_flow(self):
        st = self.state.flow_states()
        cur = self.state.current_step()
        done = [st[1], st[2], st[3], st[4]]
        self.stepper.set_states(done, cur)

        self.locked_label.text = self.state.locked_student_text()
        if self.state.identity_locked:
            if self.state.identity_mismatched:
                self.locked_label.color = C.WARN
                self._locked_icon.color = C.WARN
                self._locked_icon.icon = "alert"
            else:
                self.locked_label.color = C.SUCCESS
                self._locked_icon.color = C.SUCCESS
                self._locked_icon.icon = "check_circle"
        elif self.state.student_querying:
            self.locked_label.text = "正在查询考生信息..."
            self.locked_label.color = C.TEXT_SUB
            self._locked_icon.color = C.TEXT_SUB
            self._locked_icon.icon = "id"
        elif (self.state.student_query_sfzjh == self.state.id_number
              and self.state.student_query_sfzjh):
            if self.state.student_exists:
                ksbs = self.state.student_ksbs or ""
                xm = self.state.student_xm or ""
                self.locked_label.text = f"✓ 已查到考生：{xm}（ksbs={ksbs}），可处理并提交证件照"
                self.locked_label.color = C.SUCCESS
                self._locked_icon.color = C.SUCCESS
                self._locked_icon.icon = "check_circle"
            else:
                self.locked_label.text = "✗ 未查到该考生，禁止上传/提交，请核对号码后重新查找"
                self.locked_label.color = (0.9, 0.2, 0.2, 1)
                self._locked_icon.color = (0.9, 0.2, 0.2, 1)
                self._locked_icon.icon = "alert"
        else:
            self.locked_label.color = C.TEXT_SUB
            self._locked_icon.color = C.TEXT_SUB
            self._locked_icon.icon = "id"

        self.similarity_label.text = self.state.similarity_text()
        col = self.state.similarity_color()
        self.similarity_label.color = col
        self._sim_icon.color = col

    def _refresh_previews(self):
        src = self.state.face_path or ""
        if self.face_preview.source != src:
            self.face_preview.source = src
            self.face_preview.reload()

        src = self.state.processed_path or ""
        if self.result_preview.source != src:
            self.result_preview.source = src
            self.result_preview.reload()

        # 计算拖动坐标映射：contain 模式下图片真实显示宽度 / 照片实际宽度
        if self.state.processed_path and hasattr(self, "result_preview"):
            tw = STANDARD_SIZES[self.state.size_name][0]
            img = getattr(self.result_preview, "_img", None)
            disp_w = (img.norm_image_size[0] if img is not None
                      else self.result_preview.width) or 1
            self._preview_scale = disp_w / tw if tw > 0 else 1.0

        src = self.state.id_path or ""
        if self.id_preview.source != src:
            self.id_preview.source = src
            self.id_preview.reload()

    def _refresh_id_form(self):
        info = self.state.id_info or {}
        mapping = {
            "name": info.get("name", ""),
            "gender": info.get("gender", ""),
            "ethnicity": info.get("ethnicity", ""),
            "birth": info.get("birth", ""),
            "address": info.get("address", ""),
            "id_number": info.get("id_number", ""),
        }
        for k, v in mapping.items():
            ti = self.id_inputs.get(k)
            if ti and ti.text != v:
                ti.text = v

    def _refresh_buttons(self):
        self.start_btn.disabled = not self.state.can_start_process
        self.save_btn.disabled = not bool(self.state.processed_b64)
        self.upload_btn.disabled = not self.state.can_upload_identity
        self.submit_btn.disabled = not self.state.can_submit_face
        self.query_btn.disabled = (self.state.student_querying
                                   or not self.state.logged_in
                                   or not self.state.id_number_ready)

    def _refresh_status(self):
        text = self.state.status or ""
        self.status_label.text = text
        col, ic, _ = self._status_style(text)
        self.status_label.color = col
        self.status_icon.color = col
        self.status_icon.icon = ic

    # ==================== 弹窗 ====================
    def _alert(self, title, msg):
        popup, _ = make_dialog(title, msg, [("确定", "filled", None)])
        popup.open()

    def _confirm(self, title, msg, on_yes=None, danger=False,
                 confirm_text="确认", cancel_text="取消"):
        """非阻塞确认弹窗：点“确认”后回调 on_yes()，点取消/外部点击不回调

        不能在主线程自旋等待，否则弹窗收不到触摸事件会直接卡死。
        """
        kind = "danger" if danger else "filled"
        popup, btns = make_dialog(
            title, msg,
            [(cancel_text, "outlined", None),
             (confirm_text, kind, None)],
        )
        confirmed = {"value": False}

        def on_yes_cb(*_):
            confirmed["value"] = True
            popup.dismiss()

        def on_dismiss(*_):
            if confirmed["value"] and on_yes:
                on_yes()

        btns[confirm_text].bind(on_release=on_yes_cb)
        popup.bind(on_dismiss=on_dismiss)
        popup.open()

    def _confirm_exit(self):
        def do_exit():
            from kivy.app import App
            App.get_running_app().stop()
        self._confirm("退出", "确认退出 App？", do_exit)
