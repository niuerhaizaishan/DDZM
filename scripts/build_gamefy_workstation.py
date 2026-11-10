import argparse
import ast
import html
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "gamefy-workstation"
PUBLISH = PROJECT / "publish"
STATIC = ROOT / "src" / "dzmm_bot" / "admin" / "static"
sys.path.insert(0, str(ROOT / "src"))
from dzmm_bot.core.workstation_art import ART_FILENAMES, preview_art_manifest
from dzmm_bot.core.reply_templates import template_definition


def command_help():
    # Read the canonical group help tuple so the popup cannot drift from it.
    tree = ast.parse((ROOT / 'src/dzmm_bot/core/commands.py').read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'guides' for t in node.targets):
            for key, value in zip(node.value.keys, node.value.values):
                if isinstance(key, ast.Constant) and key.value == '装备商城':
                    heading, entries = ast.literal_eval(value)
                    guide = html.escape(template_definition('/帮助', 'shown').default.replace('{指令列表}', '\n'.join([heading, *(line for _, line in entries)])))
                    return guide
    raise ValueError('Missing canonical workstation guide')


def validate_settings(api_base_url, card_id, *, release=False):
    if not isinstance(api_base_url, str):
        raise ValueError('apiBaseUrl must be a string')
    if api_base_url:
        endpoint = urlsplit(api_base_url)
        if (endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username or endpoint.password
                or endpoint.query or endpoint.fragment or any(c.isspace() for c in api_base_url)):
            raise ValueError('apiBaseUrl must be an HTTPS URL without credentials, query or fragment')
        endpoint.port  # Reject invalid ports before creating any output.
    if card_id is not None and (type(card_id) is not int or card_id <= 0):
        raise ValueError('cardId must be a positive integer')
    if release and (not api_base_url or card_id is None):
        raise ValueError('Release requires --api-base-url and --card-id, environment settings, or config.local.json')


def build(destination, *, release=False, api_base_url='', card_id=None):
    """Build an isolated project; never rewrite the source checkout or private settings."""
    validate_settings(api_base_url, card_id, release=release)
    destination = Path(destination).resolve()
    if destination.is_relative_to(PROJECT.resolve()) or destination.is_relative_to((ROOT / 'src').resolve()):
        raise ValueError('Build destination must be outside the source project')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Build destination must be empty')
    publish = destination / 'publish'
    publish.mkdir(parents=True)
    (destination / 'functions').mkdir()
    for name in ('game.js', 'game.css', 'index.html'):
        shutil.copyfile(PUBLISH / name, publish / name)
    document = (publish / 'index.html').read_text(encoding='utf-8')
    document, count = re.subn(r'<pre id="help-text">.*?</pre>', lambda _: '<pre id="help-text">' + command_help() + '</pre>', document, flags=re.S)
    if count != 1:
        raise ValueError('Missing command help popup')
    (publish / 'index.html').write_text(document, encoding='utf-8')
    (publish / 'config.js').write_text('"use strict";\nwindow.workstationConfig = Object.freeze({\n  apiBaseUrl: '
        + json.dumps(api_base_url.rstrip('/')) + ',\n});\n', encoding='utf-8')
    (destination / 'dzmm.json').write_text(json.dumps({'cardId': card_id, 'publishDir': 'publish', 'functionsDir': 'functions'}, indent=2) + '\n', encoding='utf-8')
    # Connected clients use the server-composed image; the offline demo uses
    # only the legacy growth manifest. Independent accessory layers stay server-side.
    required = set() if release else {"core-base.png", *(path.name for path in (STATIC / "workstation").glob("*-layer.png")), *ART_FILENAMES}
    if any(not (STATIC / "workstation" / name).is_file() for name in required):
        raise ValueError("Workstation artwork is incomplete; run scripts/import_workstation_art.py first")
    assets = publish / 'assets'
    if required:
        assets.mkdir()
    for name in sorted(required):
        asset = STATIC / "workstation" / name
        shutil.copyfile(asset, assets / asset.name)
    (publish / "art.js").write_text("window.workstationArt = Object.freeze(" + json.dumps(preview_art_manifest(), ensure_ascii=False) + ");\n", encoding="utf-8")
    shutil.copyfile(STATIC / "workstation.css", publish / "style.css")
    shutil.copyfile(STATIC / "workstation.js", publish / "workstation.js")
    return destination


