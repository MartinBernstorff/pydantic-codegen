import inspect
import os
import shutil
import subprocess
from pathlib import Path

from iterpy import Arr
from pydantic import ConfigDict, RootModel

from pydantic_codegen.ir import FrozenText, Model
from pydantic_codegen.renderer import RecipeLabel, rendered


class OutputPath(FrozenText): ...


class RuffExecutable(RootModel[Path]):
    model_config = ConfigDict(frozen=True)


class RecipeFile(RootModel[Path]):
    model_config = ConfigDict(frozen=True)


class RepoRootNotFoundError(Exception):
    def __init__(self, recipe: RecipeFile) -> None:
        super().__init__(f"no .git directory found above {recipe.root}")


class FormatterNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("ruff was not found on PATH")


class File:
    def __init__(self, path: OutputPath, *model_lists: Arr[Model]) -> None:
        self.recipe = Path(inspect.stack()[1].filename).resolve()
        self.path = (self.recipe.parent / path.root).resolve()
        self.models = Arr(model_lists).flatten()

    def label(self) -> RecipeLabel:
        root = next(
            (parent for parent in self.recipe.parents if (parent / ".git").exists()),
            None,
        )
        if root is None:
            raise RepoRootNotFoundError(RecipeFile(self.recipe))
        return RecipeLabel(f"/{self.recipe.relative_to(root)}")


def _ruff() -> RuffExecutable:
    found = shutil.which("ruff")
    if found is None:
        raise FormatterNotFoundError
    return RuffExecutable(Path(found))


def _format(files: list[File], ruff: RuffExecutable) -> None:
    written = Arr(files).map(lambda file: str(file.path)).to_list()
    # ruff discovers config by walking up from its working directory, so cwd decides
    # which config the output is formatted with.
    directory = os.path.commonpath(
        Arr(files).map(lambda file: str(file.path.parent)).to_list()
    )
    _ = subprocess.run(
        [str(ruff.root), "check", "--select", "I", "--fix", *written],
        cwd=directory,
        check=True,
    )
    _ = subprocess.run([str(ruff.root), "format", *written], cwd=directory, check=True)


def write(files: list[File]) -> None:
    if not files:
        return
    ruff = _ruff()
    labelled = Arr(files).map(lambda file: (file, file.label())).to_list()
    for file, label in labelled:
        file.path.parent.mkdir(parents=True, exist_ok=True)
        _ = file.path.write_text(rendered(file.models, label).root)
    _format(files, ruff)
