#!/usr/bin/env python3
"""Deploy the pushed production revision only after its Bot CI run succeeds.

Default: read-only preflight. --deploy creates a Render deployment of that exact
commit. Requires gh login; Render credentials come from RENDER_API_KEY or --key-file.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import urllib.request

BRANCH = 'codex/crystal-v2'
REPOSITORY = 'utlik-pro/Alina'
SERVICE = 'srv-d7d1u0reo5us7381mqc0'
ROOT = Path(__file__).resolve().parents[2]


def command(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def checked_revision():
    if command('git', 'branch', '--show-current') != BRANCH:
        raise RuntimeError(f'Deploy from {BRANCH} only')
    if command('git', 'diff', 'HEAD', '--name-only'):
        raise RuntimeError('Tracked changes must be committed before deployment')
    revision = command('git', 'rev-parse', 'HEAD')
    remote = command('git', 'ls-remote', 'origin', f'refs/heads/{BRANCH}').split()
    if not remote or remote[0] != revision:
        raise RuntimeError('Local revision is not the pushed production branch head')
    runs = json.loads(command(
        'gh', 'run', 'list', '--repo', REPOSITORY, '--branch', BRANCH,
        '--commit', revision, '--workflow', 'bot-ci.yml', '--event', 'push',
        '--limit', '1', '--json', 'headSha,status,conclusion,url'))
    if not runs or runs[0]['headSha'] != revision or runs[0]['status'] != 'completed' or runs[0]['conclusion'] != 'success':
        raise RuntimeError('Bot CI must succeed for this exact revision, including Docker startup')
    return revision, runs[0]['url']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deploy', action='store_true')
    parser.add_argument('--key-file', type=Path)
    args = parser.parse_args()
    revision, run_url = checked_revision()
    print(json.dumps({'revision': revision, 'ci': run_url, 'preflight': 'passed'}), flush=True)
    if not args.deploy:
        return
    token = args.key_file.read_text().strip() if args.key_file else os.environ.get('RENDER_API_KEY')
    if not token:
        raise RuntimeError('Set RENDER_API_KEY or provide --key-file')
    req = urllib.request.Request(
        f'https://api.render.com/v1/services/{SERVICE}/deploys',
        data=json.dumps({'commitId': revision, 'clearCache': 'do_not_clear'}).encode(),
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        deployment = json.load(response)
    print(json.dumps({'deploy_id': deployment['id'], 'status': deployment['status'],
                      'revision': revision}), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(f'Deployment stopped: {exc}') from None