def check(project=PROJECT, *, release=False):
    # Every delivery uses the same authored raster rules as the backend.
    from workstation_layout_tools import validate_registry_assets
    validate_registry_assets(STATIC / "workstation")
    project = Path(project)
    publish = project / 'publish'
    config = json.loads((project / "dzmm.json").read_text(encoding="utf-8"))
    if (release or config.get('cardId') is not None) and (type(config.get("cardId")) is not int or config["cardId"] <= 0):
        raise ValueError("dzmm.json cardId must be a positive integer")
    if config.get("publishDir") != "publish" or config.get("functionsDir") != "functions":
        raise ValueError("Unexpected project directories")
    if not (publish / "index.html").is_file():
        raise ValueError("publish/index.html is required")
    files = sorted(path for path in publish.rglob("*") if path.is_file())
    allowed = {
        "index.html", "config.js", "game.js", "game.css", "style.css", "workstation.js", "art.js",
        *(f"assets/{path.name}" for path in (STATIC / "workstation").glob("*.png")),
    }
    # The publishing API enforces 64 MiB, despite the larger workspace/import limit.
    # Connected releases load full-resolution artwork from the deployed backend.
    limit = (64 if release else 100) * 1024 * 1024
    if len(files) > 3000 or sum(path.stat().st_size for path in files) > limit:
        raise ValueError("Project exceeds platform file count or size limit")
    for path in files:
        relative = path.relative_to(project)
        if path.relative_to(publish).as_posix() not in allowed:
            raise ValueError(f"Unexpected file in publish directory: {relative}")
        if path.is_symlink() or not all(re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in relative.parts):
            raise ValueError(f"Invalid published path: {relative}")
        if path.stat().st_size > 25 * 1024 * 1024:
            raise ValueError(f"File exceeds 25 MiB: {relative}")
        if path.suffix in {".html", ".js", ".css", ".json"}:
            content = path.read_text(encoding="utf-8")
            if re.search(r"sk-[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9_-]{20,}|-----BEGIN.*PRIVATE KEY", content):
                raise ValueError(f"Possible credential in {relative}")
            if re.search(r"(?:localStorage|sessionStorage|document\.cookie)", content):
                raise ValueError(f"Sandbox-incompatible storage in {relative}")
            for resource in re.findall(r'(?:src|href)="([^"]+)"', content):
                if not resource.startswith("./") or not (path.parent / resource).is_file():
                    raise ValueError(f"Missing or non-relative resource in {relative}: {resource}")
    api_config = (publish / "config.js").read_text(encoding="utf-8")
    match = re.search(r'apiBaseUrl:\s*"([^"\s]*)"', api_config)
    if match is None:
        raise ValueError("config.js must contain a literal apiBaseUrl string")
    validate_settings(match[1], config.get('cardId'), release=release)
    return files


def build_settings(*, release, api_base_url=None, card_id=None, config_path=None):
    local = {}
    if release:
        config_path = Path(config_path or ROOT / 'config.local.json')
        if config_path.exists():
            local = json.loads(config_path.read_text(encoding='utf-8-sig')).get('workstation', {})
    api = api_base_url if api_base_url is not None else (os.environ.get('DZMM_WORKSTATION_API_BASE_URL', local.get('apiBaseUrl', '')) if release else '')
    card = card_id if card_id is not None else (os.environ.get('DZMM_GAMEFY_CARD_ID', local.get('cardId')) if release else None)
    if isinstance(card, str):
        if not card.isascii() or not card.isdecimal():
            raise ValueError('DZMM_GAMEFY_CARD_ID must be a positive integer')
        card = int(card)
    validate_settings(api, card, release=release)
    return api, card


def main():
    parser = argparse.ArgumentParser(description="Build and validate the Gamefy workstation project")
    parser.add_argument("--release", action="store_true", help="Require a configured HTTPS data backend")
    parser.add_argument('--api-base-url', help='Public HTTPS backend origin; this is not a secret')
    parser.add_argument('--card-id', type=int, help='Numeric platform upload target (distinct from JWT audience)')
    parser.add_argument('--config', type=Path, help='Ignored local JSON configuration; used only for release builds')
    parser.add_argument('--output', type=Path, help='Destination ZIP; defaults to output/gamefy-workstation-{release,preview}.zip')
    args = parser.parse_args()
    try:
        api, card = build_settings(release=args.release, api_base_url=args.api_base_url, card_id=args.card_id, config_path=args.config)
    except (ValueError, TypeError) as error:
        parser.error(str(error))
    staging = ROOT / 'output' / 'workstation-build'
    staging.mkdir(parents=True, exist_ok=True)
    project = build(Path(tempfile.mkdtemp(prefix='project-', dir=staging)), release=args.release, api_base_url=api, card_id=card)
    files = check(project, release=args.release)
    output = args.output or ROOT / "output" / ("gamefy-workstation-release.zip" if args.release else "gamefy-workstation-preview.zip")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.write(project / "dzmm.json", "dzmm.json")
        for path in files:
            archive.write(path, path.relative_to(project).as_posix())
    print(f"Validated {len(files)} static files, {sum(path.stat().st_size for path in files):,} bytes")
    print(f"Package: {output}")
    print("Mode: " + ("connected release candidate" if args.release else "preview; verify backend before release"))


if __name__ == "__main__":
    main()
