from pathlib import Path

import pytest

from pydantic_codegen.ir import ModuleName
from pydantic_codegen.loader import load
from pydantic_codegen.python_source import PythonSource
from pydantic_codegen.renderer import RecipeLabel
from pydantic_codegen.test_corpus_builder import SourceModule, corpus
from pydantic_codegen.writing import (
    File,
    FormatterNotFoundError,
    RecipeFile,
    RepoRootNotFoundError,
    generated,
    label_of,
    write,
)

RECIPE = RecipeLabel("/codegen.py")

SUBFOLDER = SourceModule(
    name=ModuleName("subfolder"),
    source=PythonSource("""
from pydantic import BaseModel, RootModel


class SubfolderName(RootModel[str]): ...


class Subfolder(BaseModel):
    name: SubfolderName
"""),
)


def test_generating_pairs_the_output_path_with_its_source(tmp_path: Path) -> None:
    destination = tmp_path / "out" / "generated.py"

    with corpus(tmp_path, [SUBFOLDER]):
        only = generated([File(str(destination), load("subfolder:Subfolder"))], RECIPE)[
            0
        ]

    assert only.path == destination
    assert "class Subfolder(BaseModel):" in only.source.root
    assert not destination.exists()


def test_a_recipe_outside_a_repository_cannot_be_labelled(tmp_path: Path) -> None:
    with pytest.raises(RepoRootNotFoundError, match=r"codegen\.py"):
        _ = label_of(RecipeFile(tmp_path / "codegen.py"))


def test_a_missing_formatter_raises_instead_of_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    destination = tmp_path / "out" / "generated.py"

    with corpus(tmp_path, [SUBFOLDER]), pytest.raises(FormatterNotFoundError):
        write([File(str(destination), load("subfolder:Subfolder"))])

    assert not destination.parent.exists()
