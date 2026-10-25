"""Private document storage on the local filesystem, settled together with the database transaction.

Layout: `<root>/<key>` for stored bytes and `<root>/.staging/<random>.part` while an upload is received. The root is
configurable (settings.document_storage_dir) and outside every served path; keys are random hex, never derived from an
upload name. An upload is written into a staging file (mode 0600), validated, and moved into place by an atomic rename
only after its Document row was flushed; if the request transaction then ends without a commit (error, rollback or
close), the moved file is removed again. A deletion removes the bytes only after the commit. A staging file never
outlives its request.
"""
from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import secrets
from sqlalchemy import event
from sqlalchemy.orm import Session
from ..config import settings

KEY = re.compile(r'[0-9a-f]{32}')
STAGING = '.staging'
PLAN = 'document_files'  # Session.info key of the transaction's pending file operations


class StagedFile:
    """An upload being received: counted and hashed (SHA-256 of the actual bytes) as it is written."""

    def __init__(self, path: Path):
        self.path = path
        self.size = 0
        self._digest = hashlib.sha256()
        self._handle = os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb')

    def write(self, data: bytes) -> None:
        self._handle.write(data)
        self._digest.update(data)
        self.size += len(data)

    def finish(self) -> None:
        self._handle.close()

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()

    def read_bytes(self) -> bytes:
        self.finish()
        return self.path.read_bytes()

    def discard(self) -> None:
        self.finish()
        self.path.unlink(missing_ok=True)


class FilePlan:
    """Files a transaction created (removed unless it commits) and files it deleted (removed once it commits)."""

    def __init__(self):
        self.created: list[Path] = []
        self.deleted: list[Path] = []
        self.committed = False


def plan(db: Session) -> FilePlan:
    return db.info.setdefault(PLAN, FilePlan())


@event.listens_for(Session, 'after_commit')
def _committed(session: Session) -> None:
    pending = session.info.get(PLAN)
    if pending is not None:
        pending.committed = True


@event.listens_for(Session, 'after_transaction_end')
def _settle(session: Session, transaction) -> None:
    """Runs when the outermost transaction ends, after `after_commit` when it committed."""
    if transaction.parent is not None:
        return
    pending = session.info.pop(PLAN, None)
    if pending is None:
        return
    for path in pending.deleted if pending.committed else pending.created:
        path.unlink(missing_ok=True)


class DocumentStorage:
    def __init__(self, root: Path):
        self.root = Path(root)

    @staticmethod
    def new_key() -> str:
        return secrets.token_hex(16)

    def path(self, key: str) -> Path:
        if not KEY.fullmatch(key):
            raise ValueError('invalid storage key')
        return self.root / key

    @contextmanager
    def staged(self) -> Iterator[StagedFile]:
        """A new private staging file, removed when the block ends unless it was placed."""
        staging = self.root / STAGING
        staging.mkdir(mode=0o700, parents=True, exist_ok=True)
        staged = StagedFile(staging / f'{secrets.token_hex(16)}.part')
        try:
            yield staged
        finally:
            staged.discard()

    def place(self, db: Session, staged: StagedFile, key: str) -> None:
        """Moves a validated staging file into place; call after the Document row was flushed."""
        staged.finish()
        target = self.path(key)
        os.replace(staged.path, target)
        plan(db).created.append(target)

    def remove_after_commit(self, db: Session, key: str) -> None:
        plan(db).deleted.append(self.path(key))


def get_storage() -> DocumentStorage:
    """FastAPI dependency; tests override it with a temporary root."""
    return DocumentStorage(Path(settings.document_storage_dir))
