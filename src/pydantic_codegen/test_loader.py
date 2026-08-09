import pytest
from pydantic import BaseModel
from pydantic.fields import FieldInfo

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
    UnboundTypeParameterError,
    UndeclaredFieldError,
    UnnameableArgumentError,
    UnresolvableNameError,
    load,
)
from pydantic_codegen.test_corpus_asset_location import FolderId


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


def test_a_relative_import_is_absolute_in_the_ir() -> None:
    loaded = load(ModelTarget("pydantic_codegen.test_corpus_inheriting:Record"))

    assert loaded.to_list()[0].imports == (
        Import(
            module=ModuleName("pydantic_codegen.test_corpus_stamping"),
            name=SymbolName("Stamped"),
        ),
    )


@pytest.mark.parametrize(
    ("target", "field"),
    [
        (
            ModelTarget("pydantic_codegen.test_corpus_bound_names:Sorted"),
            FieldName("tags"),
        ),
        (
            ModelTarget("pydantic_codegen.test_corpus_bound_names:Comprehended"),
            FieldName("tags"),
        ),
    ],
)
def test_a_name_bound_inside_the_expression_needs_no_import(
    target: ModelTarget, field: FieldName
) -> None:
    loaded = load(target)

    imported = {
        statement.bound_name()
        for declared in loaded.to_list()[0].fields
        if declared.name == field
        for statement in declared.imports
    }
    assert imported <= {SymbolName("Field"), SymbolName("Tag")}


def _injecting_a_field(model: type[BaseModel]) -> type[BaseModel]:
    model.model_fields["ghost"] = FieldInfo(annotation=int)
    return model


@_injecting_a_field
class Injected(BaseModel):
    known: FolderId


# Hidden from a top-level scan of the module's imports, but bound at runtime.
try:
    from decimal import Decimal as Conditional
except ImportError as missing:  # pragma: no cover
    raise RuntimeError from missing


class Conditionally(BaseModel):
    hidden: Conditional


def test_a_field_no_class_in_the_mro_declares_is_unrepresentable() -> None:
    with pytest.raises(UndeclaredFieldError, match="ghost"):
        _ = load(ModelTarget("pydantic_codegen.test_loader:Injected"))


def test_an_unbound_type_parameter_is_unrepresentable() -> None:
    with pytest.raises(UnboundTypeParameterError):
        _ = load(ModelTarget("pydantic_codegen.test_corpus_generic:Identified"))


def test_a_type_parameter_bound_to_more_than_a_bare_name_is_unrepresentable() -> None:
    with pytest.raises(UnnameableArgumentError):
        _ = load(ModelTarget("pydantic_codegen.test_corpus_parametrised:Listed"))


def test_a_name_the_module_neither_imports_nor_defines_is_unrepresentable() -> None:
    with pytest.raises(UnresolvableNameError):
        _ = load(ModelTarget("pydantic_codegen.test_loader:Conditionally"))


def test_a_target_without_a_class_is_malformed() -> None:
    with pytest.raises(MalformedTargetError):
        _ = load(ModelTarget("pydantic_codegen.test_corpus_subfolder"))
