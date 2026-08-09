import pytest
from pydantic import BaseModel

from pydantic_codegen.ir import (
    AnnotationText,
    BaseName,
    Field,
    FieldName,
    Import,
    Model,
    ModelName,
    ModuleName,
    SymbolName,
)
from pydantic_codegen.loader import (
    MalformedTargetError,
    ModelTarget,
    UndeclaredFieldError,
    UnresolvableNameError,
    load,
)
from pydantic_codegen.test_corpus_subfolder import Subfolder


def test_loads_fields_bases_and_imports() -> None:
    loaded = load(ModelTarget("pydantic_codegen.test_corpus_subfolder:Subfolder"))

    assert loaded.to_list() == [
        Model(
            name=ModelName("Subfolder"),
            bases=(BaseName("BaseModel"),),
            fields=(
                Field(
                    name=FieldName("name"),
                    annotation=AnnotationText("SubfolderName"),
                    imports=(
                        Import(
                            module=ModuleName("pydantic_codegen.test_corpus_subfolder"),
                            name=SymbolName("SubfolderName"),
                        ),
                    ),
                ),
                Field(
                    name=FieldName("parent_folder_id"),
                    annotation=AnnotationText("FolderId"),
                    imports=(
                        Import(
                            module=ModuleName(
                                "pydantic_codegen.test_corpus_asset_location"
                            ),
                            name=SymbolName("FolderId"),
                        ),
                    ),
                ),
            ),
            imports=(
                Import(module=ModuleName("pydantic"), name=SymbolName("BaseModel")),
            ),
        )
    ]


class Inherited(Subfolder):
    pass


# Hidden from a top-level scan of the module's imports, but bound at runtime.
try:
    from decimal import Decimal as Conditional
except ImportError as missing:  # pragma: no cover
    raise RuntimeError from missing


class Conditionally(BaseModel):
    hidden: Conditional


def test_a_field_the_model_does_not_declare_itself_is_unrepresentable() -> None:
    with pytest.raises(UndeclaredFieldError):
        _ = load(ModelTarget("pydantic_codegen.test_loader:Inherited"))


def test_a_name_the_module_neither_imports_nor_defines_is_unrepresentable() -> None:
    with pytest.raises(UnresolvableNameError):
        _ = load(ModelTarget("pydantic_codegen.test_loader:Conditionally"))


def test_a_target_without_a_class_is_malformed() -> None:
    with pytest.raises(MalformedTargetError):
        _ = load(ModelTarget("pydantic_codegen.test_corpus_subfolder"))
