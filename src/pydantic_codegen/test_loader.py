from pathlib import Path

import pytest
from pydantic import BaseModel, RootModel
from pydantic.fields import FieldInfo

from pydantic_codegen.ir import (
    AnnotationText,
    Base,
    BaseName,
    Field,
    FieldName,
    Import,
    Model,
    ModelName,
    ModuleName,
    SymbolName,
)
from pydantic_codegen.loader import MalformedTargetError, ModelTarget, load
from pydantic_codegen.python_source import PythonSource
from pydantic_codegen.rejections import UndeclaredFieldError, UnresolvableNameError
from pydantic_codegen.test_corpus_builder import SourceModule, corpus

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

PACKAGED_STAMPING = SourceModule(
    name=ModuleName("packaged.stamping"),
    source=PythonSource("""
import datetime

from pydantic import BaseModel


class Stamped(BaseModel):
    created: datetime.datetime
"""),
)

INHERITING = SourceModule(
    name=ModuleName("packaged.inheriting"),
    source=PythonSource("""
from pydantic import RootModel

from .stamping import Stamped


class RecordLabel(RootModel[str]): ...


class Record(Stamped):
    label: RecordLabel
"""),
)

TAGGING = SourceModule(
    name=ModuleName("tagging"),
    source=PythonSource("""
from pydantic import RootModel


class Tag(RootModel[str]): ...
"""),
)

BOUND_NAMES = SourceModule(
    name=ModuleName("bound_names"),
    source=PythonSource("""
from pydantic import BaseModel, Field

from tagging import Tag


class Sorted(BaseModel):
    tags: list[Tag] = Field(
        default_factory=lambda: sorted([Tag("b"), Tag("a")], key=lambda tag: tag.root)
    )


class Comprehended(BaseModel):
    tags: list[Tag] = Field(default_factory=lambda: [Tag(word) for word in ("new",)])
"""),
)

GENERIC = SourceModule(
    name=ModuleName("generic"),
    source=PythonSource("""
from pydantic import BaseModel


class Identified[ID](BaseModel):
    id: ID
"""),
)

PARAMETRISED = SourceModule(
    name=ModuleName("parametrised"),
    source=PythonSource("""
from generic import Identified

from tagging import Tag


class Listed(Identified[list[Tag]]): ...
"""),
)


def test_loads_fields_bases_and_imports(tmp_path: Path) -> None:
    with corpus(tmp_path, [LOCATION, SUBFOLDER]):
        loaded = load("subfolder:Subfolder")

    assert loaded == [
        Model(
            name=ModelName("Subfolder"),
            bases=(Base(name=BaseName("BaseModel")),),
            fields=(
                Field(
                    name=FieldName("name"),
                    annotation=AnnotationText("SubfolderName"),
                    imports=(
                        Import(
                            module=ModuleName("subfolder"),
                            name=SymbolName("SubfolderName"),
                        ),
                    ),
                ),
                Field(
                    name=FieldName("parent_folder_id"),
                    annotation=AnnotationText("FolderId"),
                    imports=(
                        Import(
                            module=ModuleName("location"), name=SymbolName("FolderId")
                        ),
                    ),
                ),
            ),
            imports=(
                Import(module=ModuleName("pydantic"), name=SymbolName("BaseModel")),
            ),
        )
    ]


def test_a_relative_import_is_absolute_in_the_ir(tmp_path: Path) -> None:
    with corpus(tmp_path, [PACKAGED_STAMPING, INHERITING]):
        loaded = load("packaged.inheriting:Record")

    assert loaded[0].imports == (
        Import(module=ModuleName("packaged.stamping"), name=SymbolName("Stamped")),
    )


@pytest.mark.parametrize(
    "target",
    [ModelTarget("bound_names:Sorted"), ModelTarget("bound_names:Comprehended")],
    ids=lambda target: target.root,
)
def test_a_name_bound_inside_the_expression_needs_no_import(
    target: ModelTarget, tmp_path: Path
) -> None:
    with corpus(tmp_path, [TAGGING, BOUND_NAMES]):
        loaded = load(target.root)

    imported = {
        statement.bound_name()
        for declared in loaded[0].fields
        if declared.name == FieldName("tags")
        for statement in declared.imports
    }
    assert imported <= {SymbolName("Field"), SymbolName("Tag")}


def test_a_generic_base_is_kept_verbatim_however_it_is_parametrised(
    tmp_path: Path,
) -> None:
    with corpus(tmp_path, [TAGGING, GENERIC, PARAMETRISED]):
        loaded = load("parametrised:Listed")

    assert loaded[0].bases == (Base(name=BaseName("Identified[list[Tag]]")),)
    assert loaded[0].fields == ()


class LocalId(RootModel[str]): ...


def _injecting_a_field(model: type[BaseModel]) -> type[BaseModel]:
    model.model_fields["ghost"] = FieldInfo(annotation=int)
    return model


@_injecting_a_field
class Injected(BaseModel):
    known: LocalId


# Hidden from a top-level scan of the module's imports, but bound at runtime.
try:
    from decimal import Decimal as Conditional
except ImportError as missing:  # pragma: no cover
    raise RuntimeError from missing


class Conditionally(BaseModel):
    hidden: Conditional


def test_a_field_no_class_in_the_mro_declares_is_unrepresentable() -> None:
    with pytest.raises(UndeclaredFieldError, match="ghost"):
        _ = load("pydantic_codegen.test_loader:Injected")


def test_a_name_the_module_neither_imports_nor_defines_is_unrepresentable() -> None:
    with pytest.raises(UnresolvableNameError):
        _ = load("pydantic_codegen.test_loader:Conditionally")


def test_a_target_without_a_class_is_malformed() -> None:
    with pytest.raises(MalformedTargetError):
        _ = load("pydantic_codegen.test_loader")
