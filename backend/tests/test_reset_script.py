"""The guards of scripts/reset-demo.sh, run with --dry-run so that no database is touched.

The script refuses unless DEMO_MODE is true (compared as app.config does: case-insensitive, unset counts as true),
refuses a DATABASE_URL whose host is not localhost, 127.0.0.1 or db unless --force-remote, and needs an explicit
confirmation (a typed "yes", or --yes). A dry run makes every check and prints the steps instead of running them."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts' / 'reset-demo.sh'
# Local hosts on port 1, where nothing listens: should a dry run ever go on to the steps, they fail to connect
# instead of touching a real database.
LOCAL = 'postgresql+psycopg://reset_test:reset_test@localhost:1/reset_test'
STEPS = ('downgrade base', 'upgrade head', 'python -m app.seed')

pytestmark = pytest.mark.skipif(shutil.which('bash') is None, reason='the script needs bash')


def run(*args, stdin='', **env):
    """The script with the given environment; DEMO_MODE and DATABASE_URL are inherited only when passed."""
    environment = {key: value for key, value in os.environ.items() if key not in ('DEMO_MODE', 'DATABASE_URL')}
    environment.update(env)
    return subprocess.run(['bash', str(SCRIPT), *args], input=stdin, capture_output=True, text=True,
                          env=environment, cwd=ROOT, timeout=30)


def planned(result) -> bool:
    return result.returncode == 0 and all(step in result.stdout for step in STEPS)


@pytest.mark.parametrize('mode', ['false', 'False', '0', 'yes', ''])
def test_refuses_unless_demo_mode_is_true(mode):
    result = run('--yes', '--dry-run', DEMO_MODE=mode, DATABASE_URL=LOCAL)
    assert result.returncode == 1
    assert 'DEMO_MODE' in result.stderr and 'Refusing' in result.stderr
    assert 'would run' not in result.stdout


@pytest.mark.parametrize('mode', ['true', 'TRUE', 'True'])
def test_demo_mode_true_in_any_case_is_accepted(mode):
    assert planned(run('--yes', '--dry-run', DEMO_MODE=mode, DATABASE_URL=LOCAL))


@pytest.mark.skipif((ROOT / '.env').exists(), reason='a local .env may set DEMO_MODE or DATABASE_URL')
def test_unset_demo_mode_and_url_follow_the_app_defaults():
    # Stopped at the question (answered «no»), so the app's default database is only named, never reached.
    result = run('--dry-run', stdin='no\n')
    assert 'Refusing' not in result.stderr
    assert 'postgresql+psycopg://credit_route:***@localhost:5432/credit_route' in result.stderr
    assert result.returncode == 1 and 'Cancelled' in result.stderr


@pytest.mark.parametrize('host', ['localhost', '127.0.0.1', 'db'])
def test_local_hosts_are_accepted(host):
    assert planned(run('--yes', '--dry-run', DEMO_MODE='true',
                       DATABASE_URL=f'postgresql+psycopg://reset_test:secret@{host}:1/reset_test'))


@pytest.mark.parametrize('url', [
    'postgresql+psycopg://credit_route:secret@db.example.com:5432/credit_route',
    'postgresql+psycopg://credit_route:secret@10.0.0.7/credit_route',
    'postgresql://user@localhost.example.org/credit_route',
    'postgresql+psycopg://credit_route:secret@[2001:db8::1]:5432/credit_route',
])
def test_a_remote_host_is_refused_unless_forced(url):
    refused = run('--yes', '--dry-run', DEMO_MODE='true', DATABASE_URL=url)
    assert refused.returncode == 1
    assert 'not local' in refused.stderr and '--force-remote' in refused.stderr
    assert 'would run' not in refused.stdout
    forced = run('--yes', '--dry-run', '--force-remote', DEMO_MODE='true', DATABASE_URL=url)
    assert planned(forced)
    assert 'Warning' in forced.stderr


def test_without_yes_only_a_typed_yes_confirms():
    for answer in ('', 'no\n', 'y\n', 'YES\n', 'yes please\n'):
        result = run('--dry-run', stdin=answer, DEMO_MODE='true', DATABASE_URL=LOCAL)
        assert result.returncode == 1, answer
        assert 'Cancelled: nothing was changed.' in result.stderr
        assert 'would run' not in result.stdout
    assert planned(run('--dry-run', stdin='yes\n', DEMO_MODE='true', DATABASE_URL=LOCAL))


def test_the_question_names_the_database_without_its_password():
    result = run('--dry-run', stdin='no\n', DEMO_MODE='true',
                 DATABASE_URL='postgresql+psycopg://reset_test:s3cret-pass@localhost:1/reset_test')
    assert 'reset_test:***@localhost:1/reset_test' in result.stderr
    assert 's3cret-pass' not in result.stderr + result.stdout


def test_guards_run_before_the_question():
    # A refused mode or host never asks: the answer is not even read.
    assert 'Type yes' not in run('--dry-run', stdin='yes\n', DEMO_MODE='false', DATABASE_URL=LOCAL).stderr
    assert 'Type yes' not in run('--dry-run', stdin='yes\n', DEMO_MODE='true',
                                 DATABASE_URL='postgresql://u:p@remote.example/x').stderr


def test_an_unknown_option_is_refused():
    result = run('--force', DEMO_MODE='true', DATABASE_URL=LOCAL)
    assert result.returncode == 2 and 'Unknown option' in result.stderr


def test_the_script_and_its_output_carry_no_demo_wording():
    """The file name is a technical name; what the script prints is neutral (DEMO_MODE is the env variable)."""
    outputs = [run('--yes', '--dry-run', DEMO_MODE=mode, DATABASE_URL=LOCAL) for mode in ('true', 'false')]
    text = ''.join(result.stdout + result.stderr for result in outputs).replace('DEMO_MODE', '')
    assert 'demo' not in text.lower() and 'демо' not in text.lower()
