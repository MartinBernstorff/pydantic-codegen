# pydantic-codegen

A Python library, published to PyPI as `pydantic-codegen`.

## Layout

One package, one distribution: `src/pydantic_codegen/`. Tests live beside the code
they test. `tach` enforces module boundaries as the package grows.

## Tickets

We use Todoist tickets to track work. All work is tagged with "@it-pydantic-codegen".

## Python

- **Never take primitives as function parameters.** Wrap them in a Pydantic `RootModel` — a `str` says nothing about what it is; `ModuleName` does. Enforced by `moon run :noprim`.
- **No `tests/` folder.** Tests live beside the code as `test_<module>.py` — a test you can see is a test you maintain.
- **Never maintain `__all__`, and keep every `__init__.py` empty.** A wall of `from x import Y as Y` is an `__all__` in disguise: a second source of truth that drifts, and a sorted list every branch inserts into. Import from the defining module (`from pydantic_codegen.python_source import PythonSource`); `tach` is what enforces the layer boundary. `moon run :modularity` fails on a non-empty `__init__.py`.
- **Prefer iterators over manual for-loops.** Use `iterpy`: `Arr([1,2,3]).map(lambda x: x+1).filter(lambda x: x>2).to_list()` — pipelines read top-to-bottom without accumulator state.
- **Avoid constants.** Before defining one, ask whether it should be an argument from the caller — a constant is a decision frozen at the wrong layer.
- **Default to no comments.** If code needs a comment to be understood, fix the code. When you must, one line on *why* (constraint, invariant, bug), never *what*. No docstrings.

## Moon

Always run tasks through moon, never the tool directly: `moon run :test`, not `pytest`.
Moon resolves task dependencies and caches aggressively.

| Task | Does |
| --- | --- |
| `moon run :test` | pytest |
| `moon run :lint` | ruff check |
| `moon run :lint-fix` | ruff check --fix |
| `moon run :format` | ruff format |
| `moon run :format-check` | ruff format --check |
| `moon run :typecheck` | pyrefly |
| `moon run :modularity` | tach check + tach check-external, and fails on a non-empty `__init__.py` |
| `moon run :noprim` | noprim, the primitive-parameter linter |
| `moon run :actionlint` | actionlint over `.github/workflows/` |
| `moon run :smoke` | builds the wheel, installs it into a clean venv at the Python floor, imports it |

**A task's inputs must include everything it reads.** A missing input means moon
replays a stale cache — a test that no longer holds still reports a pass.

`:test` runs under `--testmon`, so a run that reports `no tests ran` means testmon
decided nothing relevant changed, not that the suite is empty. `.testmondata` is
gitignored and local; delete it to force a full run.

## Tooling

- Tool settings live in each tool's own file — `ruff.toml`, `pyrefly.toml`, `tach.toml`, `pytest.toml` — **not** in `pyproject.toml`. Keeps config where the tool's docs say to look. Packaging is the exception: `[build-system]` and `[tool.hatch.build.*]` have nowhere else to live.
- Commits are validated automatically by lefthook pre-commit hooks (`lefthook.yml`). Install with `uv run lefthook install`; Conductor's setup script does this per clone.

## Releasing

The version is not written down anywhere — `hatch-vcs` derives it from the git tag, and
python-semantic-release derives the tag from commit messages. So **the PR title is the
release note**, and it must be a [conventional commit](https://www.conventionalcommits.org/):

| Prefix | Effect below 1.0.0 |
| --- | --- |
| `fix: …` | patch — `0.3.1` → `0.3.2` |
| `feat: …` | minor — `0.3.1` → `0.4.0` |
| `feat!: …` or a `BREAKING CHANGE:` footer | minor, until 1.0.0 (`major_on_zero = false`) |
| `chore: …`, `docs: …`, `refactor: …`, `test: …`, `ci: …` | no release |

PRs are squash-merged, so the PR title becomes the commit subject on main and is the
only thing the parser reads — an individual commit inside the branch is never parsed.
Nothing enforces this; a non-conventional title means `release` runs, finds no
releasable change, and exits without publishing.

Merging to main runs `ci`; on success, `release` tags, creates the GitHub Release,
builds, and publishes to PyPI via trusted publishing (no API token). To cut a release
from an unchanged main, dispatch `release` manually.

Publishing requires a trusted publisher registered at
[pypi.org/manage/account/publishing](https://pypi.org/manage/account/publishing/) —
owner `MartinBernstorff`, repository `pydantic-codegen`, workflow `release.yml`, no
environment. A one-time manual step, since only a logged-in human can do it. See
`/wizard`.
