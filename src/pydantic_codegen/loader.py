import ast
import builtins
import importlib
import importlib.util
import inspect
from functools import cache
from types import ModuleType
from typing import TypeVar

from iterpy import Arr
from pydantic import BaseModel, RootModel

from pydantic_codegen.ir import (
    AnnotationText,
    Base,
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


def _guards_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


# A TYPE_CHECKING import is invisible at runtime, so the generated file must bind it
# for real; the same statement, hoisted out of the guard, is what does that.
def _deferred_imports(node: ast.stmt) -> list[ast.stmt]:
    if not isinstance(node, ast.If):
        return []
    return node.body if _guards_type_checking(node.test) else []


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

    def _statements(self) -> list[ast.stmt]:
        deferred = Arr(self.tree.body).map(_deferred_imports).flatten().to_list()
        return self.tree.body + deferred

    def _absolute(self, node: ast.ImportFrom) -> ModuleName:
        written = f"{'.' * node.level}{node.module or ''}"
        if node.level == 0:
            return ModuleName(written)
        return ModuleName(importlib.util.resolve_name(written, self.package.root))

    def _imports(self) -> Arr[Import]:
        plain = (
            Arr(self._statements())
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
            Arr(self._statements())
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
    def __init__(self, *, declaring: ParsedModule, model: ModelName) -> None:
        self.declaring = declaring
        self.model = model

    def import_of(self, name: SymbolName) -> Import:
        if name in self.declaring.type_parameters:
            raise TypeParameterAnnotationError(self.model, name)
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


def _own_fields(cls: type[BaseModel]) -> list[FieldName]:
    return (
        Arr(list(cls.model_fields))
        .map(FieldName)
        .filter(lambda name: _declaring_class(cls, name) is cls)
        .to_list()
    )


def _field(cls: type[BaseModel], name: FieldName) -> Field:
    declaring = _parsed_module(inspect.getmodule(cls))
    assign = _annotated_assign(declaring, ModelName(cls.__name__), name)
    source = NameSource(declaring=declaring, model=ModelName(cls.__name__))
    annotation = declaring.segment(assign.annotation)
    parsed = _parsed_expression(annotation)
    assigned = assign.value
    return Field(
        name=name,
        annotation=AnnotationText(annotation.root),
        default=DefaultText(declaring.segment(assigned).root) if assigned else None,
        imports=_imports_for(_annotation_names(parsed), source)  # pyrefly: ignore
        + (_imports_for(_plain_names(assigned), source) if assigned else ()),
    )


def _fields_of(module: ModuleType, name: SymbolName) -> tuple[FieldName, ...]:
    referenced = getattr(module, name.root, None)
    if not (isinstance(referenced, type) and issubclass(referenced, BaseModel)):
        return ()
    return tuple(Arr(list(referenced.model_fields)).map(FieldName).to_list())


# A base kept from the source carries no fields for the gate to see: the generated
# model declares only what its own body declares, so nothing is declared twice.
def _base(parsed: ParsedModule, node: ast.expr) -> Base:
    return Base(name=BaseName(parsed.segment(node).root))


def base_of(target: ModelTarget) -> Base:
    statement = imported(target)
    module = importlib.import_module(statement.module.root)
    return Base(
        name=BaseName(statement.bound_name().root),
        fields=_fields_of(module, statement.bound_name()),
    )


def _model(cls: type[BaseModel]) -> Model:
    module: ModuleType = inspect.getmodule(cls)  # pyrefly: ignore
    loaded = _parsed_module(module)
    owner = ModelName(cls.__name__)
    # Fields before bases: an undeclared field is the more precise rejection, and
    # reading the bases of a model with no class statement is what raises otherwise.
    fields = Arr(_own_fields(cls)).map(lambda name: _field(cls, name)).to_list()
    bases = Arr(loaded.class_bases(owner))
    source = NameSource(declaring=loaded, model=owner)
    return Model(
        name=owner,
        bases=tuple(bases.map(lambda base: _base(loaded, base)).to_list()),
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
