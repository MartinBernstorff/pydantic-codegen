import inspect
import os
import shutil
import subprocess
from pathlib import Path

from iterpy import Arr
from pydantic import ConfigDict, RootModel

from pydantic_codegen.ir import Model
from pydantic_codegen.renderer import RecipeLabel, rendered


class OutputPath(RootModel[str]):
    model_config = ConfigDict(frozen=True)


class RepoRootNotFoundError(Exception):
    def __init__(self, recipe: Path) -> None:
        super().__init__(f"no .git directory found above {recipe}")


class FormatterNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("ruff was not found on PATH")


def _repo_root(recipe: Path) -> Path:
    root = next(
        (parent for parent in recipe.parents if (parent / ".git").exists()), None
    )
    if root is None:
        raise RepoRootNotFoundError(recipe)
    return root


class File:
    def __init__(self, path: OutputPath, *model_lists: Arr[Model]) -> None:
        self.recipe = Path(inspect.stack()[1].filename).resolve()
        self.path = (self.recipe.parent / path.root).resolve()
        self.models = Arr(model_lists).flatten()

    def label(self) -> RecipeLabel:
        relative = self.recipe.relative_to(_repo_root(self.recipe))
        return RecipeLabel(f"/{relative}")


def _ruff() -> Path:
    found = shutil.which("ruff")
    if found is None:
        raise FormatterNotFoundError
    return Path(found)


def _format(paths: Arr[Path], ruff: Path) -> None:
    written = paths.map(str).to_list()
    # ruff discovers config by walking up from its working directory, so cwd decides
    # which config the output is formatted with.
    directory = os.path.commonpath(paths.map(lambda path: str(path.parent)).to_list())
    _ = subprocess.run(
        [str(ruff), "check", "--select", "I", "--fix", *written],
        cwd=directory,
        check=True,
    )
    _ = subprocess.run([str(ruff), "format", *written], cwd=directory, check=True)


def write(files: list[File]) -> None:
    ruff = _ruff()
    labelled = Arr(files).map(lambda file: (file, file.label())).to_list()
    for file, label in labelled:
        file.path.parent.mkdir(parents=True, exist_ok=True)
        _ = file.path.write_text(rendered(file.models, label).root)
    _format(Arr(files).map(lambda file: file.path), ruff)
