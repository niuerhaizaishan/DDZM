"""Validate shipped room layers without depending on archived art projects."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from workstation_layout_tools import validate_registry_assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Optional directory for layout-validation.json')
    args = parser.parse_args()
    reports = validate_registry_assets()
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'layout-validation.json').write_text(json.dumps(reports, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'environments': len(reports), 'problems': sum(len(r['problems']) for r in reports)}))


if __name__ == '__main__':
    main()
