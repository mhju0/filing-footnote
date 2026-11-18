"""Save regulator responses as pinned files, in the layout ``app.build.verify`` reads.

``--save-pinned DIR`` on an ingest command writes the exact body the parser consumed, as
received, under ``DIR``:

- ``dart/fnlttSinglAcntAll/<corp_code>_<bsns_year>_<reprt_code>_<fs_div>.json``
- ``sec/companyfacts/CIK<cik10>.json``
- ``dart/structured/<endpoint>_<stock_code>.json``
- ``sec/submissions/CIK<cik10>.json``
- ``dart/document/<rcept_no>.xml`` (the body member of ``document.xml``, for table facts)

Bodies are first *staged* in memory and written by :meth:`PinnedStore.commit` only after the
run's database transaction has committed, so a run that fails or rolls back never replaces a
pinned file that matches the stored rows. A body staged ``only_if_absent`` (a DART "no data"
answer) never replaces an existing file.

A write goes to a temporary file in the target directory and is renamed into place, so a
reader never sees a partial file. Before any write the body is scanned for the DART key: the
configured key itself, the text ``crtfc_key`` and, in ``dart/`` files, any 40-character hex
string (the shape of a key). A body that matches is refused and nothing is written.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

_SAFE_PART = re.compile(r"[A-Za-z0-9_.-]+")
_KEY_LIKE = re.compile(rb"(?<![0-9A-Za-z])[0-9a-fA-F]{40}(?![0-9A-Za-z])")


class PinnedError(RuntimeError):
    """A response could not be saved as a pinned file."""


def dart_annual_path(corp_code: str, bsns_year: str, reprt_code: str, fs_div: str) -> str:
    return f"dart/fnlttSinglAcntAll/{corp_code}_{bsns_year}_{reprt_code}_{fs_div}.json"


def sec_companyfacts_path(cik10: str) -> str:
    return f"sec/companyfacts/CIK{cik10}.json"


def dart_structured_path(endpoint: str, stock_code: str) -> str:
    return f"dart/structured/{endpoint}_{stock_code}.json"


def dart_document_path(rcept_no: str) -> str:
    return f"dart/document/{rcept_no}.xml"


def sec_submissions_path(cik10: str) -> str:
    return f"sec/submissions/CIK{cik10}.json"


def scan_for_key(relative: str, body: bytes, secrets: Sequence[str] = ()) -> None:
    """Raise :class:`PinnedError` when ``body`` holds, or looks like it holds, a DART key."""
    for secret in secrets:
        if secret and secret.encode() in body:
            raise PinnedError(f"{relative}: body contains the configured API key; not saved")
    if b"crtfc_key" in body:
        raise PinnedError(f"{relative}: body contains 'crtfc_key'; not saved")
    if relative.startswith("dart/") and _KEY_LIKE.search(body):
        raise PinnedError(f"{relative}: body contains a key-like 40-character hex value; not saved")


class PinnedStore:
    """Stages and writes pinned files under ``root``; ``saved`` lists the paths written."""

    def __init__(self, root: Path | str, secrets: Sequence[str] = ()) -> None:
        self.root = Path(root)
        self._secrets = tuple(secrets)
        self.saved: list[str] = []
        self._staged: dict[str, tuple[bytes, bool]] = {}

    def _check(self, relative: str, body: bytes) -> list[str]:
        parts = relative.split("/")
        if not parts or any(not _SAFE_PART.fullmatch(p) or p in (".", "..") for p in parts):
            raise PinnedError(f"unsafe pinned path {relative!r}")
        scan_for_key(relative, body, self._secrets)
        return parts

    def stage(self, relative: str, body: bytes, *, only_if_absent: bool = False) -> None:
        """Hold ``body`` for :meth:`commit`; a refused body raises now. A later body for the
        same path replaces an earlier one."""
        self._check(relative, body)
        self._staged[relative] = (body, only_if_absent)

    def commit(self) -> list[str]:
        """Write every staged body; returns problem lines (a skipped or failed write).

        Call it once the database transaction that stored the matching rows has committed.
        """
        problems: list[str] = []
        staged, self._staged = self._staged, {}
        for relative, (body, only_if_absent) in staged.items():
            if only_if_absent and self.root.joinpath(*relative.split("/")).exists():
                problems.append(
                    f"pinned {relative}: the response had no data; the existing file was kept"
                )
                continue
            try:
                self.save(relative, body)
            except PinnedError as exc:
                problems.append(f"pinned {exc}")
        return problems

    def save(self, relative: str, body: bytes) -> Path:
        parts = self._check(relative, body)
        target = self.root.joinpath(*parts)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
        except OSError as exc:
            raise PinnedError(f"{relative}: {exc}") from exc
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except OSError as exc:
            Path(temp_name).unlink(missing_ok=True)
            raise PinnedError(f"{relative}: {exc}") from exc
        if relative not in self.saved:
            self.saved.append(relative)
        return target

    def sink(
        self, relative: str, problems: list[str] | None = None, *, only_if_absent: bool = False
    ) -> Callable[[bytes], None]:
        """A callback for a client's ``on_body`` that stages the body.

        With ``problems`` a refused body is recorded there and the run goes on; without it
        the :class:`PinnedError` propagates.
        """

        def write(body: bytes) -> None:
            try:
                self.stage(relative, body, only_if_absent=only_if_absent)
            except PinnedError as exc:
                if problems is None:
                    raise
                problems.append(f"pinned {exc}")

        return write


SAVE_PINNED_HELP = {
    "default": None,
    "help": "also write the regulator responses the parsers consumed to DIR, in the layout "
    "python -m app.build.verify reads (for example backend/data/pinned)",
}


def open_pinned_store(directory: str | None) -> PinnedStore | None:
    """A store for ``--save-pinned DIR``, scanning bodies for the configured DART key."""
    if not directory:
        return None
    from app.config import get_settings  # only needed when the option is used

    secret = get_settings().dart_api_key
    return PinnedStore(directory, [secret.get_secret_value()] if secret is not None else [])


def format_pinned(store: PinnedStore) -> str:
    lines = [f"pinned: {len(store.saved)} file(s) written under {store.root}"]
    lines.extend(f"  {relative}" for relative in store.saved)
    return "\n".join(lines)
