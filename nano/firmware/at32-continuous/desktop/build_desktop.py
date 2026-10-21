"""Build the Apple Silicon app with a bundled Python backend and native window."""
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
ROOT = SOURCE.parents[1]
BUILD = ROOT / 'work/at32-desktop-build'
APP = ROOT / 'outputs/Aster Nano.app'

def run(*args):
    subprocess.run([str(x) for x in args], check=True)

def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    (SOURCE/'build').mkdir(parents=True, exist_ok=True)
    run('cc','-O3','-Wall','-Wextra','-Werror','-dynamiclib', SOURCE/'host_codec.c',
        '-o', SOURCE/'build/libastercodec.dylib')
    sparse=SOURCE.parent/'at32-sparse'
    (sparse/'build').mkdir(parents=True, exist_ok=True)
    run('cc','-O3','-Wall','-Wextra','-Werror','-dynamiclib',sparse/'host_codec.c',
        '-o',sparse/'build/libastercodec.dylib')
    sparse_data=[]
    for name in ['__init__.py','capture.py','protocol.py','spectrum.py']:
        sparse_data+=['--add-data',f'{sparse}/{name}:sparse']
    burst=SOURCE.parent/'at32-burst'
    (burst/'build').mkdir(exist_ok=True)
    run('cc','-O3','-Wall','-Wextra','-Werror','-dynamiclib',burst/'host_dsp.c',
        '-o',burst/'build/libasterburst.dylib')
    burst_data=[]
    for name in ['__init__.py','capture.py','protocol.py','spectrum.py']:
        burst_data+=['--add-data',f'{burst}/{name}:burst']
    histogram=SOURCE.parent/'at32-histogram'
    histogram_data=[]
    for name in ['__init__.py','capture.py','protocol.py']:
        histogram_data+=['--add-data',f'{histogram}/{name}:histogram']
    run(sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir',
        '--name','aster-backend','--distpath',BUILD/'dist','--workpath',BUILD/'temp',
        '--specpath',BUILD,
        '--add-data',f'{SOURCE}/gui.html:.','--add-data',f'{SOURCE}/gui.js:.',
        '--add-data',f'{SOURCE}/gui.css:.','--add-binary',f'{SOURCE}/build/libastercodec.dylib:build',
        '--add-binary',f'{sparse}/build/libastercodec.dylib:sparse/build',*sparse_data,
        '--add-binary',f'{burst}/build/libasterburst.dylib:burst/build',*burst_data,*histogram_data,
        SOURCE/'gui.py')
    if APP.exists(): shutil.rmtree(APP)
    contents = APP/'Contents'; resources = contents/'Resources'; macos = contents/'MacOS'
    resources.mkdir(parents=True); macos.mkdir()
    shutil.copytree(BUILD/'dist/aster-backend',resources/'backend',symlinks=True)
    (resources/'workspace.json').write_text(json.dumps({'workspace':str(ROOT)}, ensure_ascii=False))
    plist = {
        'CFBundleName':'Aster Nano', 'CFBundleDisplayName':'Aster Nano',
        'CFBundleIdentifier':'org.pulsefoundry.aster-nano', 'CFBundleExecutable':'AsterNano',
        'CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.6.1','CFBundleVersion':'7',
        'LSMinimumSystemVersion':'15.0','NSHighResolutionCapable':True,
        'NSPrincipalClass':'NSApplication',
        'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True},
    }
    (contents/'Info.plist').write_bytes(plistlib.dumps(plist))
    run('xcrun','swiftc','-swift-version','5','-O','-framework','AppKit','-framework','WebKit',
        '-target','arm64-apple-macosx15.0',HERE/'AsterNano.swift','-o',macos/'AsterNano')
    run('codesign','--force','--deep','--sign','-',APP)
    run('codesign','--verify','--deep','--strict',APP)
    print(APP)

if __name__ == '__main__': main()
