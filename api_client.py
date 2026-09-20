# photo-app/api_client.py
"""Java 后端接口封装（与桌面客户端 client_app.py 完全对齐）

直连 student-affair-service（经 nginx 反代）：
    默认地址 https://111.12.149.164
    登录       /admin/apiauth/auth/login
    图像处理    /admin/apistudentaffair/admin/photo/**（抠图/OCR/人脸比对，经 Java 转发 Python）
    云端提交    /admin/apistudentaffair/admin/face/**（身份/人脸/特征提取）

所有方法同步调用，返回 (ok: bool, data_or_msg)。
UI 层请用 run_async() 包一层，避免阻塞 Kivy 主线程。
"""

import base64
import threading

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# 响应日志中单条 body 的最大打印字符数（base64 大图截断，避免日志卡死）
MAX_LOG_BODY = 50000


# ==================== 云端接口（Java 后端，全部走 /admin 路径） ====================
DEFAULT_API_BASE = "https://111.12.149.164"
PATH_AUTH_LOGIN = "/admin/apiauth/auth/login"
PATH_FACE_IDENTITY = "/admin/apistudentaffair/admin/face/identity"
PATH_FACE_VERIFY = "/admin/apistudentaffair/admin/face/verify"
PATH_FACE_EXTRACT = "/admin/apistudentaffair/admin/face/extract"


