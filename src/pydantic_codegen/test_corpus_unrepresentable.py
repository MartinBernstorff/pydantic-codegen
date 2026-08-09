from typing import TypeVar

import pytest
from pydantic import (
    BaseModel,
    RootModel,
    computed_field,
    create_model,
    field_validator,
    model_validator,
)

from pydantic_codegen.ir import Model, SymbolName
from pydantic_codegen.loader import (
    ComputedFieldError,
    RootModelSourceError,
    TypeParameterAnnotationError,
    UnboundTypeParameterError,
    UndeclaredFieldError,
    UndeclaredModelError,
    ValidatorError,
    load,
)


def _loaded(model: SymbolName) -> list[Model]:
    return load(f"pydantic_codegen.test_corpus_unrepresentable:{model.root}")


class UnparametrisedGeneric[Id](BaseModel):
    id: Id


def test_an_unbound_type_parameter_is_unrepresentable() -> None:
    with pytest.raises(UnboundTypeParameterError) as rejection:
        _ = _loaded(SymbolName("UnparametrisedGeneric"))

    message = str(rejection.value)
    assert "UnparametrisedGeneric" in message
    assert "Id" in message
    assert "parametrised alias" in message
    assert "concrete subclass" in message


class Name(RootModel[str]): ...


def test_a_root_model_is_unrepresentable_as_a_load_target() -> None:
    with pytest.raises(RootModelSourceError):
        _ = _loaded(SymbolName("Name"))


class FieldValidated(BaseModel):
    name: Name

    @field_validator("name")
    @classmethod
    def _stripped(cls, name: Name) -> Name:
        return Name(name.root.strip())


class ModelValidated(BaseModel):
    name: Name

    @model_validator(mode="after")
    def _named(self) -> "ModelValidated":
        return self


class InheritsAValidator(FieldValidated): ...


@pytest.mark.parametrize(
    "model",
    [
        SymbolName("FieldValidated"),
        SymbolName("ModelValidated"),
        SymbolName("InheritsAValidator"),
    ],
)
def test_a_validator_is_unrepresentable(model: SymbolName) -> None:
    with pytest.raises(ValidatorError):
        _ = _loaded(model)


class HasAComputedField(BaseModel):
    name: Name

    @computed_field
    @property
    def shouted(self) -> Name:
        return Name(self.name.root.upper())


def test_a_computed_field_is_unrepresentable() -> None:
    with pytest.raises(ComputedFieldError):
        _ = _loaded(SymbolName("HasAComputedField"))


Fabricated = create_model("Fabricated", name=(Name, ...))


def test_a_model_without_a_class_statement_is_unrepresentable() -> None:
    with pytest.raises(UndeclaredFieldError):
        _ = _loaded(SymbolName("Fabricated"))


FabricatedWithoutFields = create_model("FabricatedWithoutFields")


def test_a_fieldless_model_without_a_class_statement_is_unrepresentable() -> None:
    with pytest.raises(UndeclaredModelError):
        _ = _loaded(SymbolName("FabricatedWithoutFields"))


class BrandedAndValidated(RootModel[str]):
    @field_validator("root")
    @classmethod
    def _stripped(cls, root: str) -> str:
        return root.strip()


def test_a_root_model_is_rejected_before_its_validator() -> None:
    with pytest.raises(RootModelSourceError):
        _ = _loaded(SymbolName("BrandedAndValidated"))


Id = TypeVar("Id")


class AnnotatedWithATypeParameter(BaseModel):
    # Not generic, so only the free-name backstop can catch this.
    id: Id  # pyrefly: ignore


def test_a_field_annotated_with_a_type_parameter_is_unrepresentable() -> None:
    with pytest.raises(TypeParameterAnnotationError) as rejection:
        _ = _loaded(SymbolName("AnnotatedWithATypeParameter"))

    message = str(rejection.value)
    assert "AnnotatedWithATypeParameter" in message
    assert "Id" in message
    assert "parametrised alias" not in message
