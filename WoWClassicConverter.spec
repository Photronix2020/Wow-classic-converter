# PyInstaller build recipe for the single-file Windows executable.
#   pyinstaller WoWClassicConverter.spec
# Output: dist/WoWClassicConverter.exe

a = Analysis(
    ["wowconv_app.py"],
    datas=[("wowconv/shim.lua", "wowconv")],
    excludes=["unittest", "pydoc", "test"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="WoWClassicConverter",
    console=False,
    upx=False,
)
