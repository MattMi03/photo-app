# photo-app/state.py
"""全局状态对象

集中管理：
- 服务端连接信息
- 用户登录信息
- 当前正在处理的考生信息
- 流程状态

所有页面共享一个 AppState 实例，通过 subscribe/notify 实现 UI 联动。

用法：
    from state import get_state
    state = get_state()
    state.subscribe(on_state_changed)   # 状态变化时回调
    state.update(status="处理中...")     # 改字段并通知
"""

import re


# 身份证号基本格式（18 位，末位可为 X）
ID_NUMBER_RE = re.compile(r"^\d{17}[\dX]$")


# ==================== 常量（和服务端 config.py 保持一致） ====================
STANDARD_SIZES = {
    "一寸   (25×35mm)": (295, 413),
    "小一寸 (22×32mm)": (260, 378),
    "大一寸 (33×48mm)": (390, 567),
    "二寸   (35×49mm)": (413, 579),
    "小二寸 (35×45mm)": (413, 531),
    "大二寸 (35×53mm)": (413, 626),
}

# 背景固定为内置 default_bg.jpg，不可更换
BG_OPTIONS = []

SIMILARITY_PASS = 0.50
SIMILARITY_WARN = 0.35

# 拖动微调步长（像素）
NUDGE_STEP = 2

# 缩放范围与按钮步长（相对倍数）
SCALE_MIN = 0.6
SCALE_MAX = 2.0
SCALE_STEP = 1.05


