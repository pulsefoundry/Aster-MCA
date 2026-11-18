#!/usr/bin/env python3
"""Copy the reviewed v0.4 delivery whitelist; never modify the canonical repo.

Run from the project checkout. Re-running replaces only named delivery files.
No directory deletion, symlink following, recursive model copy, or native-editor
operation is performed. Missing final native exports are reported, never replaced
with older exports. --strict fails when required inputs or local links are absent.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import sys
from urllib.parse import unquote
import xml.etree.ElementTree as ET
import zipfile

NAME = 'Aster-MCA-Nano-v0.4-20261112'
STEMS = {
    'core': 'Aster-MCA-Nano-AT32-Core-v0.4-NOT_FOR_FAB',
    'carrier': 'Aster-MCA-Nano-AT32-Peak-Carrier-v0.4-NOT_FOR_FAB',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, default=Path(__file__).resolve().parent,
                    help='Original work/peak-hold-v0.4 directory')
    ap.add_argument('--destination', type=Path,
                    help='Optional directory within this checkout outputs/')
    ap.add_argument('--strict', action='store_true')
    args = ap.parse_args()
    source = args.source.resolve()
    if source.name != 'peak-hold-v0.4' or not (source/'core/design.json').is_file():
        ap.error('--source must name the original work/peak-hold-v0.4 directory')
    checkout = source.parent.parent
    outputs = checkout/'outputs'
    dest = (args.destination or outputs/NAME).absolute()
    if not dest.resolve().is_relative_to(outputs.resolve()) or dest.resolve() == outputs.resolve():
        ap.error('Destination must be a child of this checkout outputs/ directory')
    for path in [dest, *dest.parents]:
        if path.is_symlink():
            ap.error('Symlink destination paths are not allowed')
    dest.mkdir(parents=True, exist_ok=True)
    mappings, missing, manifest = {}, [], []

    def add(src, target, required=True):
        src = Path(src)
        target = Path(target)
        assert not target.is_absolute() and '..' not in target.parts
        if target.as_posix() in mappings:
            raise ValueError('Duplicate destination: '+target.as_posix())
        if not src.is_file():
            if required:
                missing.append(str(src.relative_to(checkout)))
            return
        if src.is_symlink():
            raise ValueError('Source symlink is not permitted: '+str(src))
        mappings[target.as_posix()] = src

    for name in ['README.md', 'README.en.md']:
        add(source/'delivery'/name, name)
    add(checkout/'work/aster-mca-integration-20261021/nano/LICENSE', 'LICENSE')

    for name in ['ASSEMBLY.md', 'architecture.svg', 'electrical-review.md',
                 'independent-review.md', 'RELEASE-STATUS.md']:
        add(source/'docs'/name, 'docs/'+name)
    for name in ['PROTOTYPE-MANUFACTURING-NOTES.md', 'PROTOTYPE-VISUAL-REVIEW.md']:
        add(source/'cad'/name, 'docs/'+name)

    for name in ['design.json', 'module-spec.json', 'interface.csv', 'design-notes.md']:
        add(source/'core'/name, 'design/core/'+name)
    for name in ['design.json', 'assembly-mechanical.md', 'merge-and-routing-notes.md']:
        add(source/'carrier'/name, 'design/carrier/'+name)
    for name in ['analog-design.json', 'analog-bom.csv', 'ANALOG-DESIGN-NOTES.txt']:
        add(source/'analog'/name, 'design/analog/'+name)

    for board, stem in STEMS.items():
        folder = source/'cad'/f'{board}-output'
        hardware = Path('hardware')/board
        for ext in ['.kicad_pcb', '.kicad_pro']:
            add(folder/(stem+ext), hardware/(stem+ext))
        add(folder/(stem+'.kicad_dru'), hardware/(stem+'.kicad_dru'), required=False)
        add(folder/'fp-lib-table', hardware/'fp-lib-table')
        footprints = {
            'core': ['Aster_Castellated_22_26x20.kicad_mod'],
            'carrier': ['Aster_AT32_Core_22_26x20_Carrier.kicad_mod', 'Aster_GSG_Wire_3P.kicad_mod'],
        }
        for name in footprints[board]:
            add(folder/'AsterCustom.pretty'/name, hardware/'AsterCustom.pretty'/name)
        for name in ['pcb-top.svg', 'pcb-bottom.svg', 'pcb-top.png', 'pcb-bottom.png',
                     'design-manifest.json', 'component-geometry.json']:
            add(folder/name, hardware/name)
        add(folder/'BOM.csv', Path('design')/board/'BOM.csv')
        for name in ['structural-audit.json', 'copper-audit.json', 'silk-drc.json',
                     'silk-only-change-audit.json', 'added-assembly-silk.json',
                     'expected-pin-nets.json', 'native-mapping.json']:
            add(folder/name, Path('evidence')/board/name)
        if board == 'carrier':
            for name in ['dnp-audit.json', 'critical-route-summary.json']:
                add(folder/name, Path('evidence')/board/name)
        cam = folder/'prototype-fabrication'
        suffixes = [
            '-F_Cu.gtl', '-B_Cu.gbl', '-F_Mask.gts', '-B_Mask.gbs',
            '-F_Silkscreen.gto', '-B_Silkscreen.gbo', '-Edge_Cuts.gm1',
            '-PTH.drl', '-NPTH.drl', '-PTH-drl_map.svg', '-NPTH-drl_map.svg',
            '-job.gbrjob', '-Gerber.zip',
        ]
        fixed = [
            'CAM-FILE-SHA256.json', 'CAM-top.svg', 'CAM-top.png', 'CAM-bottom.svg',
            'CAM-bottom.png', 'assembly-placement.svg', 'assembly-placement.png',
            'README-NOT_FOR_FAB.md', 'cam-readback-audit.json', 'drill-report.txt',
            'expected-cam.json', 'export-log.json', 'source-hashes.json',
        ]
        for name in [stem+s for s in suffixes]+fixed:
            add(cam/name, hardware/'prototype-fabrication'/name)

        # Only native editor final exports, never cad/*.epro2 or native-evidence/core/.
        native = source/'native-evidence'/f'{board}-final'
        for name in [stem+'-native.epro2', stem+'-Schematic.pdf',
                     'PCB-netlist.net', 'Schematic-netlist.net']:
            add(native/name, Path('native')/board/name)
        for name in [stem+'-Gerber-PROTOTYPE.zip', 'schematic-preview.png',
                     'schematic-preview-1.png', 'schematic-preview-2.png',
                     'schematic-preview-3.png']:
            add(native/name, Path('native')/board/name, required=False)
        # Explicit final report names. Raw export transport JSON contains large
        # embedded documents and is intentionally not copied.
        for name in ['native-check-summary.json', 'native-drc.json', 'sync-report.csv',
                     'native-export-audit.json', 'native-final-audit.json']:
            add(native/name, Path('evidence')/board/name, required=False)
        for name in [f'{board}-final-check.json', f'{board}-final-sync.csv',
                     f'{board}-native-final-summary.json']:
            add(source/'native-evidence'/name, Path('evidence')/board/name, required=False)

    for name in ['simulation-summary.json', 'simulated-peak-hold.png',
                 'validate_positive.json', 'validate_frontend.json', 'tolerance_check.json',
                 'positive-candidate.cir', 'representative.cir', 'tolerance.cir']:
        add(source/'analog'/name, 'simulation/'+name)
    for name in ['README.md', 'MODEL-SOURCES.md']:
        add(source/'delivery'/('simulation-'+name), 'simulation/'+name)
    for name in ['build.py', 'native_base.py', 'audit.py', 'audit_copper.py', 'preview.py',
                 'cam_expected.py', 'cam_audit.py', 'protect_routes.py']:
        add(source/'cad'/name, 'tooling/'+name)
    add(source/'delivery/tooling-README.md', 'tooling/README.md')
    add(Path(__file__).resolve(), 'tooling/package_delivery.py')

    for target, src in sorted(mappings.items()):
        dst = dest/target
        if dst.is_symlink() or any(p.is_symlink() for p in dst.parents if p != dest.parent):
            raise ValueError('Refusing to overwrite through a symlink: '+str(dst))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        digest = sha(src)
        assert sha(dst) == digest
        manifest.append({'path':target, 'source':str(src.relative_to(checkout)),
                         'bytes':src.stat().st_size, 'sha256':digest})

    # Validate every copied image/container and local Markdown link.
    checks, broken_links = [], []
    for item in manifest:
        p = dest/item['path']
        suffix = p.suffix.lower()
        if suffix == '.svg':
            ET.parse(p); checks.append({'path':item['path'], 'check':'SVG XML parsed'})
        elif suffix == '.png':
            b = p.read_bytes()
            assert b[:8] == b'\x89PNG\r\n\x1a\n'
            w,h = struct.unpack('>II', b[16:24]); assert w and h
            checks.append({'path':item['path'], 'check':'PNG signature/dimensions', 'pixels':[w,h]})
        elif suffix in {'.zip','.epro2'}:
            with zipfile.ZipFile(p) as archive:
                assert archive.testzip() is None
            checks.append({'path':item['path'], 'check':'ZIP CRC passed'})
        elif suffix == '.pdf':
            assert p.read_bytes().startswith(b'%PDF-')
            checks.append({'path':item['path'], 'check':'PDF signature'})
        elif suffix == '.md':
            for link in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', p.read_text()):
                link = link.strip('<>').split('#')[0]
                if not link or re.match(r'^[a-z]+:', link):
                    continue
                if not (p.parent/unquote(link)).exists():
                    broken_links.append({'path':item['path'], 'link':link})

    # Existing non-whitelist files are reported; they are never silently removed.
    generated = {'PACKAGE-MANIFEST.json','PACKAGE-CHECK.json'}
    unexpected = sorted(str(p.relative_to(dest)) for p in dest.rglob('*')
                        if p.is_file() and str(p.relative_to(dest)) not in mappings
                        and str(p.relative_to(dest)) not in generated)
    result = {
        'status':'COMPLETE_COPY' if not missing and not broken_links and not unexpected else 'PARTIAL_COPY',
        'note':'Copy completeness is not fabrication approval or bench validation.',
        'generated_utc':datetime.now(timezone.utc).isoformat(),
        'copied_files':len(manifest), 'copied_bytes':sum(m['bytes'] for m in manifest),
        'missing_required_sources':missing, 'broken_local_markdown_links':broken_links,
        'unexpected_existing_files_not_deleted':unexpected, 'container_and_image_checks':checks,
        'exclusions':['old native exports','placement-only CAD checkpoints','old DRC reports',
                      'vendor models/LIB/ZIP/PDF','historical analog sweeps','firmware binaries'],
    }
    (dest/'PACKAGE-MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    (dest/'PACKAGE-CHECK.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'container_and_image_checks'},ensure_ascii=False,indent=2))
    if args.strict and (missing or broken_links or unexpected):
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
