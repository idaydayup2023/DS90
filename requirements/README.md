# Optional dependency locks

DB90 keeps ASR, OCR, and IMDb dependencies in separate virtual environments so
large or native packages do not leak into the system Python installation.

- `*.in` files contain the reviewed direct versions.
- `*.lock` files contain the complete cross-platform resolution and distribution
  hashes. Runtime installation always uses `--require-hashes`.
- Automatic installation is disabled by default. If `auto_install` is explicitly
  enabled, the same lock files are used; arbitrary `pip install -U` commands are
  never run.

Install or update all optional environments:

```bash
python3 install_optional_dependencies.py
```

Install one group only:

```bash
python3 install_optional_dependencies.py asr
python3 install_optional_dependencies.py ocr
python3 install_optional_dependencies.py imdb
```

Regenerate locks after reviewing new direct versions:

```bash
uv pip compile requirements/asr.in --python-version 3.11 --universal --generate-hashes -o requirements/asr.lock
uv pip compile requirements/ocr.in --python-version 3.11 --universal --generate-hashes -o requirements/ocr.lock
uv pip compile requirements/imdb.in --python-version 3.11 --universal --generate-hashes -o requirements/imdb.lock
```

For an offline deployment, download wheels on a machine matching the target OS,
CPU architecture, and Python minor version, then transfer the wheelhouse and the
repository together:

```bash
python3 -m pip download --require-hashes -r requirements/asr.lock -d wheelhouse/asr
python3 -m pip download --require-hashes -r requirements/ocr.lock -d wheelhouse/ocr
python3 -m pip download --require-hashes -r requirements/imdb.lock -d wheelhouse/imdb
```

On the offline host, transfer the repository and `wheelhouse/` tree together,
then run the same installer in offline mode. This also writes the lock digest
marker used by the application to validate each environment:

```bash
python3 install_optional_dependencies.py --wheelhouse-root wheelhouse asr ocr imdb
```

Without `--wheelhouse-root`, the installer uses PyPI and therefore requires
network access.