class AppState:
    def __init__(self):
        # ---- 服务端（直连 Java 后端，与桌面客户端同一地址） ----
        from api_client import DEFAULT_API_BASE
        self.server_url = DEFAULT_API_BASE

        # ---- 登录 ----
        self.logged_in = False
        self.token = ""
        self.username = ""
        self.password = ""        # 仅存内存，App 关掉就丢

        # ---- 文件路径 ----
        self.face_path = None
        self.id_path = None

        # ---- 参数 ----
        self.size_name = list(STANDARD_SIZES.keys())[0]

        # ---- 身份证信息 ----
        # dict: name/gender/ethnicity/birth/address/id_number/valid/msg
        self.id_info = None

        # ---- 身份锁定 ----
        self.identity_sfzjh = None
        self.identity_ksbs = None
        self.identity_mismatched = []   # list[str]

        # ---- 考生存在性查询（OCR 后自动查后端，只查询不上传） ----
        self.student_query_sfzjh = None    # 已查询的身份证号（防止结果串号）
        self.student_querying = False      # 是否正在查询
        self.student_exists = False        # 后端是否存在该考生
        self.student_ksbs = None           # 查询到的考生标识
        self.student_xm = ""               # 考生库姓名
        self.student_xb = ""               # 考生库性别
        self.student_mz = ""               # 考生库民族

        # ---- 抠图结果与拖动状态 ----
        self.seg_fg_b64 = None          # 透明 PNG base64
        self.seg_meta = None            # src 尺寸 / 人脸框 / 人像上下界
        self.drag_dx = 0.0              # 用户水平偏移（照片像素）
        self.drag_dy = 0.0              # 用户垂直偏移（照片像素）
        self.drag_scale = 1.0           # 用户缩放倍数（1.0 = 默认）

        # ---- 人脸处理 ----
        self.processed_b64 = None       # base64 字符串
        self.processed_path = None      # 已解码到本地的临时图片路径
        self.face_processed = False

        # ---- 相似度 ----
        self.similarity = None          # float | None
        self.similarity_msg = ""
        self.similarity_level = "unknown"   # pass / warn / fail / unknown

        # ---- 提交 ----
        self.just_submitted = False

        # ---- UI 提示 ----
        self.status = "就绪"
        self.busy = False

        # ---- 监听器 ----
        self._listeners = []

    # ==================== 订阅 / 通知 ====================
    def subscribe(self, callback):
        """注册回调，状态变化时调用 callback(state)"""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unsubscribe(self, callback):
        if callback in self._listeners:
            self._listeners.remove(callback)

    def notify(self):
        for cb in list(self._listeners):
            try:
                cb(self)
            except Exception as e:
                print(f"[State] listener 异常：{e}")

    def update(self, **kwargs):
        """批量更新字段，有变化才通知"""
        changed = False
        for k, v in kwargs.items():
            if hasattr(self, k) and getattr(self, k) != v:
                setattr(self, k, v)
                changed = True
        if changed:
            self.notify()

    # ==================== 派生属性 ====================
    @property
    def id_number(self) -> str:
        return (self.id_info or {}).get("id_number", "")

    @property
    def id_fields_valid(self) -> bool:
        """身份证字段完整且通过校验"""
        if not self.id_path:
            return False
        info = self.id_info or {}
        if not info.get("valid"):
            return False
        return all(info.get(k) for k in
                   ("name", "gender", "ethnicity", "id_number"))

    @property
    def id_number_ready(self) -> bool:
        """身份证号已就绪且校验通过（不要求拍身份证/姓名等，支持手动输入）"""
        info = self.id_info or {}
        num = self.id_number
        return bool(info.get("valid")) and bool(ID_NUMBER_RE.match(num or ""))

    @property
    def student_confirmed(self) -> bool:
        """后端已查到该身份证号对应的考生"""
        return (self.student_exists
                and bool(self.student_query_sfzjh)
                and self.student_query_sfzjh == self.id_number)

    @property
    def effective_ksbs(self):
        """优先用上传身份证返回的 ksbs，否则用查询到的 ksbs"""
        return self.identity_ksbs or self.student_ksbs

    @property
    def identity_locked(self) -> bool:
        """身份证信息已上传，且号码一致"""
        return bool(self.identity_sfzjh) and self.identity_sfzjh == self.id_number

    @property
    def can_upload_identity(self) -> bool:
        # 有身份证照片 + 身份证号合法（允许手动修正 OCR 错误）+ 后端查到考生即可
        # 不强制要求 OCR 识别出姓名/性别/民族（后端会用证件照自行核验）
        return (self.logged_in and bool(self.id_path)
                and self.id_number_ready
                and self.student_confirmed
                and not self.busy)

    @property
    def can_submit_face(self) -> bool:
        # 查到考生即可提交证件照；上传身份证（身份核验）不是必须步骤
        return (self.logged_in and self.student_confirmed
                and self.face_processed and bool(self.processed_b64)
                and not self.busy)

    @property
    def can_start_process(self) -> bool:
        return bool(self.face_path) and not self.busy

    # ==================== 流程状态 ====================
    def flow_states(self) -> dict:
        """返回 {1: bool, 2: bool, 3: bool, 4: bool}，对应 4 个步骤"""
        return {
            1: self.id_number_ready,
            2: self.student_confirmed,
            3: self.face_processed and bool(self.processed_b64),
            4: (self.just_submitted and self.student_confirmed
                and self.face_processed),
        }

    def current_step(self) -> int:
        """当前应执行的步骤号 1~4；全完成返回 0"""
        st = self.flow_states()
        for i in (1, 2, 3, 4):
            if not st[i]:
                return i
        return 0

    def locked_student_text(self) -> str:
        """给 UI 显示的锁定考生信息"""
        if not self.identity_locked:
            return "当前锁定考生：无（请先识别并上传身份证信息）"
        name = (self.id_info or {}).get("name", "")
        txt = (f"当前锁定考生：ksbs={self.identity_ksbs}　"
               f"姓名={name}　身份证号={self.id_number}")
        if self.identity_mismatched:
            txt += "　⚠ 与考籍不一致：" + "、".join(self.identity_mismatched)
        return txt

    # ==================== 相似度 ====================
    def apply_similarity(self, sim, msg="", level=None):
        """更新相似度结果；level 不传则根据阈值自动判定"""
        self.similarity = sim
        self.similarity_msg = msg
        if level is None:
            if sim is None:
                level = "unknown"
            elif sim >= SIMILARITY_PASS:
                level = "pass"
            elif sim >= SIMILARITY_WARN:
                level = "warn"
            else:
                level = "fail"
        self.similarity_level = level
        self.notify()

    def similarity_text(self) -> str:
        if self.similarity is None:
            return f"人脸相似度：{self.similarity_msg or '等待比对...'}"
        pct = f"{self.similarity * 100:.1f}%"
        if self.similarity_level == "pass":
            return f"人脸相似度：{pct}  ✓ 通过"
        elif self.similarity_level == "warn":
            return f"人脸相似度：{pct}  ⚠ 偏低，请人工核对"
        elif self.similarity_level == "fail":
            return f"人脸相似度：{pct}  ✗ 疑似非同一人"
        return f"人脸相似度：{pct}"

    def similarity_color(self):
        """给 Kivy 用的 RGBA 颜色元组"""
        if self.similarity is None:
            return (0.5, 0.5, 0.5, 1)
        if self.similarity_level == "pass":
            return (0.1, 0.7, 0.1, 1)
        elif self.similarity_level == "warn":
            return (0.8, 0.4, 0.0, 1)
        return (0.9, 0.1, 0.1, 1)

    # ==================== 登录状态 ====================
    def set_logged_in(self, username, token):
        self.logged_in = True
        self.username = username
        self.token = token
        self.notify()

    def set_logged_out(self):
        self.logged_in = False
        self.token = ""
        self.username = ""
        self.password = ""
        self.notify()

    # ==================== 考生存在性查询 ====================
    def reset_student_query(self, notify=True):
        """清空考生查询结果（换身份证照片/号码变化时调用）"""
        self.student_query_sfzjh = None
        self.student_querying = False
        self.student_exists = False
        self.student_ksbs = None
        self.student_xm = ""
        self.student_xb = ""
        self.student_mz = ""
        if notify:
            self.notify()

    def apply_student_query(self, sfzjh, exists, ksbs=None, xm="",
                            xb="", mz=""):
        """写入按身份证号查询考生的结果"""
        self.student_querying = False
        self.student_query_sfzjh = sfzjh
        self.student_exists = bool(exists)
        self.student_ksbs = ksbs if exists else None
        self.student_xm = xm if exists else ""
        self.student_xb = xb if exists else ""
        self.student_mz = mz if exists else ""
        self.notify()

    @staticmethod
    def clamp_scale(v) -> float:
        return max(SCALE_MIN, min(SCALE_MAX, float(v)))

    # ==================== 从考生列表带入 ====================
    def prefill_from_student(self, row: dict):
        """从考生列表点击进入采集页：重置上一人资料并预填身份信息

        row 字段：ksbs/xm/sfzjh/ksh/xxmc/bjmc/xb/mz/...
        """
        sfzjh = (row.get("sfzjh") or "").strip()
        xm = (row.get("xm") or "").strip()
        # 先清空上一人（保留登录态）
        self.face_path = None
        self.id_path = None
        self.identity_sfzjh = None
        self.identity_ksbs = None
        self.identity_mismatched = []
        self.seg_fg_b64 = None
        self.seg_meta = None
        self.drag_dx = 0.0
        self.drag_dy = 0.0
        self.drag_scale = 1.0
        self.processed_b64 = None
        self.processed_path = None
        self.face_processed = False
        self.similarity = None
        self.similarity_msg = ""
        self.similarity_level = "unknown"
        self.just_submitted = False

        # 预填身份证信息（来自后端列表，视为权威数据）
        self.id_info = {
            "name": xm,
            "gender": row.get("xb", "") or "",
            "ethnicity": row.get("mz", "") or "",
            "birth": "",
            "address": "",
            "id_number": sfzjh,
            "valid": bool(ID_NUMBER_RE.match(sfzjh or "")),
            "msg": "来自考生列表",
        }
        # 直接标记为"已查到考生"，进入采集页无需再查
        self.student_querying = False
        self.student_query_sfzjh = sfzjh
        self.student_exists = True
        self.student_ksbs = str(row.get("ksbs", ""))
        self.student_xm = xm
        self.student_xb = row.get("xb", "") or ""
        self.student_mz = row.get("mz", "") or ""
        self.busy = False
        self.status = f"已选择考生：{xm}，请点击人脸图拍照/选图"
        self.notify()

    # ==================== 复位（单人单次） ====================
    def reset_for_next(self):
        """清空考生相关状态，保留登录、服务端配置"""
        self.face_path = None
        self.id_path = None

        self.id_info = None
        self.identity_sfzjh = None
        self.identity_ksbs = None
        self.identity_mismatched = []

        self.reset_student_query(notify=False)

        self.seg_fg_b64 = None
        self.seg_meta = None
        self.drag_dx = 0.0
        self.drag_dy = 0.0
        self.drag_scale = 1.0

        self.processed_b64 = None
        self.processed_path = None
        self.face_processed = False

        self.similarity = None
        self.similarity_msg = ""
        self.similarity_level = "unknown"

        self.just_submitted = False
        self.status = "已复位，请开始下一位：① 选身份证照片"
        self.notify()


# ==================== 全局单例 ====================
_STATE = None


def get_state() -> AppState:
    global _STATE
    if _STATE is None:
        _STATE = AppState()
    return _STATE