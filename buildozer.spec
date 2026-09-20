[app]

# 应用信息
title = 证件照采集
package.name = photocollect
package.domain = edu.qhjy

source.dir = .
source.include_exts = py,png,jpg,jpeg,ttc,ttf,otf,json
source.exclude_patterns = bin/*, .buildozer/*, __pycache__/*, *.pyc, .git/*, venv/*, .venv/*

version = 1.0.0

requirements = python3==3.13.9, hostpython3==3.13.9, pip==24.0, kivy==2.3.1, pillow, plyer, requests, openssl, sqlite3, pyjnius, android, setuptools, wheel, certifi, charset-normalizer, idna, urllib3

# 竖屏
orientation = portrait
fullscreen = 0

# 图标 / 启动屏
icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/presplash.png

# ----------------------------
# Android 配置
# ----------------------------
android.api = 33
android.minapi = 21
android.ndk = 25b

# 主流架构（现代手机 arm64，老设备 armv7）
android.archs = arm64-v8a, armeabi-v7a

# 只需联网；选照片由系统选择器（含相册/相机）完成，无需额外权限
android.permissions = INTERNET

android.allow_backup = True
android.accept_sdk_license = True

# 构建日志
log_level = 2
