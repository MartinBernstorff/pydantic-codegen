import ast
import builtins
import importlib
import importlib.util
import inspect
import re
from functools import cache, reduce
from types import ModuleType
from typing import TypeVar

from iterpy import Arr
from pydantic import BaseModel, ConfigDict, RootModel

from pydantic_codegen.ir import (
    AnnotationText,
    BaseName,
    DefaultText,
    Field,
    FieldName,
    FrozenText,
    Import,
    Model,
    ModelName,
    ModuleName,
    SymbolName,
)
from pydantic_codegen.python_source import PythonSource


class ModelTarget(FrozenText): ...


class MalformedTargetError(Exception):
    def __init__(self, target: ModelTarget) -> None:
        super().__init__(f"{target.root} is not of the form 'module:Class'")


class UnrepresentableError(Exception): ...


class UnboundTypeParameterError(UnrepresentableError): ...


class UnparametrisedModelError(UnboundTypeParameterError):
    def __init__(self, model: ModelName, parameter: SymbolName) -> None:
        super().__init__(
            f"{model.root} leaves the type parameter {parameter.root} unbound; "
            f"load a parametrised alias or a concrete subclass instead"
        )


class TypeParameterAnnotationError(UnboundTypeParameterError):
    def __init__(self, model: ModelName, parameter: SymbolName) -> None:
        super().__init__(
            f"{model.root} annotates a field with the type parameter "
            f"{parameter.root}, which stands for no concrete type"
        )


class RootModelSourceError(UnrepresentableError):
    def __init__(self, model: ModelName) -> None:
        super().__init__(
            f"{model.root} is a RootModel, which has a root rather than fields"
        )


class ValidatorError(UnrepresentableError):
    def __init__(self, model: ModelName, validator: SymbolName) -> None:
        super().__init__(f"{model.root} validates through {validator.root}")


class ComputedFieldError(UnrepresentableError):
    def __init__(self, model: ModelName, field: FieldName) -> None:
        super().__init__(f"{model.root} computes {field.root} rather than declaring it")


class UndeclaredFieldError(UnrepresentableError):
    def __init__(self, model: ModelName, field: FieldName) -> None:
        super().__init__(f"no class in the MRO of {model.root} declares {field.root}")


class UndeclaredModelError(UnrepresentableError):
    def __init__(self, module: ModuleName, model: ModelName) -> None:
        super().__init__(
            f"{module.root} holds no class statement for {model.root}, "
            f"so there is no source to read its bases and fields from"
        )


class UnresolvableNameError(UnrepresentableError):
    def __init__(self, module: ModuleName, name: SymbolName) -> None:
        super().__init__(f"{module.root} neither imports nor defines {name.root}")


class UnnameableArgumentError(UnrepresentableError):
    def __init__(self, model: ModelName, name: SymbolName) -> None:
        super().__init__(
            f"{model.root} binds a type parameter to {name.root}, which "
            "substitution can only write as a bare name"
        )


