# photo-app/screens/login.py
"""登录页（移动端风格）"""

from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.metrics import dp
from kivy.graphics import Color, Rectangle

from api_client import ApiClient, DEFAULT_API_BASE, run_async
from state import get_state
from theme import (
    C, Card, AppButton, Banner, IconField, RoundedTextInput,
    LogoMark, vgradient_mesh,
)


class LoginScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.state = get_state()
        self._build_ui()

    # ==================== UI ====================
    def _build_ui(self):
        # 页面底色
        with self.canvas.before:
            self._bg_inst = Color(*C.BG)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda *a: setattr(self._bg_rect, "pos", self.pos),
                  size=lambda *a: setattr(self._bg_rect, "size", self.size))

        scroll = ScrollView(do_scroll_x=False, bar_width=0,
                            scroll_type=["content"])
        root = BoxLayout(orientation="vertical", size_hint_y=None)
        root.bind(minimum_height=root.setter("height"))

        # ---------- 渐变品牌区 + 表单卡片 ----------
        hero = BoxLayout(orientation="vertical", size_hint_y=None,
                         padding=[dp(22), dp(48), dp(22), dp(28)],
                         spacing=0)
        hero.bind(minimum_height=hero.setter("height"))
        with hero.canvas.before:
            Color(1, 1, 1, 1)
            self._hero_mesh = vgradient_mesh(
                hero, C.PRIMARY_TOP, C.PRIMARY_BOTTOM)

        logo = LogoMark(56)
        logo_row = BoxLayout(size_hint_y=None, height=dp(60),
                             orientation="horizontal")
        logo_row.add_widget(logo)
        hero.add_widget(logo_row)
        hero.add_widget(Label(text="", size_hint_y=None, height=dp(16)))

        title = Label(
            text="证件照采集工具",
            font_size=dp(25), bold=True, color=(1, 1, 1, 1),
            size_hint_y=None, height=dp(36),
            halign="left", valign="middle",
        )
        title.bind(size=lambda l, s: setattr(l, "text_size", s))
        hero.add_widget(title)

        subtitle = Label(
            text="证件照处理  ·  人证比对  ·  现场采集",
            font_size=dp(12.5), color=C.WHITE70,
            size_hint_y=None, height=dp(22),
            halign="left", valign="middle",
        )
        subtitle.bind(size=lambda l, s: setattr(l, "text_size", s))
        hero.add_widget(subtitle)
        hero.add_widget(Label(text="", size_hint_y=None, height=dp(26)))

        # 登录卡片
        card = Card(padding=[dp(18), dp(20), dp(18), dp(20)], spacing=dp(14))
        card.size_hint_y = None
        card.bind(minimum_height=card.setter("height"))

        head = Label(
            text="账号登录",
            font_size=dp(18), bold=True, color=C.TEXT,
            size_hint_y=None, height=dp(28),
            halign="left", valign="middle",
        )
        head.bind(size=lambda l, s: setattr(l, "text_size", s))
        card.add_widget(head)

        # ---- 字段 ----
        self.server_input = RoundedTextInput(
            text=self.state.server_url or DEFAULT_API_BASE,
            hint_text="服务器地址，如 https://111.12.149.164",
        )
        card.add_widget(self._field("服务器", "server", self.server_input))

        self.user_input = RoundedTextInput(
            text="", hint_text="账号",
        )
        card.add_widget(self._field("账号", "user", self.user_input))

        self.pwd_raw = RoundedTextInput(
            text="", password=True, hint_text="密码",
        )
        self.eye_btn = AppButton(
            text="", icon_name="eye", kind="text",
            icon_size=dp(20), radius=dp(10),
        )
        self.eye_btn.bind(on_release=self._toggle_pwd)
        self.pwd_input = self.pwd_raw
        card.add_widget(self._field("密码", "lock", self.pwd_raw,
                                    trailing=self.eye_btn))

        # 提示横幅
        self.tip_label = Banner()
        card.add_widget(self.tip_label)

        # 登录按钮
        self.login_btn = AppButton(
            text="登 录", kind="filled", icon_name="arrow_right",
            font_size=dp(16), icon_size=dp(18),
            height=dp(52), radius=dp(14),
        )
        self.login_btn.bind(on_release=self.do_login)
        card.add_widget(self.login_btn)

        hero.add_widget(card)
        hero.add_widget(Label(text="", size_hint_y=None, height=dp(14)))

        # 健康检查
        self.health_btn = AppButton(
            text="测试服务器连接", kind="glass", icon_name="activity",
            font_size=dp(13.5), icon_size=dp(17),
            height=dp(44), radius=dp(22),
        )
        self.health_btn.bind(on_release=self.do_health)
        hrow = BoxLayout(size_hint_y=None, height=dp(44),
                         padding=[dp(60), 0, dp(60), 0])
        hrow.add_widget(self.health_btn)
        hero.add_widget(hrow)

        hero.add_widget(Label(text="", size_hint_y=None, height=dp(28)))
        ver = Label(
            text="现场采集终端  ·  请在工作人员指导下操作",
            font_size=dp(11), color=(1, 1, 1, 0.55),
            size_hint_y=None, height=dp(20),
        )
        hero.add_widget(ver)

        root.add_widget(hero)

        # 弹性留白，保证小屏手机内容也能顶满
        root.add_widget(Label(text="", size_hint_y=None, height=dp(8)))

        scroll.add_widget(root)
        self.add_widget(scroll)

        if self.state.logged_in:
            self.tip_label.show(f"已登录：{self.state.username}", "success")
            self.login_btn.text = "进入考生列表"

    def _field(self, caption, icon_name, input_widget, trailing=None):
        box = BoxLayout(orientation="vertical", spacing=dp(7),
                        size_hint_y=None,
                        height=dp(20) + dp(8) + input_widget.height)
        lbl = Label(
            text=caption, font_size=dp(12.5), bold=True,
            color=C.TEXT_SUB, size_hint_y=None, height=dp(20),
            halign="left", valign="middle",
        )
        lbl.bind(size=lambda l, s: setattr(l, "text_size", s))
        box.add_widget(lbl)
        box.add_widget(IconField(icon_name, input_widget, trailing))
        return box

    def _toggle_pwd(self, *_):
        self.pwd_raw.password = not self.pwd_raw.password
        self.eye_btn.icon_name = "eye_off" if not self.pwd_raw.password else "eye"

    # ==================== 健康检查 ====================
    def do_health(self, *_):
        server = self.server_input.text.strip().rstrip("/")
        if not server:
            self._tip("请填写服务端地址", error=True)
            return

        self._tip("正在检查服务器...", info=True)
        self.health_btn.disabled = True
        api = ApiClient(server)

        def on_done(ok, result):
            self.health_btn.disabled = False
            if ok:
                svc = result.get("service", "photo-id") if isinstance(result, dict) else "photo-id"
                self.tip_label.show(f"服务器连接正常（{svc}）", "success")
            else:
                self._tip(f"服务器异常：{result}", error=True)

        run_async(api.health, on_done)

    # ==================== 登录 ====================
    def do_login(self, *_):
        if self.state.logged_in and self.login_btn.text == "进入考生列表":
            self._go_main()
            return

        server = self.server_input.text.strip().rstrip("/")
        username = self.user_input.text.strip()
        password = self.pwd_raw.text.strip()

        if not server:
            self._tip("请填写服务器地址", error=True)
            return
        if not username or not password:
            self._tip("请填写账号和密码", error=True)
            return

        self.tip_label.show("正在登录...", "info")
        self.login_btn.disabled = True
        self.login_btn.text = "登录中..."

        api = ApiClient(server)

        def on_done(ok, result):
            self.login_btn.disabled = False
            if ok:
                self.state.server_url = server
                self.state.set_logged_in(username=username, token=api.token)
                self.state.password = password
                self.tip_label.show("登录成功", "success")
                self.login_btn.text = "进入考生列表"
                self._go_main()
            else:
                self.login_btn.text = "登 录"
                self._tip(f"登录失败：{result}", error=True)

        run_async(api.login, on_done, username, password)

    # ==================== 工具 ====================
    def _go_main(self):
        if self.manager:
            self.manager.transition.direction = "left"
            self.manager.current = "students"

    def _tip(self, text, error=False, info=False):
        if error:
            self.tip_label.show(text, "error")
        elif info:
            self.tip_label.show(text, "info")
        else:
            self.tip_label.show(text, "success")
