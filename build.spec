# PyInstaller spec — bundles server.py + the game database + the prebuilt
# React frontend into a single executable.  Build with:
#     pyinstaller build.spec
# Output lands in dist/msm-breeding-planner (or .exe on Windows).
#
# Before building you must have a frontend/dist/ directory.  If you haven't
# built the frontend yet:
#     cd frontend && npm install && npm run build

block_cipher = None

a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('game_data.json', '.'),
        ('frontend/dist', 'frontend/dist'),
    ],
    hiddenimports=[],
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
    name='msm-breeding-planner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,           # keep a console so users see the server URL / Ctrl-C works
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
