import importlib
import inspect
from types import ModuleType

from iterpy import Arr
from pydantic import BaseModel, ConfigDict, RootModel

from pydantic_codegen.bindings import Bindings
from pydantic_codegen.ir import (
    Base,
    BaseName,
    Field,
    FieldName,
    FrozenText,
    Import,
    Model,
    ModelName,
    ModuleName,
    SymbolName,
)
from pydantic_codegen.module_source import module_source
from pydantic_codegen.rejections import (
    ComputedFieldError,
    RootModelSourceError,
    UndeclaredFieldError,
    UndeclaredModelError,
    UnparametrisedModelError,
    ValidatorError,
)


class ModelTarget(FrozenText): ...


class MalformedTargetError(Exception):
    def __init__(self, target: ModelTarget) -> None:
        super().__init__(
            f"{target.root} is not of the form 'module:Class' or "
            f"'module:Class[module:Argument, ...]'"
        )


class _Parsed(BaseModel):
    model_config = ConfigDict(frozen=True)

    origin: Import
    arguments: tuple["_Parsed", ...] = ()

    def written(self) -> BaseName:
        if not self.arguments:
            return BaseName(self.origin.bound_name().root)
        inside = ", ".join(
            Arr(self.arguments).map(lambda argument: argument.written().root).to_list()
        )
        return BaseName(f"{self.origin.bound_name().root}[{inside}]")

    def statements(self) -> tuple[Import, ...]:
        return (
            self.origin,
            *Arr(self.arguments)
            .map(lambda argument: argument.statements())
            .flatten()
            .to_list(),
        )


def _declaring_class(cls: type[BaseModel], name: FieldName) -> type:
    found = next(
        (
            entry
            for entry in cls.__mro__
            # Membership only, never a value: `inspect.get_annotations` would evaluate
            # them, which `from __future__ import annotations` makes unsafe.
            if name.root in entry.__dict__.get("__annotations__", {})  # noqa: RUF063
        ),
        None,
    )
    if found is None:
        raise UndeclaredFieldError(ModelName(cls.__name__), name)
    return found


def _own_fields(cls: type[BaseModel]) -> list[FieldName]:
    return (
        Arr(list(cls.model_fields))
        .map(FieldName)
        .filter(lambda name: _declaring_class(cls, name) is cls)
        .to_list()
    )


def _field(bindings: Bindings, name: FieldName) -> Field:
    owner = bindings.model
    declared = bindings.module.field_source(owner, name)
    if declared is None:
        raise UndeclaredFieldError(owner, name)
    return Field(
        name=name,
        annotation=declared.annotation,
        default=declared.default,
        imports=bindings.imports_for(declared.annotation)
        + (bindings.imports_for(declared.default) if declared.default else ()),
    )


def _bases(bindings: Bindings) -> tuple[BaseName, ...]:
    declared = bindings.module.bases_of(bindings.model)
    if declared is None:
        raise UndeclaredModelError(bindings.module.name, bindings.model)
    return declared


def _fields_of(module: ModuleType, name: SymbolName) -> tuple[FieldName, ...]:
    referenced = getattr(module, name.root, None)
    if not (isinstance(referenced, type) and issubclass(referenced, BaseModel)):
        return ()
    return tuple(Arr(list(referenced.model_fields)).map(FieldName).to_list())


def base_of(target: ModelTarget) -> Base:
    parsed = _parsed(target)
    module = importlib.import_module(parsed.origin.module.root)
    return Base(
        name=parsed.written(),
        fields=_fields_of(module, parsed.origin.bound_name()),
    )


def imports_of(target: ModelTarget) -> tuple[Import, ...]:
    return _parsed(target).statements()


def _model(cls: type[BaseModel]) -> Model:
    module: ModuleType = inspect.getmodule(cls)  # pyrefly: ignore
    owner = ModelName(cls.__name__)
    bindings = Bindings(module=module_source(module), model=owner)
    # Fields before bases: an undeclared field is the more precise rejection, and
    # reading the bases of a model with no class statement is what raises otherwise.
    fields = Arr(_own_fields(cls)).map(lambda name: _field(bindings, name)).to_list()
    bases = Arr(list(_bases(bindings)))
    return Model(
        name=owner,
        # A base kept from the source carries no fields for the gate to see: the
        # generated model declares only what its own body declares, so nothing is
        # declared twice.
        bases=tuple(bases.map(lambda base: Base(name=base)).to_list()),
        fields=tuple(fields),
        imports=tuple(bases.map(bindings.imports_for).flatten().to_list()),
    )


def imported(target: ModelTarget) -> Import:
    module_name, separator, class_name = target.root.partition(":")
    if not separator or not class_name.isidentifier():
        raise MalformedTargetError(target)
    return Import(module=ModuleName(module_name), name=SymbolName(class_name))


def _terms(inside: str) -> list[str]:
    terms = [""]
    depth = 0
    for character in inside:
        if character == "," and depth == 0:
            terms.append("")
            continue
        depth += {"[": 1, "]": -1}.get(character, 0)
        terms[-1] += character
    return [term.strip() for term in terms]


def _parsed(target: ModelTarget) -> _Parsed:
    head, bracket, inside = target.root.partition("[")
    if not bracket:
        return _Parsed(origin=imported(target))
    if not inside.endswith("]"):
        raise MalformedTargetError(target)
    return _Parsed(
        origin=imported(ModelTarget(head)),
        arguments=tuple(
            Arr(_terms(inside[:-1])).map(ModelTarget).map(_parsed).to_list()
        ),
    )


def _reject_unrepresentable(cls: type[BaseModel]) -> None:
    name = ModelName(cls.__name__)
    parameters = cls.__pydantic_generic_metadata__["parameters"]
    if parameters:
        raise UnparametrisedModelError(name, SymbolName(parameters[0].__name__))
    if issubclass(cls, RootModel):
        raise RootModelSourceError(name)
    decorators = cls.__pydantic_decorators__
    validators = list(decorators.field_validators) + list(decorators.model_validators)
    if validators:
        raise ValidatorError(name, SymbolName(validators[0]))
    computed = list(decorators.computed_fields)
    if computed:
        raise ComputedFieldError(name, FieldName(computed[0]))


def load(target: str) -> list[Model]:
    statement = imported(ModelTarget(target))
    module = importlib.import_module(statement.module.root)
    cls = getattr(module, statement.bound_name().root)
    _reject_unrepresentable(cls)
    return [_model(cls)]
