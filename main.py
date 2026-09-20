# photo-app/main.py
"""证件照采集 App —— Kivy 主入口"""

import os
import sys

# ==================== macOS 先初始化 Tk，避免 SDL2 冲突 ====================
# 仅桌面 macOS 需要；安卓/iOS/Linux/Windows 都不执行
if sys.platform == "darwin":
    try:
        import tkinter as _tk
        _tk_root = _tk.Tk()
        _tk_root.withdraw()
        print("[Tk] 已创建隐藏根窗口，避免 SDL2 冲突")
    except Exception as _e:
        print(f"[Tk] 初始化失败：{_e}")

os.environ.setdefault("KIVY_NO_ARGS", "1")

from kivy.app import App

from kivy.core.window import Window
from kivy.core.text import LabelBase
from kivy.uix.screenmanager import ScreenManager
from kivy.utils import platform

# ==================== 中文字体 ====================
# 不注册的话，中文会显示成方块 □□□
if platform in ("android", "ios"):
    # 优先打包内置资产（用 __file__ 定位，安卓上工作目录不可靠）；
    # 找不到时回退到 Android 系统自带 CJK 字体
    _app_dir = os.path.dirname(os.path.abspath(__file__))
    FONT_CANDIDATES = [
        os.path.join(_app_dir, "assets", "fonts", "NotoSansCJK.ttc"),
        "/system/fonts/NotoSansCJK-Regular.ttc",
        "/system/fonts/NotoSansSC-Regular.otf",
        "/system/fonts/NotoSansSC-Regular.ttc",
        "/system/fonts/DroidSansFallback.ttf",
    ]
else:
    # macOS 优先用 ttf，ttc 有时加载不了
    FONT_CANDIDATES = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Light.ttf",
        "/System/Library/Fonts/PingFang.ttc",
    ]

_font_path = None
for _p in FONT_CANDIDATES:
    if os.path.exists(_p):
        _font_path = _p
        break

if _font_path:
    try:
        LabelBase.register(
            name="Roboto",
            fn_regular=_font_path,
            fn_bold=_font_path,
            fn_italic=_font_path,
            fn_bolditalic=_font_path,
        )
        print(f"[字体] 已注册：{_font_path}")
    except Exception as _e:
        print(f"[字体] 注册失败（将使用系统默认字体）：{_e}")
else:
    print("[字体] 警告：未找到任何中文字体，中文可能显示为方块")

# ==================== 页面 ====================
from screens.login import LoginScreen
from screens.student_list import StudentListScreen
from screens.main_screen import MainScreen


class PhotoApp(App):
    title = "证件照采集工具"

    def build(self):
        if platform not in ("android", "ios"):
            Window.size = (480, 900)

        sm = ScreenManager()
        sm.add_widget(LoginScreen(name="login"))
        sm.add_widget(StudentListScreen(name="students"))
        sm.add_widget(MainScreen(name="main"))
        return sm


if __name__ == "__main__":
    PhotoApp().run()