#!/usr/bin/env python3
"""Check relative Markdown file links offline. External URLs/anchors are not tested."""
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', 'node_modules', '.venv', 'venv', 'build', 'dist', 'test-results', '.lab-state'}

def check(root=ROOT):
    errors=[]
    for path in sorted(root.rglob('*.md')):
        if any(part in SKIP or part.startswith('.venv') for part in path.relative_to(root).parts):
            continue
        text=re.sub(r'^```.*?^```[^\n]*$', '', path.read_text(encoding='utf-8'), flags=re.M|re.S)
        for match in re.finditer(r'!?\[[^\]\n]*\]\(([^\s)]+)(?:\s+"[^"\n]*")?\)', text):
            target=match.group(1).strip('<>')
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',target) or target.startswith(('#','/')):
                continue
            target=unquote(target.split('#')[0].split('?')[0])
            if target and not (path.parent/target).exists():
                errors.append(f'{path.relative_to(root)}: missing {target}')
    for error in errors: print(error)
    if not errors: print('PASS: relative Markdown file links (external URLs and anchors not checked).')
    return bool(errors)

if __name__=='__main__': sys.exit(check())
