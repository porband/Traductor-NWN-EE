# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['Traductor NWNEE v5.4.py'],
    pathex=[],
    binaries=[],
    datas=[('NWNEE_Traductor_NWN_Style.ico', '.')],
    # Se declaran de forma explícita porque el import está protegido por
    # try/except y el ejecutable debe conservar ambos motores.
    hiddenimports=[
        'deep_translator.google',
        'deep_translator.base',
        'deep_translator.constants',
        'deep_translator.exceptions',
        'deep_translator.validate',
        'deepl',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Traductor NWNEE v5.4',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['NWNEE_Traductor_NWN_Style.ico'],
)
