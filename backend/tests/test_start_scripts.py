"""DEMO_MODE as the start scripts read it: scripts/setup.sh and the API image's start command seed exactly when the app
is in demo mode, as app.config reads the variable (unset counts as true, the comparison ignores case, any other value,
an empty one included, is false). Both run here with stand-ins for every tool they call, so nothing is installed,
started, migrated or seeded."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# DEMO_MODE (None: unset) and whether the seed runs.
CASES = [(None, True), ('true', True), ('TRUE', True), ('True', True),
         ('', False), ('false', False), ('False', False), ('1', False), ('yes', False)]
# Every stand-in logs its call; the Python one also says when it was asked for the seed.
LOG = 'echo "$(basename "$0") $*" >> "$TOOL_LOG"'
SEED = LOG + '\nif [ "$1 $2" = "-m app.seed" ]; then echo SEEDED; fi'

pytestmark = pytest.mark.skipif(shutil.which('bash') is None or shutil.which('sh') is None,
                                reason='the scripts need bash and sh')


def stand_in(directory: Path, name: str, body: str = LOG):
    directory.mkdir(parents=True, exist_ok=True)
    tool = directory / name
    tool.write_text(f'#!/bin/sh\n{body}\n')
    tool.chmod(0o755)


def environment(mode, tools: Path, log: Path) -> dict:
    """The test's environment with DEMO_MODE as given and the stand-ins first on PATH."""
    env = {key: value for key, value in os.environ.items() if key != 'DEMO_MODE'}
    env.update(PATH=f'{tools}{os.pathsep}{env["PATH"]}', TOOL_LOG=str(log))
    if mode is not None:
        env['DEMO_MODE'] = mode
    return env


@pytest.mark.parametrize(('mode', 'seeded'), CASES)
def test_the_cases_are_how_the_app_reads_demo_mode(mode, seeded):
    env = {key: value for key, value in os.environ.items() if key != 'DEMO_MODE'}
    env['PYTHONPATH'] = str(ROOT / 'backend')
    if mode is not None:
        env['DEMO_MODE'] = mode
    result = subprocess.run([sys.executable, '-c', 'from app.config import settings; print(settings.demo_mode)'],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.stdout.strip() == str(seeded), result.stderr


@pytest.mark.parametrize(('mode', 'seeded'), CASES)
def test_setup_seeds_exactly_in_demo_mode(tmp_path, mode, seeded):
    # A copy of the script in a scratch checkout, whose venv tools are stand-ins like python3.12, npm and docker.
    (tmp_path / 'scripts').mkdir()
    shutil.copy(ROOT / 'scripts' / 'setup.sh', tmp_path / 'scripts' / 'setup.sh')
    venv = tmp_path / 'backend' / '.venv' / 'bin'
    for name in ('pip', 'alembic'):
        stand_in(venv, name)
    stand_in(venv, 'python', SEED)
    tools, log = tmp_path / 'tools', tmp_path / 'calls.log'
    for name in ('python3.12', 'npm', 'docker'):
        stand_in(tools, name)
    result = subprocess.run(['bash', str(tmp_path / 'scripts' / 'setup.sh')], env=environment(mode, tools, log),
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'docker compose up -d --wait db' in log.read_text()  # the stand-ins ran, not the real tools
    assert ('SEEDED' in result.stdout) is seeded


def api_start_script() -> str:
    """The `sh -c` script of the API image's CMD."""
    line = next(line for line in (ROOT / 'backend' / 'Dockerfile').read_text().splitlines()
                if line.startswith('CMD '))
    shell, flag, script = json.loads(line.removeprefix('CMD '))
    assert (shell, flag) == ('sh', '-c')
    return script


@pytest.mark.parametrize(('mode', 'seeded'), CASES)
def test_the_api_image_seeds_exactly_in_demo_mode(tmp_path, mode, seeded):
    tools, log = tmp_path / 'tools', tmp_path / 'calls.log'
    for name in ('alembic', 'uvicorn'):
        stand_in(tools, name)
    stand_in(tools, 'python', SEED)
    result = subprocess.run(['sh', '-c', api_start_script()], env=environment(mode, tools, log), cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'uvicorn app.main:app' in log.read_text()  # the whole command ran, on the stand-ins
    assert ('SEEDED' in result.stdout) is seeded
