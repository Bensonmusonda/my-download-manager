# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas = [
    ('extension', 'extension'),
    ('app_icon.ico', '.'),
]
binaries = []
hiddenimports = [
    'customtkinter',
    'curl_cffi',
    'libtorrent',
    'browser_cookie3',
    'rich',
    'rich.console',
    'rich.progress',
    'rich.panel',
    'rich.table',
    'rich.text',
    'PIL',
    'PIL.Image',
    'PIL.PngImagePlugin',
    'urllib.request',
    'http.server',
    'socketserver',
]

for pkg in ['customtkinter', 'curl_cffi', 'libtorrent', 'browser_cookie3', 'rich']:
    tmp_datas, tmp_binaries, tmp_hidden = collect_all(pkg)
    datas.extend(tmp_datas)
    binaries.extend(tmp_binaries)
    hiddenimports.extend(tmp_hidden)

# Deduplicate
hiddenimports = list(set(hiddenimports))

a = Analysis(
    ['__main__.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['test_download', 'test_bridge', 'test_queue', 'test_torrent'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SmartDownloadManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SmartDownloadManager',
)
