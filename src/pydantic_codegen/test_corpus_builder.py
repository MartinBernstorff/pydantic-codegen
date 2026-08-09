import importlib
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pydantic_codegen.ir import ModuleName
from pydantic_codegen.loader import load
from pydantic_codegen.python_source import PythonSource


class SourceModule(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: ModuleName
    source: PythonSource


# Names stay deterministic so they read back in the generated imports, which means
# two tests can declare the same one; unbinding on exit is what keeps them apart
# under pytest-randomly.
@contextmanager
def corpus(root: Path, modules: list[SourceModule]) -> Generator[None, None, None]:
    root.mkdir(parents=True, exist_ok=True)
    for module in modules:
        *packages, leaf = module.name.root.split(".")
        directory = root.joinpath(*packages)
        directory.mkdir(parents=True, exist_ok=True)
        for depth in range(len(packages)):
            (root.joinpath(*packages[: depth + 1]) / "__init__.py").touch()
        _ = (directory / f"{leaf}.py").write_text(module.source.root)
    sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    try:
        yield
    finally:
        sys.path.remove(str(root))
        bound = {module.name.root for module in modules}
        for name in bound | {name.split(".")[0] for name in bound}:
            _ = sys.modules.pop(name, None)


TAGGING = SourceModule(
    name=ModuleName("tagging"),
    source=PythonSource("""
from pydantic import BaseModel, RootModel


class Tag(RootModel[str]): ...


class Tagged(BaseModel):
    tag: Tag
"""),
)


def test_a_declared_module_is_loadable(tmp_path: Path) -> None:
    with corpus(tmp_path, [TAGGING]):
        only = load("tagging:Tagged")[0]

    assert only.name.root == "Tagged"
    assert only.fields[0].annotation.root == "Tag"


def test_a_module_name_outlives_no_declaration(tmp_path: Path) -> None:
    with corpus(tmp_path, [TAGGING]):
        pass

    assert "tagging" not in sys.modules
