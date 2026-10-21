"""Verify the two historical SHA256 manifest formats without changing evidence."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifests = sorted((ROOT/'outputs').glob('**/artifact-sha256.json'))
    count = 0
    for manifest in manifests:
        base = manifest.parent.resolve()
        for name, description in json.loads(manifest.read_text()).items():
            target = (base/name).resolve()
            target.relative_to(base)
            expected = description['sha256'] if isinstance(description, dict) else description
            data = target.read_bytes()
            if isinstance(description, dict) and len(data) != description['bytes']:
                raise ValueError(f'Artifact length mismatch: {target}')
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f'Artifact SHA256 mismatch: {target}')
            count += 1
    print(f'Verified {count} files in {len(manifests)} archived manifests')


if __name__ == '__main__':
    main()