class ParsedModule:
    def __init__(self, module: ModuleType) -> None:
        self.name = ModuleName(module.__name__)
        self.package = ModuleName(module.__package__ or "")
        self.source = PythonSource(inspect.getsource(module))
        self.tree = ast.parse(self.source.root)
        self.type_parameters = {
            SymbolName(bound_name)
            for bound_name, bound in vars(module).items()
            if isinstance(bound, TypeVar)
        }

    def segment(self, node: ast.expr) -> PythonSource:
        return PythonSource(ast.get_source_segment(self.source.root, node) or "")

    def class_body(self, name: ModelName) -> list[ast.stmt]:
        definition = self._class_def(name)
        return definition.body if definition else []

    def class_bases(self, name: ModelName) -> list[ast.expr]:
        definition = self._class_def(name)
        if definition is None:
            raise UndeclaredModelError(self.name, name)
        return definition.bases

    def _class_def(self, name: ModelName) -> ast.ClassDef | None:
        return next(
            (
                node
                for node in self.tree.body
                if isinstance(node, ast.ClassDef) and node.name == name.root
            ),
            None,
        )

    def import_of(self, name: SymbolName) -> Import:
        bound = {
            statement.bound_name(): statement for statement in self._imports().to_list()
        }
        if name in bound:
            return bound[name]
        if name in self._defined_names():
            return Import(module=self.name, name=name)
        raise UnresolvableNameError(self.name, name)

    def _defined_names(self) -> set[SymbolName]:
        declarations = {
            SymbolName(node.name)
            for node in self.tree.body
            if isinstance(node, ast.ClassDef | ast.FunctionDef)
        }
        assignments = {
            SymbolName(target.id)
            for node in self.tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        return declarations | assignments

    def _absolute(self, node: ast.ImportFrom) -> ModuleName:
        written = f"{'.' * node.level}{node.module or ''}"
        if node.level == 0:
            return ModuleName(written)
        return ModuleName(importlib.util.resolve_name(written, self.package.root))

    def _imports(self) -> Arr[Import]:
        plain = (
            Arr(self.tree.body)
            .filter(lambda node: isinstance(node, ast.Import))
            .map(lambda node: node.names)  # pyrefly: ignore
            .flatten()
            .map(
                lambda alias: Import(
                    module=ModuleName(alias.name),
                    alias=SymbolName(alias.asname) if alias.asname else None,
                )
            )
        )
        from_module = (
            Arr(self.tree.body)
            .filter(lambda node: isinstance(node, ast.ImportFrom))
            .map(
                lambda node: [
                    Import(
                        module=self._absolute(node),  # pyrefly: ignore
                        name=SymbolName(alias.name),
                        alias=SymbolName(alias.asname) if alias.asname else None,
                    )
                    for alias in node.names  # pyrefly: ignore
                ]
            )
            .flatten()
        )
        return plain.chain(from_module)


class NameSource:
    def __init__(
        self,
        *,
        declaring: ParsedModule,
        loaded: ParsedModule,
        model: ModelName,
        substituted: frozenset[SymbolName] = frozenset(),
        unbound: frozenset[SymbolName] = frozenset(),
    ) -> None:
        self.declaring = declaring
        self.loaded = loaded
        self.model = model
        self.substituted = substituted
        self.unbound = unbound

    def import_of(self, name: SymbolName) -> Import:
        if name in self.unbound or name in self.declaring.type_parameters:
            raise TypeParameterAnnotationError(self.model, name)
        if name in self.substituted:
            return self.loaded.import_of(name)
        return self.declaring.import_of(name)


def _bound_names(node: ast.expr) -> set[SymbolName]:
    inner = list(ast.walk(node))
    arguments = {
        SymbolName(argument.arg)
        for lambda_ in inner
        if isinstance(lambda_, ast.Lambda)
        for argument in [
            *lambda_.args.posonlyargs,
            *lambda_.args.args,
            *lambda_.args.kwonlyargs,
            *([lambda_.args.vararg] if lambda_.args.vararg else []),
            *([lambda_.args.kwarg] if lambda_.args.kwarg else []),
        ]
    }
    targets = {
        SymbolName(name.id)
        for generator in inner
        if isinstance(generator, ast.comprehension)
        for name in ast.walk(generator.target)
        if isinstance(name, ast.Name)
    }
    return arguments | targets


def _plain_names(node: ast.expr) -> Arr[SymbolName]:
    bound = _bound_names(node)
    return (
        Arr(list(ast.walk(node)))
        .filter(lambda inner: isinstance(inner, ast.Name))
        .map(lambda inner: SymbolName(inner.id))  # pyrefly: ignore
        .filter(lambda name: not hasattr(builtins, name.root))
        .filter(lambda name: name not in bound)
        .unique()
    )


def _parsed_expression(source: PythonSource) -> ast.expr | None:
    try:
        return ast.parse(source.root, mode="eval").body
    except SyntaxError:
        return None


def _forward_refs(node: ast.expr) -> list[ast.expr]:
    # A string inside a call is metadata — Field(description="…") — never a forward ref.
    if isinstance(node, ast.Call):
        return []
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, str):
            return []
        parsed = _parsed_expression(PythonSource(node.value))
        return [parsed] if parsed else []
    return [
        reference
        for child in ast.iter_child_nodes(node)
        if isinstance(child, ast.expr)
        for reference in _forward_refs(child)
    ]


def _annotation_names(node: ast.expr) -> Arr[SymbolName]:
    return (
        _plain_names(node)
        .chain(Arr(_forward_refs(node)).map(_annotation_names).flatten())
        .unique()
    )


class Substitution(BaseModel):
    model_config = ConfigDict(frozen=True)

    parameter: SymbolName
    argument: SymbolName


def _applied(text: PythonSource, substitution: Substitution) -> PythonSource:
    return PythonSource(
        re.sub(
            rf"\b{re.escape(substitution.parameter.root)}\b",
            substitution.argument.root,
            text.root,
        )
    )


def _substituted(text: PythonSource, pairs: Arr[Substitution]) -> PythonSource:
    return reduce(_applied, pairs.to_list(), text)


