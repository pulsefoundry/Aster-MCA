# CAD tooling and dependencies

These original scripts accompany the editable design. The final routed PCB files in `../hardware/` are the layout authority. Design JSON contains the placement/net contract and selected manual critical tracks; rebuilding JSON alone does not recover every final routed track, copper pour, or assembly mark.

## Runtime

- Python 3 with KiCad's `pcbnew` and `wx` modules for `build.py`, `audit_copper.py`, `preview.py`, and `cam_expected.py`.
- `audit.py` and `native_base.py` use the Python standard library.
- KiCad CLI is required for native KiCad DRC, Gerber and Excellon export. The delivered scripts were used with the installed macOS KiCad runtime and standard footprint libraries.
- `cam_audit.py` needs Python `gerbonara`; PNG rendering can use `rsvg-convert`. The previews are geometry reviews, not electrical simulations.
- A licensed/local EasyEDA Pro installation is needed to open the final `.epro2`, perform schematic-to-PCB synchronization and run its own DRC. This package does not automate or replace those editor checks.

On the author's Mac, KiCad Python is at `/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3`. `build.py` currently points to the standard footprint folder inside that application bundle; update `LIB` for another installation. Custom project footprints are supplied beside each PCB and use `${KIPRJMOD}` in `fp-lib-table`.

## Safely regenerating an engineering draft

Work in a separate scratch directory. Do not overwrite the delivered `hardware/` or `native/` copies while experimenting.

```sh
python3 tooling/build.py design/core/design.json --out scratch/core --template native/core/Aster-MCA-Nano-AT32-Core-v0.4-NOT_FOR_FAB-native.epro2
python3 tooling/audit.py scratch/core
python3 tooling/audit_copper.py scratch/core
python3 tooling/preview.py scratch/core
```

Use KiCad's Python executable in place of `python3` where needed. Pass `--template` explicitly: the original builder default references an older checkout path that is intentionally not bundled. A final native archive supplied in this package contains the base records needed by the exporter.

`--existing` preserves an existing PCB in the output folder while regenerating the native/geometry outputs. Without it, the builder starts from the input placement and explicit tracks. `--ses` imports a routing session for that exact placement only; historical sessions are intentionally not shipped. `audit.py` expects the generated EPRO filename without the `-native` export suffix, plus `design-manifest.json` and `component-geometry.json`, all in the same output folder.

The CAM helper scripts retain their original `core-output/` and `carrier-output/` paths relative to the script. If reusing them elsewhere, adapt these working paths or use a scratch folder with that structure. Re-export and recheck CAM after any PCB change.

## Package assembly

`package_delivery.py` is the whitelist copier used for this release. Run it from the original source checkout, or supply `--source /path/to/work/peak-hold-v0.4`. It writes only under that checkout's `outputs/`; it does not publish, modify the canonical repository, operate the EDA UI or delete unrelated files. `--strict` reports incomplete final inputs or unresolved local links as a failure. Re-running updates named files; unexpected pre-existing files are listed rather than removed.

`PACKAGE-MANIFEST.json` records every copied source, size and SHA-256. `PACKAGE-CHECK.json` records missing inputs, local-link checks, image dimensions and archive checks. The output is not a claim of manufacturability or analog performance. See the release status and review documents for those separate boundaries.

The CAM `source-hashes.json` retains hashes of both the routed KiCad PCB and the generated pre-editor EPRO used during export. That intermediate EPRO is intentionally not distributed: `native/` contains only the later editor-exported final archives. Use the release evidence for their synchronization relationship; do not expect the two archive hashes to be equal.
