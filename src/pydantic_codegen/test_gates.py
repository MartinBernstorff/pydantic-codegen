from pathlib import Path

import pytest

from pydantic_codegen.gates import (
    DuplicateModelError,
    DuplicatePathError,
    EmptyFileError,
    FieldCarryingBaseError,
    ImportCollisionError,
    ShadowedImportError,
)
from pydantic_codegen.ir import Model, ModuleName
from pydantic_codegen.loader import load
from pydantic_codegen.python_source import PythonSource
from pydantic_codegen.renderer import RecipeLabel
from pydantic_codegen.test_corpus_builder import SourceModule, corpus
from pydantic_codegen.transformers import pipe, rename_model, set_bases
from pydantic_codegen.writing import File, generated

RECIPE = RecipeLabel("/codegen.py")

LOCATION = SourceModule(
    name=ModuleName("location"),
    source=PythonSource("""
from pydantic import RootModel


class FolderId(RootModel[str]): ...
"""),
)

SUBFOLDER = SourceModule(
    name=ModuleName("subfolder"),
    source=PythonSource("""
from pydantic import BaseModel, RootModel

from location import FolderId


class SubfolderName(RootModel[str]): ...


class Subfolder(BaseModel):
    name: SubfolderName
    parent_folder_id: FolderId
"""),
)

# A second module binding SubfolderName, so the two imports collide in one file.
COLLISION = SourceModule(
    name=ModuleName("collision"),
    source=PythonSource("""
from pydantic import BaseModel, RootModel


class SubfolderName(RootModel[str]): ...


class Note(BaseModel):
    subfolder_name: SubfolderName
"""),
)

PAIR = SourceModule(
    name=ModuleName("pair"),
    source=PythonSource("""
from pydantic import BaseModel

from location import FolderId


class Pair(BaseModel):
    left: FolderId
    right: FolderId
"""),
)

IDENTIFIED = SourceModule(
    name=ModuleName("identified"),
    source=PythonSource("""
from pydantic import BaseModel, RootModel

from location import FolderId


class CommentBody(RootModel[str]): ...


class Identified(BaseModel):
    id: FolderId


class Comment(Identified):
    id: FolderId
    body: CommentBody
"""),
)

ATTRIBUTED = SourceModule(
    name=ModuleName("attributed"),
    source=PythonSource("""
import identified as ident

from location import FolderId


class Attributed(ident.Identified):
    id: FolderId
"""),
)

DEFERRED = SourceModule(
    name=ModuleName("deferred"),
    source=PythonSource("""
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from location import FolderId


class Deferred(BaseModel):
    folder_id: FolderId
"""),
)


def _source(models: list[Model]) -> PythonSource:
    return generated([File("generated.py", models)], RECIPE)[0].source


def test_a_file_holding_no_models_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(EmptyFileError, match=r"empty\.py"):
        _ = generated([File(str(tmp_path / "empty.py"))], RECIPE)


def test_two_files_writing_to_one_path_is_an_error(tmp_path: Path) -> None:
    with (
        corpus(tmp_path, [LOCATION, SUBFOLDER]),
        pytest.raises(DuplicatePathError, match=r"clash\.py"),
    ):
        _ = generated(
            [
                File(str(tmp_path / "clash.py"), load("subfolder:Subfolder")),
                File(str(tmp_path / "clash.py"), load("subfolder:Subfolder")),
            ],
            RECIPE,
        )


def test_two_models_sharing_a_name_is_an_error(tmp_path: Path) -> None:
    with (
        corpus(tmp_path, [LOCATION, SUBFOLDER]),
        pytest.raises(DuplicateModelError, match="Subfolder"),
    ):
        _ = generated(
            [
                File(
                    str(tmp_path / "twins.py"),
                    load("subfolder:Subfolder"),
                    load("subfolder:Subfolder"),
                )
            ],
            RECIPE,
        )


def test_one_name_bound_by_two_modules_is_an_error(tmp_path: Path) -> None:
    with (
        corpus(tmp_path, [LOCATION, SUBFOLDER, COLLISION]),
        pytest.raises(ImportCollisionError) as raised,
    ):
        _ = generated(
            [
                File(
                    str(tmp_path / "collision.py"),
                    load("subfolder:Subfolder"),
                    load("collision:Note"),
                )
            ],
            RECIPE,
        )

    message = str(raised.value)
    assert "SubfolderName" in message
    assert "subfolder" in message
    assert "collision" in message
    assert "Subfolder.name" in message
    assert "Note.subfolder_name" in message


def test_an_import_shadowed_by_a_generated_class_is_an_error(tmp_path: Path) -> None:
    with (
        corpus(tmp_path, [LOCATION, COLLISION, PAIR]),
        pytest.raises(ShadowedImportError) as raised,
    ):
        _ = generated(
            [
                File(
                    str(tmp_path / "shadowed.py"),
                    load("collision:Note"),
                    pipe(load("pair:Pair"), rename_model("SubfolderName")),
                )
            ],
            RECIPE,
        )

    message = str(raised.value)
    assert "SubfolderName" in message
    assert "Note.subfolder_name" in message


def test_a_source_base_that_declares_fields_is_kept(tmp_path: Path) -> None:
    with corpus(tmp_path, [LOCATION, IDENTIFIED]):
        source = _source(load("identified:Comment"))

    assert "class Comment(Identified):" in source.root


def test_a_dotted_source_base_is_kept(tmp_path: Path) -> None:
    with corpus(tmp_path, [LOCATION, IDENTIFIED, ATTRIBUTED]):
        source = _source(load("attributed:Attributed"))

    assert "class Attributed(ident.Identified):" in source.root


def test_a_base_set_by_the_recipe_that_declares_fields_is_an_error(
    tmp_path: Path,
) -> None:
    with (
        corpus(tmp_path, [LOCATION, SUBFOLDER, IDENTIFIED]),
        pytest.raises(FieldCarryingBaseError, match="Identified"),
    ):
        _ = generated(
            [
                File(
                    str(tmp_path / "based.py"),
                    pipe(
                        load("subfolder:Subfolder"),
                        set_bases("identified:Identified"),
                    ),
                )
            ],
            RECIPE,
        )


def test_a_recipe_without_set_bases_keeps_the_source_base(tmp_path: Path) -> None:
    with corpus(tmp_path, [LOCATION, SUBFOLDER]):
        source = _source(load("subfolder:Subfolder"))

    assert "class Subfolder(BaseModel):" in source.root


def test_a_deferred_source_import_becomes_a_real_one(tmp_path: Path) -> None:
    with corpus(tmp_path, [LOCATION, DEFERRED]):
        source = _source(load("deferred:Deferred"))

    assert "from location import FolderId" in source.root
    assert "TYPE_CHECKING" not in source.root
    assert "__future__" not in source.root


def test_two_fields_needing_one_import_dedupe(tmp_path: Path) -> None:
    with corpus(tmp_path, [LOCATION, PAIR]):
        source = _source(load("pair:Pair"))

    assert source.root.count("from location import FolderId") == 1