def _models_in_mro(cls: type[BaseModel]) -> list[type[BaseModel]]:
    return [
        entry
        for entry in cls.__mro__
        if isinstance(entry, type)
        and issubclass(entry, BaseModel)
        # BaseModel itself declares the attribute but does not carry it.
        and hasattr(entry, "__pydantic_generic_metadata__")
    ]


def _argument_name(model: ModelName, argument: type) -> SymbolName:
    if not isinstance(argument, type):
        raise UnnameableArgumentError(model, SymbolName(str(argument)))
    return SymbolName(argument.__name__)


def _parametrised(model: ModelName, entry: type[BaseModel]) -> Arr[Substitution]:
    metadata = entry.__pydantic_generic_metadata__
    origin = metadata["origin"]
    if origin is None:
        return Arr([])
    return Arr(
        [
            Substitution(
                parameter=SymbolName(parameter.__name__),
                argument=_argument_name(model, argument),
            )
            for parameter, argument in zip(
                origin.__pydantic_generic_metadata__["parameters"],
                metadata["args"],
                strict=False,
            )
        ]
    )


def _substitutions(cls: type[BaseModel]) -> Arr[Substitution]:
    model = ModelName(cls.__name__)
    return (
        Arr(_models_in_mro(cls))
        .map(lambda entry: _parametrised(model, entry))
        .flatten()
    )


def _parameters(cls: type[BaseModel]) -> set[SymbolName]:
    return {
        SymbolName(parameter.__name__)
        for entry in _models_in_mro(cls)
        for parameter in entry.__pydantic_generic_metadata__["parameters"]
    }


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


@cache
def _parsed_module(module: ModuleType) -> ParsedModule:
    return ParsedModule(module)


def _annotated_assign(
    parsed: ParsedModule, owner: ModelName, name: FieldName
) -> ast.AnnAssign:
    assign = next(
        (
            node
            for node in parsed.class_body(owner)
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name.root
        ),
        None,
    )
    if assign is None:
        raise UndeclaredFieldError(owner, name)
    return assign


def _imports_for(names: Arr[SymbolName], source: NameSource) -> tuple[Import, ...]:
    return tuple(names.map(source.import_of).to_list())


def _field(cls: type[BaseModel], name: FieldName) -> Field:
    declaring_class = _declaring_class(cls, name)
    declaring = _parsed_module(inspect.getmodule(declaring_class))
    assign = _annotated_assign(declaring, ModelName(declaring_class.__name__), name)
    pairs = _substitutions(cls)
    source = NameSource(
        declaring=declaring,
        loaded=_parsed_module(inspect.getmodule(cls)),
        model=ModelName(cls.__name__),
        substituted=frozenset(pairs.map(lambda pair: pair.argument).to_list()),
        unbound=frozenset(
            _parameters(cls) - set(pairs.map(lambda pair: pair.parameter))
        ),
    )
    annotation = _substituted(declaring.segment(assign.annotation), pairs)
    parsed = _parsed_expression(annotation)
    assigned = assign.value
    return Field(
        name=name,
        annotation=AnnotationText(annotation.root),
        default=DefaultText(declaring.segment(assigned).root) if assigned else None,
        imports=_imports_for(_annotation_names(parsed), source)  # pyrefly: ignore
        + (_imports_for(_plain_names(assigned), source) if assigned else ()),
    )


def _model(cls: type[BaseModel]) -> Model:
    loaded = _parsed_module(inspect.getmodule(cls))
    owner = ModelName(cls.__name__)
    # Fields before bases: an undeclared field is the more precise rejection, and
    # reading the bases of a model with no class statement is what raises otherwise.
    fields = (
        Arr(list(cls.model_fields))
        .map(lambda name: _field(cls, FieldName(name)))
        .to_list()
    )
    bases = Arr(loaded.class_bases(owner))
    source = NameSource(declaring=loaded, loaded=loaded, model=owner)
    return Model(
        name=owner,
        bases=tuple(
            bases.map(lambda base: BaseName(loaded.segment(base).root)).to_list()
        ),
        fields=tuple(fields),
        imports=tuple(
            bases.map(lambda base: _imports_for(_plain_names(base), source))
            .flatten()
            .to_list()
        ),
    )


def imported(target: ModelTarget) -> Import:
    module_name, separator, class_name = target.root.partition(":")
    if not separator:
        raise MalformedTargetError(target)
    return Import(module=ModuleName(module_name), name=SymbolName(class_name))


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
