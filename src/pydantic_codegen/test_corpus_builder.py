import importlib
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

from pydantic import BaseModel, ConfigDict

from pydantic_codegen.ir import ModuleName
from pydantic_codegen.loader import load
from pydantic_codegen.python_source import PythonSource


class SourceModule(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: ModuleName
    source: PythonSource


def _written(root: Path, module: SourceModule) -> None:
    *packages, leaf = module.name.root.split(".")
    directory = root
    for package in packages:
        directory = directory / package
        directory.mkdir(exist_ok=True)
        (directory / "__init__.py").touch()
    _ = (directory / f"{leaf}.py").write_text(module.source.root)


# A package binds a name too, so `packaged.inheriting` also leaves `packaged` behind.
def _bindings(modules: list[SourceModule]) -> set[ModuleName]:
    return {
        ModuleName(".".join(parts[: depth + 1]))
        for module in modules
        for parts in [module.name.root.split(".")]
        for depth in range(len(parts))
    }


# Names stay deterministic so they read back in the generated imports, which means two
# tests can declare the same one; restoring what was bound before is what keeps them
# apart under pytest-randomly.
@contextmanager
def corpus(root: Path, modules: list[SourceModule]) -> Generator[None, None, None]:
    root.mkdir(parents=True, exist_ok=True)
    for module in modules:
        _written(root, module)
    bindings = _bindings(modules)
    shadowed = {
        name.root: sys.modules[name.root]
        for name in bindings
        if name.root in sys.modules
    }
    sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    try:
        yield
    finally:
        sys.path.remove(str(root))
        for name in bindings:
            _ = sys.modules.pop(name.root, None)
        sys.modules.update(shadowed)


@contextmanager
def executed(
    source: PythonSource, name: ModuleName
) -> Generator[ModuleType, None, None]:
    module = ModuleType(name.root)
    # Pydantic resolves a forward ref through sys.modules, so a module that is not
    # registered leaves `note: "Tag | None"` an unevaluated ForwardRef.
    sys.modules[name.root] = module
    try:
        exec(source.root, module.__dict__)
        yield module
    finally:
        _ = sys.modules.pop(name.root, None)


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
