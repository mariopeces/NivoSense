# G-Code T2.1 round 2, run in WSL Ubuntu (x86_64) on a fresh clone at bad749e.
uv python install 3.11
uv venv --seed -p 3.11 venvrt && venvrt/bin/python -m pip install --no-cache-dir --require-hashes -r pipelines/requirements.lock
uv venv --seed -p 3.11 venv   && venv/bin/python -m pip install --no-cache-dir --require-hashes -r pipelines/requirements-dev.lock
# Lock reproduction (fresh resolution into /tmp, compared without header comments)
(cd pipelines && uv pip compile requirements.in --generate-hashes --python-version 3.11 --python-platform x86_64-manylinux_2_28 -o /tmp/requirements.repro.lock)
(cd pipelines && uv pip compile requirements-dev.in --generate-hashes --python-version 3.11 --python-platform x86_64-manylinux_2_28 -o /tmp/requirements-dev.repro.lock)
# Rebuild from the live REDIAM WFS + MITECO ENP zip, then compare outputs with HEAD
venvrt/bin/python -m pipelines.domain.build && git status --short
# Corrupted sources (each in its own --cache dir)
venvrt/bin/python -m pipelines.domain.build --cache c1   # ENP zip with one byte overwritten
venvrt/bin/python -m pipelines.domain.build --cache c2   # REDIAM GML with one coordinate digit changed in a Sierra Nevada feature
venvrt/bin/python -m pipelines.domain.build --subbasin-zips c3/A_cuencas_rios_Atl_Sur.zip   # 4 KiB random bytes
# Checks
venv/bin/ruff check . ; venv/bin/mypy ; venv/bin/pytest -q
# Areas, round 1 vs round 2
venvrt/bin/python areas.py 2095dc9 bad749e
