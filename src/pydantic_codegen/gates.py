from pathlib import Path

from iterpy import Arr
from pydantic import BaseModel, ConfigDict

from pydantic_codegen.ir import (
    Base,
    FieldName,
    FrozenText,
    Import,
    Model,
    ModelName,
    SymbolName,
)
from pydantic_codegen.renderer import rendered_import


class RequirerName(FrozenText): ...


class Requirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    statement: Import
    requirer: RequirerName


class EmptyFileError(Exception):
    def __init__(self, path: Path) -> None:
        super().__init__(f"{path} holds no models")


class DuplicatePathError(Exception):
    def __init__(self, path: Path) -> None:
        super().__init__(f"two files write to {path}; one would discard the other")


class DuplicateModelError(Exception):
    def __init__(self, name: ModelName) -> None:
        super().__init__(f"two models in this file are named {name.root}")


class ImportCollisionError(Exception):
    def __init__(self, first: Requirement, second: Requirement) -> None:
        super().__init__(
            f"{first.statement.bound_name().root} is bound by two different imports: "
            f"'{rendered_import(first.statement).root}' required by {first.requirer.root}, "
            f"and '{rendered_import(second.statement).root}' required by {second.requirer.root}; "
            f"alias one of them in the module it is defined in"
        )


class ShadowedImportError(Exception):
    def __init__(self, requirement: Requirement) -> None:
        super().__init__(
            f"{requirement.statement.bound_name().root} is generated in this file, so "
            f"the import required by {requirement.requirer.root} would be shadowed by it"
        )


class RedeclaredBaseFieldError(Exception):
    def __init__(self, model: ModelName, base: Base, field: FieldName) -> None:
        super().__init__(
            f"{model.root} declares {field.root}, which its base {base.name.root} "
            f"already declares; the generated declaration silently overrides the "
            f"base's, so omit {field.root} or drop the base"
        )


def _first_repeat[T](keys: list[T]) -> T | None:
    return next((key for index, key in enumerate(keys) if key in keys[:index]), None)


def reject_duplicate_paths(paths: list[Path]) -> None:
    repeated = _first_repeat(paths)
    if repeated is not None:
        raise DuplicatePathError(repeated)


def _reject_duplicate_models(models: list[Model]) -> None:
    repeated = _first_repeat(Arr(models).map(lambda model: model.name).to_list())
    if repeated is not None:
        raise DuplicateModelError(repeated)


def _requirements(models: list[Model]) -> list[Requirement]:
    def of_fields(model: Model) -> list[Requirement]:
        return [
            Requirement(
                statement=statement,
                requirer=RequirerName(f"{model.name.root}.{field.name.root}"),
            )
            for field in model.fields
            for statement in field.imports
        ]

    def of_bases(model: Model) -> list[Requirement]:
        return [
            Requirement(
                statement=statement,
                requirer=RequirerName(f"the bases of {model.name.root}"),
            )
            for statement in model.imports
        ]

    return (
        Arr(models)
        .map(of_fields)
        .flatten()
        .chain(Arr(models).map(of_bases).flatten())
        .to_list()
    )


def _reject_import_collisions(requirements: list[Requirement]) -> None:
    bound: dict[SymbolName, Requirement] = {}
    for requirement in requirements:
        first = bound.setdefault(requirement.statement.bound_name(), requirement)
        if first.statement != requirement.statement:
            raise ImportCollisionError(first, requirement)


def _reject_shadowed_imports(
    requirements: list[Requirement], models: list[Model]
) -> None:
    generated = {SymbolName(model.name.root) for model in models}
    shadowed = (
        Arr(requirements)
        .filter(lambda requirement: requirement.statement.bound_name() in generated)
        .to_list()
    )
    if shadowed:
        raise ShadowedImportError(shadowed[0])


def _reject_redeclared_base_fields(models: list[Model]) -> None:
    def of_model(model: Model) -> list[tuple[ModelName, Base, FieldName]]:
        declared = {field.name for field in model.fields}
        return [
            (model.name, base, name)
            for base in model.bases
            for name in base.fields
            if name in declared
        ]

    redeclared = Arr(models).map(of_model).flatten().to_list()
    if redeclared:
        raise RedeclaredBaseFieldError(*redeclared[0])


def reject_unwritable(path: Path, models: Arr[Model]) -> None:
    declared = models.to_list()
    if not declared:
        raise EmptyFileError(path)
    _reject_duplicate_models(declared)
    _reject_redeclared_base_fields(declared)
    requirements = _requirements(declared)
    _reject_import_collisions(requirements)
    _reject_shadowed_imports(requirements, declared)
