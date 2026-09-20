# photo-app/filedialog_helper.py
"""跨平台文件选择

- Android / iOS：用 plyer
- 桌面（macOS / Linux / Windows）：用 tkinter，不需要额外依赖

对外只暴露两个函数：
    open_file(on_selection, filters)   打开文件
    save_file(on_selection, filters)   保存文件

回调签名：on_selection(list_of_paths)
取消时传空列表。
"""

from kivy.utils import platform


def _is_desktop():
    return platform not in ("android", "ios")


# ==================== 桌面：tkinter ====================
def _tk_open_file(on_selection, filters):
    import tkinter as tk
    from tkinter import filedialog

    # 把 Kivy 的过滤器格式转成 tkinter 的
    tk_filters = []
    for f in filters or []:
        if len(f) >= 2:
            name = f[0]
            patterns = f[1:]
            tk_filters.append((name, " ".join(patterns)))
    if not tk_filters:
        tk_filters = [("所有文件", "*.*")]

    root = tk.Tk()
    root.withdraw()
    root.update()
    try:
        path = filedialog.askopenfilename(
            title="请选择文件",
            filetypes=tk_filters,
        )
    finally:
        root.destroy()

    if path:
        on_selection([path])
    else:
        on_selection([])


def _tk_save_file(on_selection, filters):
    import tkinter as tk
    from tkinter import filedialog

    tk_filters = []
    for f in filters or []:
        if len(f) >= 2:
            name = f[0]
            patterns = f[1:]
            tk_filters.append((name, " ".join(patterns)))
    if not tk_filters:
        tk_filters = [("所有文件", "*.*")]

    root = tk.Tk()
    root.withdraw()
    root.update()
    try:
        path = filedialog.asksaveasfilename(
            title="保存文件",
            filetypes=tk_filters,
            defaultextension=".jpg",
        )
    finally:
        root.destroy()

    if path:
        on_selection([path])
    else:
        on_selection([])


# ==================== 移动端：plyer ====================
def _plyer_open_file(on_selection, filters):
    from plyer import filechooser
    filechooser.open_file(on_selection=on_selection, filters=filters)


def _plyer_save_file(on_selection, filters):
    from plyer import filechooser
    filechooser.save_file(on_selection=on_selection, filters=filters)


# ==================== 对外接口 ====================
def open_file(on_selection, filters=None):
    if _is_desktop():
        return _tk_open_file(on_selection, filters)
    return _plyer_open_file(on_selection, filters)


def save_file(on_selection, filters=None):
    if _is_desktop():
        return _tk_save_file(on_selection, filters)
    return _plyer_save_file(on_selection, filters)