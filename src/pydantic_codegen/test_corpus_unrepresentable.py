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

from pydantic_codegen.ir import SymbolName
from pydantic_codegen.loader import (
    ComputedFieldError,
    ModelTarget,
    RootModelSourceError,
    TypeParameterAnnotationError,
    UnboundTypeParameterError,
    UndeclaredFieldError,
    UndeclaredModelError,
    ValidatorError,
    load,
)


def target(model: SymbolName) -> ModelTarget:
    return ModelTarget(f"pydantic_codegen.test_corpus_unrepresentable:{model.root}")


class UnparametrisedGeneric[Id](BaseModel):
    id: Id


def test_an_unbound_type_parameter_is_unrepresentable() -> None:
    with pytest.raises(UnboundTypeParameterError) as rejection:
        _ = load(target(SymbolName("UnparametrisedGeneric")))

    message = str(rejection.value)
    assert "UnparametrisedGeneric" in message
    assert "Id" in message
    assert "parametrised alias" in message
    assert "concrete subclass" in message


class Name(RootModel[str]): ...


def test_a_root_model_is_unrepresentable_as_a_load_target() -> None:
    with pytest.raises(RootModelSourceError):
        _ = load(target(SymbolName("Name")))


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
        _ = load(target(model))


class HasAComputedField(BaseModel):
    name: Name

    @computed_field
    @property
    def shouted(self) -> Name:
        return Name(self.name.root.upper())


def test_a_computed_field_is_unrepresentable() -> None:
    with pytest.raises(ComputedFieldError):
        _ = load(target(SymbolName("HasAComputedField")))


Fabricated = create_model("Fabricated", name=(Name, ...))


def test_a_model_without_a_class_statement_is_unrepresentable() -> None:
    with pytest.raises(UndeclaredFieldError):
        _ = load(target(SymbolName("Fabricated")))


FabricatedWithoutFields = create_model("FabricatedWithoutFields")


def test_a_fieldless_model_without_a_class_statement_is_unrepresentable() -> None:
    with pytest.raises(UndeclaredModelError):
        _ = load(target(SymbolName("FabricatedWithoutFields")))


class BrandedAndValidated(RootModel[str]):
    @field_validator("root")
    @classmethod
    def _stripped(cls, root: str) -> str:
        return root.strip()


def test_a_root_model_is_rejected_before_its_validator() -> None:
    with pytest.raises(RootModelSourceError):
        _ = load(target(SymbolName("BrandedAndValidated")))


Id = TypeVar("Id")


class AnnotatedWithATypeParameter(BaseModel):
    # Not generic, so only the free-name backstop can catch this.
    id: Id  # pyrefly: ignore


def test_a_field_annotated_with_a_type_parameter_is_unrepresentable() -> None:
    with pytest.raises(TypeParameterAnnotationError) as rejection:
        _ = load(target(SymbolName("AnnotatedWithATypeParameter")))

    message = str(rejection.value)
    assert "AnnotatedWithATypeParameter" in message
    assert "Id" in message
    assert "parametrised alias" not in message
