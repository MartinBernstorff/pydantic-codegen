import functools
import re
from collections.abc import Callable

from iterpy import Arr

from pydantic_codegen.ir import (
    AnnotationText,
    DefaultText,
    Field,
    FieldName,
    Import,
    Model,
    ModelName,
    ModuleName,
    SymbolName,
)
from pydantic_codegen.loader import ModelTarget, base_of, imported

Transformer = Callable[[list[Model]], list[Model]]


class UnknownFieldError(Exception):
    def __init__(self, model: Model, name: FieldName) -> None:
        declared = ", ".join(field.name.root for field in model.fields)
        super().__init__(
            f"{model.name.root} has no field {name.root}; it has {declared}"
        )


def pipe(models: list[Model], *transformers: Transformer) -> list[Model]:
    def applied(carried: list[Model], step: Transformer) -> list[Model]:
        return step(carried)

    return functools.reduce(applied, transformers, models)


def each(transform: Callable[[Model], list[Model]]) -> Transformer:
    return lambda models: Arr(models).map(transform).flatten().to_list()


def _with_fields(model: Model, fields: Arr[Field]) -> list[Model]:
    return [model.model_copy(update={"fields": tuple(fields.to_list())})]


def _selected(model: Model, names: tuple[str, ...]) -> set[FieldName]:
    declared = {field.name for field in model.fields}
    selected = Arr(names).map(FieldName)
    unknown = selected.filter(lambda name: name not in declared).to_list()
    if unknown:
        raise UnknownFieldError(model, unknown[0])
    return set(selected.to_list())


class DeclaredFieldError(Exception):
    def __init__(self, model: Model, name: FieldName) -> None:
        super().__init__(
            f"{model.name.root} already declares {name.root}; adding it would declare "
            f"it a second time"
        )


def add_field(
    name: str, annotation: str, default: str | None = None, *imports: str
) -> Transformer:
    added = Field(
        name=FieldName(name),
        annotation=AnnotationText(annotation),
        default=None if default is None else DefaultText(default),
        imports=tuple(Arr(imports).map(ModelTarget).map(imported).to_list()),
    )

    def appended(model: Model) -> list[Model]:
        if any(field.name == added.name for field in model.fields):
            raise DeclaredFieldError(model, added.name)
        return _with_fields(model, Arr(model.fields).chain(Arr([added])))

    return each(appended)


def omit(*names: str) -> Transformer:
    def dropped(model: Model) -> list[Model]:
        selected = _selected(model, names)
        return _with_fields(
            model, Arr(model.fields).filter(lambda field: field.name not in selected)
        )

    return each(dropped)


def pick(*names: str) -> Transformer:
    def kept(model: Model) -> list[Model]:
        selected = _selected(model, names)
        return _with_fields(
            model, Arr(model.fields).filter(lambda field: field.name in selected)
        )

    return each(kept)


def _widened(annotation: AnnotationText, token: SymbolName) -> AnnotationText:
    # Bracketed groups are erased before splitting, so the None in
    # `Callable[[int], None]` does not read as a top-level term.
    outermost = annotation.root
    while True:
        collapsed = re.sub(r"\[[^\[\]]*\]|\([^()]*\)", "", outermost)
        if collapsed == outermost:
            break
        outermost = collapsed
    if any(term.strip() == token.root for term in outermost.split("|")):
        return annotation
    return AnnotationText(f"{annotation.root} | {token.root}")


def each_field(transform: Callable[[Field], list[Field]]) -> Transformer:
    return each(
        lambda model: _with_fields(model, Arr(model.fields).map(transform).flatten())
    )


def partial_sentinel() -> Transformer:
    sentinel = Import(
        module=ModuleName("pydantic.experimental.missing_sentinel"),
        name=SymbolName("MISSING"),
    )

    token = sentinel.bound_name()

    def widened(field: Field) -> list[Field]:
        annotation = _widened(field.annotation, token)
        if annotation == field.annotation:
            return [field]
        return [
            field.model_copy(
                update={
                    "annotation": annotation,
                    "default": DefaultText(token.root),
                    "imports": (*field.imports, sentinel),
                }
            )
        ]

    return each_field(widened)


def partial_none() -> Transformer:
    token = SymbolName("None")

    # An annotation that is already optional needs the default added, not a second
    # | None appended.
    def widened(field: Field) -> list[Field]:
        return [
            field.model_copy(
                update={
                    "annotation": _widened(field.annotation, token),
                    "default": DefaultText(token.root),
                }
            )
        ]

    return each_field(widened)


def set_bases(*targets: str) -> Transformer:
    parsed = Arr(targets).map(ModelTarget).to_list()
    statements = tuple(Arr(parsed).map(imported).to_list())
    bases = tuple(Arr(parsed).map(base_of).to_list())
    return each(
        lambda model: [model.model_copy(update={"bases": bases, "imports": statements})]
    )


class AmbiguousRenameError(Exception):
    def __init__(self, name: ModelName) -> None:
        super().__init__(
            f"renaming several models to {name.root} produces duplicate class definitions"
        )


def rename_model(name: str | Callable[[str], str]) -> Transformer:
    if callable(name):
        return each(
            lambda model: [
                model.model_copy(update={"name": ModelName(name(model.name.root))})
            ]
        )

    def renamed(models: list[Model]) -> list[Model]:
        if len(models) > 1:
            raise AmbiguousRenameError(ModelName(name))
        return [model.model_copy(update={"name": ModelName(name)}) for model in models]

    return renamed
