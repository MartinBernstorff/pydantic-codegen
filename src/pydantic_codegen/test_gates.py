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
from pydantic_codegen.loader import load
from pydantic_codegen.transformers import pipe, rename_model, set_bases
from pydantic_codegen.writing import File, write

SUBFOLDER = "pydantic_codegen.test_corpus_subfolder:Subfolder"
NOTE = "pydantic_codegen.test_corpus_collision:Note"
PAIR = "pydantic_codegen.test_corpus_pair:Pair"
COMMENT = "pydantic_codegen.test_corpus_identified:Comment"
DEFERRED = "pydantic_codegen.test_corpus_deferred:Deferred"
ATTRIBUTED = "pydantic_codegen.test_corpus_attributed:Attributed"


def test_a_file_holding_no_models_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(EmptyFileError, match=r"empty\.py"):
        write([File(str(tmp_path / "empty.py"))])


def test_two_files_writing_to_one_path_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DuplicatePathError, match=r"clash\.py"):
        write(
            [
                File(str(tmp_path / "clash.py"), load(SUBFOLDER)),
                File(str(tmp_path / "clash.py"), load(SUBFOLDER)),
            ]
        )


def test_two_models_sharing_a_name_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DuplicateModelError, match="Subfolder"):
        write([File(str(tmp_path / "twins.py"), load(SUBFOLDER), load(SUBFOLDER))])


def test_one_name_bound_by_two_modules_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ImportCollisionError) as raised:
        write([File(str(tmp_path / "collision.py"), load(SUBFOLDER), load(NOTE))])

    message = str(raised.value)
    assert "SubfolderName" in message
    assert "pydantic_codegen.test_corpus_subfolder" in message
    assert "pydantic_codegen.test_corpus_collision" in message
    assert "Subfolder.name" in message
    assert "Note.subfolder_name" in message


def test_an_import_shadowed_by_a_generated_class_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ShadowedImportError) as raised:
        write(
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


def test_a_base_that_declares_fields_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FieldCarryingBaseError) as raised:
        write([File(str(tmp_path / "comment.py"), load(COMMENT))])

    message = str(raised.value)
    assert "Identified" in message
    assert "id" in message


def test_a_dotted_base_that_declares_fields_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FieldCarryingBaseError) as raised:
        write([File(str(tmp_path / "attributed.py"), load(ATTRIBUTED))])

    message = str(raised.value)
    assert "ident.Identified" in message
    assert "id" in message


def test_a_base_set_by_the_recipe_that_declares_fields_is_an_error(
    tmp_path: Path,
) -> None:
    with pytest.raises(FieldCarryingBaseError, match="Identified"):
        write(
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


def test_a_recipe_without_set_bases_keeps_the_source_base(tmp_path: Path) -> None:
    generated = tmp_path / "subfolder.py"

    write([File(str(generated), load(SUBFOLDER))])

    assert "class Subfolder(BaseModel):" in generated.read_text()


def test_a_deferred_source_import_becomes_a_real_one(tmp_path: Path) -> None:
    generated = tmp_path / "deferred.py"

    write([File(str(generated), load(DEFERRED))])

    written = generated.read_text()
    assert "from pydantic_codegen.test_corpus_asset_location import FolderId" in written
    assert "TYPE_CHECKING" not in written
    assert "__future__" not in written


def test_two_fields_needing_one_import_dedupe(tmp_path: Path) -> None:
    generated = tmp_path / "pair.py"

    write([File(str(generated), load(PAIR))])

    imported = "from pydantic_codegen.test_corpus_asset_location import FolderId"
    assert generated.read_text().count(imported) == 1
