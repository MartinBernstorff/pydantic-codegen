import inspect
import shutil
import subprocess
from pathlib import Path

from iterpy import Arr
from pydantic import BaseModel, ConfigDict, RootModel

from pydantic_codegen.gates import reject_duplicate_paths, reject_unwritable
from pydantic_codegen.ir import FrozenText, Model
from pydantic_codegen.python_source import PythonSource
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
    def __init__(self, path: str, *model_lists: list[Model]) -> None:
        self.recipe = Path(inspect.stack()[1].filename).resolve()
        self.path = (self.recipe.parent / OutputPath(path).root).resolve()
        self.models = Arr(model_lists).flatten()

    def label(self) -> RecipeLabel:
        root = next(
            (parent for parent in self.recipe.parents if (parent / ".git").exists()),
            None,
        )
        if root is None:
            raise RepoRootNotFoundError(RecipeFile(self.recipe))
        return RecipeLabel(f"/{self.recipe.relative_to(root)}")


class GeneratedFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path
    source: PythonSource


def _ruff() -> RuffExecutable:
    found = shutil.which("ruff")
    if found is None:
        raise FormatterNotFoundError
    return RuffExecutable(Path(found))


def _piped(
    ruff: RuffExecutable, arguments: list[str], path: Path, source: PythonSource
) -> PythonSource:
    # --stdin-filename is what ruff resolves config from, so the destination decides
    # which config the output is formatted with, not the working directory.
    finished = subprocess.run(
        [str(ruff.root), *arguments, "--stdin-filename", str(path), "-"],
        input=source.root,
        capture_output=True,
        text=True,
        check=True,
    )
    return PythonSource(finished.stdout)


def _formatted(path: Path, source: PythonSource, ruff: RuffExecutable) -> PythonSource:
    # --exit-zero: a diagnostic ruff cannot fix is not this library's failure.
    sorted_imports = _piped(
        ruff, ["check", "--select", "I", "--fix", "--exit-zero"], path, source
    )
    return _piped(ruff, ["format"], path, sorted_imports)


def generated(files: list[File]) -> list[GeneratedFile]:
    reject_duplicate_paths(Arr(files).map(lambda file: file.path).to_list())
    for file in files:
        reject_unwritable(file.path, file.models)
    ruff = _ruff()
    return (
        Arr(files)
        .map(
            lambda file: GeneratedFile(
                path=file.path,
                source=_formatted(file.path, rendered(file.models, file.label()), ruff),
            )
        )
        .to_list()
    )


def write(files: list[File]) -> None:
    for output in generated(files):
        output.path.parent.mkdir(parents=True, exist_ok=True)
        _ = output.path.write_text(output.source.root)
