"""Copy the desktop evaluation project into the website's public evals/ tree.

Explicit allowlist, no secrets/caches, no deletion, and no runtime-world changes.
Run only after a measurement finishes so its copied artifacts are consistent.
"""
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'website/evals'
FOLDERS = ['cartly', 'service', 'data', 'evaluation', 'prompts', 'runs', 'scenario_truth',
           'scenarios', 'scripts', 'simulation', 'tests']


def main():
    if not (ROOT/'website/.git').exists():
        raise SystemExit('Run this exporter from the desktop authoring project, not the exported copy.')
    files = [ROOT/'policy.md', ROOT/'README.md', ROOT/'.gitignore']
    files += [p for name in FOLDERS for p in (ROOT/name).rglob('*')
              if p.is_file() and '__pycache__' not in p.parts
              and p.name != '.DS_Store' and not p.name.startswith('.env')]
    secret_values = []
    if (ROOT/'.env').exists():
        for line in (ROOT/'.env').read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                if any(word in key.upper() for word in ['KEY', 'TOKEN', 'SECRET']):
                    value = value.strip().strip('"\'')
                    if len(value) > 12:
                        secret_values.append(value.encode())
    token = re.compile(rb'(?<![A-Za-z0-9_-])(?:sk-(?:proj-)?[A-Za-z0-9_-]{35,}|github_pat_[A-Za-z0-9_]{30,}|gh[pousr]_[A-Za-z0-9]{30,})')
    # Scan the entire proposed export before the first copy. Report paths only.
    bad = [str(p.relative_to(ROOT)) for p in files
           if token.search(p.read_bytes()) or any(s in p.read_bytes() for s in secret_values)]
    if bad:
        raise SystemExit('Potential credentials; export stopped: '+', '.join(bad))
    hashes = {}
    for source in files:
        relative = source.relative_to(ROOT)
        target = DEST/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != source.read_bytes():
            shutil.copyfile(source, target)
        hashes[str(relative)] = hashlib.sha256(target.read_bytes()).hexdigest()
    (DEST/'EXPORT_MANIFEST.json').write_text(json.dumps({
        'source': 'desktop Cartly evaluation project',
        'reference_date': json.loads((ROOT/'data/config.json').read_text())['today'],
        'source_paths_are_relative': True, 'credentials_included': False,
        'runtime_world_changed': False, 'files': hashes,
    }, indent=2)+'\n')
    print(f'Exported {len(hashes)} files into {DEST}; credential scan passed.')


if __name__ == '__main__':
    main()