def _file_to_b64(image_path: str) -> str:
    """图片文件 -> Base64 字符串"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


class ApiClient:
    def __init__(self, base_url: str = DEFAULT_API_BASE):
        self.token = ""
        self.username = ""
        self.password = ""
        # 统一 Session：所有请求/响应都经过下面的日志钩子
        self.session = requests.Session()
        self.session.verify = False
        self.session.hooks["response"].append(self._log_http_response)
        self.set_server(base_url)

    # ---------------- 基础 ----------------
    def set_server(self, base_url: str):
        self.base = (base_url or DEFAULT_API_BASE).strip().rstrip("/")
        lowered = self.base.lower()
        if "localhost" in lowered or "127.0.0.1" in lowered:
            self._admin_prefix = "/api/admin"
            self._file_prefix = "/api/file"
        else:
            self._admin_prefix = "/admin/apistudentaffair/admin"
            self._file_prefix = "/admin/apifile"
        self._photo_prefix = self._admin_prefix + "/photo"

    @property
    def logged_in(self) -> bool:
        return bool(self.token)

    def _headers(self, auth: bool = True) -> dict:
        h = {"Content-Type": "application/json"}
        if auth and self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    @staticmethod
    def _is_ok(resp, body) -> bool:
        return resp.status_code == 200 and str(body.get("code")) == "200"

    # ---------------- 统一请求 / 响应日志 ----------------
    @staticmethod
    def _clip(text: str, limit: int = MAX_LOG_BODY) -> str:
        if text is None:
            return ""
        if len(text) <= limit:
            return text
        return text[:limit] + f"\n...<已截断，共 {len(text)} 字符，仅显示前 {limit}>"

    def _log_http_response(self, resp, *args, **kwargs):
        """每个 HTTP 响应都打印：方法、URL、状态码、耗时、完整响应体"""
        req = resp.request
        ct = resp.headers.get("Content-Type", "")
        elapsed = getattr(resp, "elapsed", None)
        ms = f"{elapsed.total_seconds() * 1000:.0f}ms" if elapsed else "?"
        print("\n" + "=" * 72)
        print(f"[HTTP请求] {req.method} {resp.url}")
        # 请求体（JSON 含 base64 时截断）
        body = req.body
        if body:
            if isinstance(body, bytes):
                try:
                    body = body.decode("utf-8", errors="replace")
                except Exception:
                    body = "<binary request body>"
            print(f"[HTTP请求体] {self._clip(str(body), 4000)}")
        print(f"[HTTP响应] {resp.status_code}  耗时 {ms}  "
              f"{len(resp.content)} bytes  Content-Type: {ct or '-'}")
        ctype = ct.lower()
        if "json" in ctype or "text" in ctype or "xml" in ctype or "javascript" in ctype:
            try:
                print("[HTTP响应体]\n" + self._clip(resp.text))
            except Exception as e:
                print(f"[HTTP响应体] <文本读取失败: {e}>")
        else:
            # 二进制（如 OBS 图片直链）只打印摘要，不灌爆日志
            head = resp.content[:16].hex(" ")
            print(f"[HTTP响应体] <二进制 {len(resp.content)} bytes，头字节: {head}>")
        print("=" * 72)

    # ---------------- ① 健康检查 ----------------
    def health(self, timeout: int = 8):
        url = self.base + self._photo_prefix + "/health"
        try:
            r = self.session.get(url, headers=self._headers(),
                             timeout=timeout, verify=False)
            body = r.json()
            if self._is_ok(r, body):
                return True, body.get("data") or {}
            return False, body.get("msg") or "服务异常"
        except requests.exceptions.ConnectionError:
            return False, f"无法连接服务器：{self.base}"
        except requests.exceptions.Timeout:
            return False, "连接服务器超时"
        except Exception as e:
            return False, f"健康检查异常：{e}"

    # ---------------- ② 登录 ----------------
    def login(self, username: str, password: str, timeout: int = 40):
        """直连 Java 后端登录，成功时保存 token"""
        url = self.base + PATH_AUTH_LOGIN
        payload = {
            "identifier": username,
            "password": password,
            "loginType": "WORK_CODE",
            "userType": 1,
        }
        try:
            r = self.session.post(url, json=payload, verify=False, timeout=timeout)
            body = r.json()
            if self._is_ok(r, body) and body.get("data"):
                token = body["data"].get("token")
                if not token:
                    return False, "登录响应中缺少 token"
                self.token = token
                self.username = username
                self.password = password
                return True, "登录成功"
            return False, body.get("msg") or "登录失败"
        except requests.exceptions.ConnectionError:
            return False, f"无法连接服务器：{self.base}"
        except requests.exceptions.Timeout:
            return False, "登录超时"
        except Exception as e:
            return False, f"登录异常：{e}"

    def logout(self):
        self.token = ""
        self.username = ""
        self.password = ""

    # ---------------- 图像处理（Java 转发 Python） ----------------
    def _photo_post(self, path: str, payload: dict, timeout: int = 120):
        url = self.base + self._photo_prefix + path
        try:
            r = self.session.post(url, json=payload, headers=self._headers(),
                              timeout=timeout, verify=False)
            body = r.json()
            if self._is_ok(r, body):
                return True, body.get("data") or {}
            msg = body.get("msg") or f"服务调用失败(HTTP {r.status_code})"
            if "未登录" in msg or "Token" in msg:
                return False, "登录已失效，请重新登录"
            return False, msg
        except requests.exceptions.ConnectionError:
            return False, "无法连接服务器"
        except requests.exceptions.Timeout:
            return False, "请求超时"
        except Exception as e:
            return False, f"请求异常：{e}"

    # ---------------- ③ 人像抠图（客户端本地合成） ----------------
    def segment(self, image_path: str, timeout: int = 60):
        """返回 (ok, {fgPngBase64, srcWidth/Height, faceX/Y/W/H, personTop/Bottom})"""
        return self._photo_post(
            "/id-photo/segment",
            {"facePhotoBase64": _file_to_b64(image_path)},
            timeout=timeout,
        )

    # ---------------- ④ 身份证 OCR ----------------
    def recognize_id_card(self, image_path: str, timeout: int = 120):
        """返回 (ok, info) info 含 name/gender/ethnicity/birth/address/id_number/raw_lines"""
        ok, data = self._photo_post(
            "/id-card/ocr",
            {"idCardPhotoBase64": _file_to_b64(image_path)},
            timeout=timeout,
        )
        if not ok:
            return False, data
        return True, {
            "name": data.get("name", ""),
            "gender": data.get("gender", ""),
            "ethnicity": data.get("ethnicity", ""),
            "birth": data.get("birth", ""),
            "address": data.get("address", ""),
            "id_number": data.get("idNumber", ""),
            "raw_lines": data.get("rawLines", []),
        }

    # ---------------- ⑤ 人脸比对 ----------------
    def compare_face(self, id_card_path: str, face_path: str, timeout: int = 60):
        """返回 (ok, {similarity, level, msg, passed})"""
        ok, data = self._photo_post(
            "/face/compare",
            {
                "idCardPhotoBase64": _file_to_b64(id_card_path),
                "facePhotoBase64": _file_to_b64(face_path),
            },
            timeout=timeout,
        )
        if not ok:
            return False, data
        return True, {
            "similarity": data.get("similarity"),
            "level": data.get("level", "unknown"),
            "msg": data.get("msg", "ok"),
            "passed": data.get("passed", False),
        }

    # ---------------- ⑥ 按身份证号查询考生是否存在（只查询不上传） ----------------
    def query_student(self, sfzjh: str, timeout: int = 30):
        """GET /admin/registrations?sfzjh=xxx，返回 (ok, {exists, ksbs, xm, sfzjh})"""
        if not self.token:
            return False, "未登录"
        url = self.base + self._admin_prefix + "/registrations"
        try:
            r = self.session.get(
                url,
                params={"sfzjh": sfzjh, "pageNum": 1, "pageSize": 1},
                headers=self._headers(), verify=False, timeout=timeout,
            )
            body = r.json()
            if not self._is_ok(r, body):
                return False, body.get("msg") or "查询考生失败"
            data = body.get("data") or {}
            rows = data.get("list") or []
            if not rows:
                return True, {"exists": False}
            stu = rows[0]
            return True, {
                "exists": True,
                "ksbs": str(stu.get("ksbs", "")),
                "xm": stu.get("xm", ""),
                "sfzjh": stu.get("sfzjh", ""),
                "ksh": stu.get("ksh", ""),
                "xb": stu.get("xb", "") or "",
                "mz": stu.get("mz", "") or "",
            }
        except requests.exceptions.ConnectionError:
            return False, "无法连接服务器"
        except requests.exceptions.Timeout:
            return False, "查询超时"
        except Exception as e:
            return False, f"查询异常：{e}"

    # ---------------- ⑥b 分页查询考生列表 ----------------
    def list_students(self, page_num: int = 1, page_size: int = 20,
                      ksh: str = None, sfzjh: str = None, xm: str = None,
                      timeout: int = 30):
        """GET /admin/registrations 分页列表

        返回 (ok, {list, total, page_num, page_size, pages})
        """
        if not self.token:
            return False, "未登录"
        url = self.base + self._admin_prefix + "/registrations"
        params = {"pageNum": page_num, "pageSize": page_size}
        if ksh:
            params["ksh"] = ksh
        if sfzjh:
            params["sfzjh"] = sfzjh
        if xm:
            params["xm"] = xm
        try:
            r = self.session.get(
                url, params=params,
                headers=self._headers(), verify=False, timeout=timeout,
            )
            body = r.json()
            if not self._is_ok(r, body):
                return False, body.get("msg") or "查询考生列表失败"
            data = body.get("data") or {}
            rows = data.get("list") or []
            items = []
            for s in rows:
                zp = s.get("zpdz") or []
                if isinstance(zp, str):
                    zp = [p for p in zp.split(";") if p.strip()]
                # zpdz 按提交顺序存储，最后一条为最新照片；回退打卡照片
                latest_key = zp[-1] if zp else (s.get("facePhotoUrl") or "")
                items.append({
                    "ksbs": str(s.get("ksbs", "")),
                    "xm": s.get("xm", "") or "",
                    "sfzjh": s.get("sfzjh", "") or "",
                    "ksh": s.get("ksh", "") or "",
                    "xxmc": s.get("xxmc", "") or "",
                    "bjmc": s.get("bjmc", "") or "",
                    "xb": s.get("xb", "") or "",
                    "mz": s.get("mz", "") or "",
                    "shzt": s.get("shzt", "") or "",
                    "zpdz": zp,
                    "latest_photo_key": latest_key,
                    "photo_count": s.get("photoCount") or len(zp),
                    "face_photo_url": s.get("facePhotoUrl") or "",
                })
            return True, {
                "list": items,
                "total": int(data.get("total", 0) or 0),
                "page_num": int(data.get("pageNum", page_num) or page_num),
                "page_size": int(data.get("pageSize", page_size) or page_size),
                "pages": int(data.get("pages", 1) or 1),
            }
        except requests.exceptions.ConnectionError:
            return False, "无法连接服务器"
        except requests.exceptions.Timeout:
            return False, "查询超时"
        except Exception as e:
            return False, f"查询异常：{e}"

    # ---------------- ⑥c 照片预览地址 / 下载 ----------------
    def get_photo_preview_url(self, object_key: str, timeout: int = 20):
        """GET /admin/apifile/photos/preview-url?objectKey=xxx → 签名 fileUrl"""
        if not self.token:
            return False, "未登录"
        url = self.base + self._file_prefix + "/photos/preview-url"
        try:
            r = self.session.get(
                url, params={"objectKey": object_key},
                headers=self._headers(), verify=False, timeout=timeout,
            )
            body = r.json()
            if not self._is_ok(r, body):
                return False, body.get("msg") or "获取照片预览地址失败"
            data = body.get("data") or {}
            if not data.get("success"):
                return False, "照片不存在或不可访问"
            file_url = data.get("fileUrl")
            if not file_url:
                return False, "响应中缺少 fileUrl"
            return True, file_url
        except requests.exceptions.ConnectionError:
            return False, "无法连接文件服务"
        except requests.exceptions.Timeout:
            return False, "获取照片地址超时"
        except Exception as e:
            return False, f"获取照片地址异常：{e}"

    def download_photo_bytes(self, object_key: str, timeout: int = 30):
        """先换签名 URL，再下载照片字节，返回 (True, b'...')"""
        ok, res = self.get_photo_preview_url(object_key, timeout=timeout)
        if not ok:
            return False, res
        try:
            r = self.session.get(res, timeout=timeout, verify=False)
            if r.status_code != 200 or not r.content:
                return False, f"照片下载失败（HTTP {r.status_code}）"
            return True, r.content
        except requests.exceptions.Timeout:
            return False, "照片下载超时"
        except Exception as e:
            return False, f"照片下载异常：{e}"

    # ---------------- ⑦ 上传身份证信息（拿 ksbs） ----------------
    def upload_identity(self, id_card_path: str,
                        sfzjh: str, xm: str, xb: str, mz: str,
                        timeout: int = 90):
        """返回 (ok, {ksbs, mismatchedFields})"""
        if not self.token:
            return False, "未登录"
        url = self.base + PATH_FACE_IDENTITY
        payload = {
            "sfzjh": sfzjh, "xm": xm, "xb": xb, "mz": mz,
            "idCardPhotoBase64": _file_to_b64(id_card_path),
            "idCardPhotoContentType": "image/jpeg",
        }
        try:
            r = self.session.post(url, json=payload, headers=self._headers(),
                              verify=False, timeout=timeout)
            body = r.json()
            if self._is_ok(r, body) and body.get("data") is not None:
                d = body["data"]
                return True, {
                    "ksbs": str(d.get("ksbs", "")),
                    "mismatchedFields": d.get("mismatchedFields") or [],
                }
            return False, body.get("msg") or "身份证信息上传失败"
        except requests.exceptions.ConnectionError:
            return False, "无法连接服务器"
        except requests.exceptions.Timeout:
            return False, "上传超时"
        except Exception as e:
            return False, f"上传异常：{e}"

    # ---------------- ⑦ 提交人脸采集（上传证件照 + 特征提取） ----------------
    def submit_face(self, photo_path: str, sfzjh: str, timeout: int = 90):
        """返回 (ok, {extract_msg})"""
        if not self.token:
            return False, "未登录"
        try:
            # 1) 上传合成后的证件照
            r = self.session.post(
                self.base + PATH_FACE_VERIFY,
                json={"sfzjh": sfzjh,
                      "photoBase64": _file_to_b64(photo_path)},
                headers=self._headers(), verify=False, timeout=timeout,
            )
            body = r.json()
            if not self._is_ok(r, body):
                return False, body.get("msg") or "人脸照片上传失败"

            # 2) 提交人脸特征生成任务
            r2 = self.session.post(
                self.base + PATH_FACE_EXTRACT,
                params={"sfzjh": sfzjh},
                headers=self._headers(), verify=False, timeout=30,
            )
            body2 = r2.json()
            if self._is_ok(r2, body2):
                return True, {"extract_msg": body2.get("msg", "任务已提交")}
            return False, body2.get("msg") or "特征提取任务提交失败"
        except requests.exceptions.ConnectionError:
            return False, "无法连接服务器"
        except requests.exceptions.Timeout:
            return False, "提交超时"
        except Exception as e:
            return False, f"提交异常：{e}"

    # ---------------- 图片工具 ----------------
    @staticmethod
    def b64_to_file(b64: str, out_path: str) -> bool:
        """base64 图片写文件，返回是否成功"""
        try:
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(b64))
            return True
        except Exception:
            return False


# ==================== 本地合成（与服务端 calc_geometry 参数一致） ====================

HEAD_TOP_MARGIN = 0.10
MAX_HEAD_HEIGHT_RATIO = 0.75
MAX_HEAD_WIDTH_RATIO = 0.90
HAIR_WIDTH_FACTOR = 1.15
HAIR_HEIGHT_FACTOR = 1.55


class PhotoComposer:
    """抠图结果 + 内置背景图 -> 本地合成证件照，支持拖动偏移"""

    def __init__(self, bg_image_path: str):
        from PIL import Image
        self._bg = Image.open(bg_image_path).convert("RGB")

    def calc_geometry(self, src_w, src_h, face_bbox, person_top,
                      person_bottom, target_w, target_h, scale_extra=1.0):
        fx, fy, fw, fh = face_bbox
        person_span = max(1, person_bottom - person_top)
        scale_fill = (target_h * (1.0 - HEAD_TOP_MARGIN)) / person_span
        scale_cap_h = (target_h * MAX_HEAD_HEIGHT_RATIO) / (fh * HAIR_HEIGHT_FACTOR)
        scale_cap_w = (target_w * MAX_HEAD_WIDTH_RATIO) / (fw * HAIR_WIDTH_FACTOR)
        # 用户缩放：以人脸水平中心、头顶边距为锚点放大/缩小
        scale = min(scale_fill, scale_cap_h, scale_cap_w) * scale_extra
        new_w = int(src_w * scale)
        new_h = int(src_h * scale)
        paste_x = int(target_w / 2 - (fx + fw / 2) * scale)
        paste_y = int(target_h * HEAD_TOP_MARGIN - person_top * scale)
        return scale, paste_x, paste_y, new_w, new_h

    def compose(self, fg_png_b64: str, seg_meta: dict,
                target_w: int, target_h: int,
                dx: float = 0.0, dy: float = 0.0,
                scale_extra: float = 1.0):
        """合成证件照，返回 PIL RGB 图"""
        from io import BytesIO
        from PIL import Image

        fg = Image.open(BytesIO(base64.b64decode(fg_png_b64))).convert("RGBA")
        src_w = seg_meta["srcWidth"]
        src_h = seg_meta["srcHeight"]
        face_bbox = (seg_meta["faceX"], seg_meta["faceY"],
                     seg_meta["faceW"], seg_meta["faceH"])
        person_top = seg_meta["personTop"]
        person_bottom = seg_meta["personBottom"]

        _, paste_x, paste_y, new_w, new_h = self.calc_geometry(
            src_w, src_h, face_bbox, person_top, person_bottom,
            target_w, target_h, scale_extra=scale_extra,
        )

        bg = self._bg.copy()
        bw, bh = bg.size
        scale = max(target_w / bw, target_h / bh)
        new_bw, new_bh = int(bw * scale), int(bh * scale)
        bg = bg.resize((new_bw, new_bh), Image.LANCZOS)
        x1 = (new_bw - target_w) // 2
        y1 = (new_bh - target_h) // 2
        canvas = bg.crop((x1, y1, x1 + target_w, y1 + target_h)).convert("RGBA")

        fg_resized = fg.resize((new_w, new_h), Image.LANCZOS)
        px = int(paste_x + dx)
        py = int(paste_y + dy)
        canvas.alpha_composite(fg_resized, (px, py))
        return canvas.convert("RGB")


# ==================== 异步调用工具 ====================
def run_async(func, on_done, *args, **kwargs):
    """在后台线程里跑 func，完成后回主线程调 on_done(ok, result)

    Kivy 里所有网络请求都应该走这个，否则会卡 UI。
    """
    from kivy.clock import Clock

    def worker():
        try:
            ok, result = func(*args, **kwargs)
        except Exception as e:
            ok, result = False, f"后台任务异常：{e}"

        if not ok:
            print(f"[HTTP结果] {getattr(func, '__name__', 'api')} 失败：{result}")

        # 用 Clock 把回调切回主线程
        Clock.schedule_once(lambda dt: on_done(ok, result), 0)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t
