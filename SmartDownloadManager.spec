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
    'win32gui',
    'win32con',
    'resvg_py',
    'storage_manager',
    'ui',
    'ui.theme',
    'ui.icons',
    'ui.tooltip',
    'ui.tray',
    'ui.app_window',
    'ui.sidebar',
    'ui.toolbar',
    'ui.queue_card',
    'ui.queue_view',
    'ui.recovery_view',
    'ui.modals.add_modal',
    'ui.modals.refresh_modal',
    'ui.modals.batch_modal',
    'ui.modals.ext_setup_modal',
    'ui.modals.settings_modal',
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

# 1. Standalone single-file executable (self-contained, no _internal folder needed)
exe_onefile = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SmartDownloadManager-Standalone',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico',
)

# 2. Directory-based executable (for Inno Setup installer)
exe_onedir = EXE(
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
    exe_onedir,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SmartDownloadManager',
)
