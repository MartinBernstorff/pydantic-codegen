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
from pydantic_codegen.ir import Model
from pydantic_codegen.loader import load
from pydantic_codegen.python_source import PythonSource
from pydantic_codegen.transformers import pipe, rename_model, set_bases
from pydantic_codegen.writing import File, generated

SUBFOLDER = "pydantic_codegen.test_corpus_subfolder:Subfolder"
NOTE = "pydantic_codegen.test_corpus_collision:Note"
PAIR = "pydantic_codegen.test_corpus_pair:Pair"
COMMENT = "pydantic_codegen.test_corpus_identified:Comment"
DEFERRED = "pydantic_codegen.test_corpus_deferred:Deferred"
ATTRIBUTED = "pydantic_codegen.test_corpus_attributed:Attributed"


def _source(models: list[Model]) -> PythonSource:
    return generated([File("generated.py", models)])[0].source


def test_a_file_holding_no_models_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(EmptyFileError, match=r"empty\.py"):
        _ = generated([File(str(tmp_path / "empty.py"))])


def test_two_files_writing_to_one_path_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DuplicatePathError, match=r"clash\.py"):
        _ = generated(
            [
                File(str(tmp_path / "clash.py"), load(SUBFOLDER)),
                File(str(tmp_path / "clash.py"), load(SUBFOLDER)),
            ]
        )


def test_two_models_sharing_a_name_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DuplicateModelError, match="Subfolder"):
        _ = generated(
            [File(str(tmp_path / "twins.py"), load(SUBFOLDER), load(SUBFOLDER))]
        )


def test_one_name_bound_by_two_modules_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ImportCollisionError) as raised:
        _ = generated(
            [File(str(tmp_path / "collision.py"), load(SUBFOLDER), load(NOTE))]
        )

    message = str(raised.value)
    assert "SubfolderName" in message
    assert "pydantic_codegen.test_corpus_subfolder" in message
    assert "pydantic_codegen.test_corpus_collision" in message
    assert "Subfolder.name" in message
    assert "Note.subfolder_name" in message


def test_an_import_shadowed_by_a_generated_class_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ShadowedImportError) as raised:
        _ = generated(
            [
                File(
                    str(tmp_path / "shadowed.py"),
                    load(NOTE),
                    pipe(load(PAIR), rename_model("SubfolderName")),
                )
            ]
        )

    message = str(raised.value)
    assert "SubfolderName" in message
    assert "Note.subfolder_name" in message


def test_a_source_base_that_declares_fields_is_kept() -> None:
    source = _source(load(COMMENT))

    assert "class Comment(Identified):" in source.root


def test_a_dotted_source_base_is_kept() -> None:
    source = _source(load(ATTRIBUTED))

    assert "class Attributed(ident.Identified):" in source.root


def test_a_base_set_by_the_recipe_that_declares_fields_is_an_error(
    tmp_path: Path,
) -> None:
    with pytest.raises(FieldCarryingBaseError, match="Identified"):
        _ = generated(
            [
                File(
                    str(tmp_path / "based.py"),
                    pipe(
                        load(SUBFOLDER),
                        set_bases("pydantic_codegen.test_corpus_identified:Identified"),
                    ),
                )
            ]
        )


def test_a_recipe_without_set_bases_keeps_the_source_base() -> None:
    source = _source(load(SUBFOLDER))

    assert "class Subfolder(BaseModel):" in source.root


def test_a_deferred_source_import_becomes_a_real_one() -> None:
    source = _source(load(DEFERRED))

    assert (
        "from pydantic_codegen.test_corpus_asset_location import FolderId"
        in source.root
    )
    assert "TYPE_CHECKING" not in source.root
    assert "__future__" not in source.root


def test_two_fields_needing_one_import_dedupe() -> None:
    source = _source(load(PAIR))

    imported = "from pydantic_codegen.test_corpus_asset_location import FolderId"
    assert source.root.count(imported) == 1
