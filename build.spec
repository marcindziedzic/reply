# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Email Assistant."""

block_cipher = None

a = Analysis(
    ['src/email_assistant/main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'textual',
        'textual.app',
        'textual.widgets',
        'textual.screen',
        'textual.containers',
        'anthropic',
        'google.auth',
        'google.oauth2',
        'google_auth_oauthlib',
        'googleapiclient',
        'yaml',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='email-assistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
