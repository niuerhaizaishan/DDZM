"""List exactly the shipped renderer assets; never delete or move files."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from dzmm_bot.core.workstation_art import ART_FILENAMES
from dzmm_bot.core.workstation_stage5 import ACCESSORY_FILENAMES
from dzmm_bot.core.workstation import WORKSTATION_LAYERS


def required_assets():
    return set(ART_FILENAMES) | set(ACCESSORY_FILENAMES) | {'core-base.png'} | {f'{key}-layer.png' for key in WORKSTATION_LAYERS}


def audit(directory):
    directory = Path(directory)
    required = required_assets()
    actual = {p.name for p in directory.glob('*.png')}
    files = [{'name': name, 'bytes': (directory / name).stat().st_size,
              'sha256': hashlib.sha256((directory / name).read_bytes()).hexdigest()}
             for name in sorted(required & actual)]
    return {'required_count': len(required), 'bytes': sum(f['bytes'] for f in files),
            'missing': sorted(required - actual), 'unreferenced': sorted(actual - required), 'files': files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, default=ROOT / 'src/dzmm_bot/admin/static/workstation')
    parser.add_argument('--manifest', type=Path, help='Write the complete content-hash inventory')
    parser.add_argument('--check', action='store_true', help='Fail on missing or unreferenced PNGs')
    args = parser.parse_args()
    report = audit(args.assets)
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'files'}))
    if args.check and (report['missing'] or report['unreferenced']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
