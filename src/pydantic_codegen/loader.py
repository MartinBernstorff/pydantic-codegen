import ast
import builtins
import importlib
import inspect
from functools import partial
from types import ModuleType
from typing import TypeVar

from iterpy import Arr
from pydantic import BaseModel, RootModel

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


class UnboundTypeParameterError(UnrepresentableError):
    def __init__(self, model: ModelName, parameter: SymbolName) -> None:
        super().__init__(
            f"{model.root} leaves the type parameter {parameter.root} unbound; "
            f"load a parametrised alias or a concrete subclass instead"
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
        super().__init__(f"{model.root} does not declare {field.root} itself")


class UnresolvableNameError(UnrepresentableError):
    def __init__(self, module: ModuleName, name: SymbolName) -> None:
        super().__init__(f"{module.root} neither imports nor defines {name.root}")


class ParsedModule:
    def __init__(self, module: ModuleType) -> None:
        self.module = module
        self.name = ModuleName(module.__name__)
        self.source = PythonSource(inspect.getsource(module))
        self.tree = ast.parse(self.source.root)

    def segment(self, node: ast.expr) -> PythonSource:
        return PythonSource(ast.get_source_segment(self.source.root, node) or "")

    def class_body(self, name: ModelName) -> list[ast.stmt]:
        definition = self._class_def(name)
        return definition.body if definition else []

    def class_bases(self, name: ModelName) -> list[ast.expr]:
        definition = self._class_def(name)
        return definition.bases if definition else []

    def _class_def(self, name: ModelName) -> ast.ClassDef | None:
        return next(
            (
                node
                for node in self.tree.body
                if isinstance(node, ast.ClassDef) and node.name == name.root
            ),
            None,
        )

    def type_parameters(self) -> set[SymbolName]:
        return {
            SymbolName(name)
            for name, bound in vars(self.module).items()
            if isinstance(bound, TypeVar)
        }

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
            .filter(lambda node: isinstance(node, ast.ImportFrom) and node.level == 0)
            .map(
                lambda node: [
                    Import(
                        module=ModuleName(node.module or ""),  # pyrefly: ignore
                        name=SymbolName(alias.name),
                        alias=SymbolName(alias.asname) if alias.asname else None,
                    )
                    for alias in node.names  # pyrefly: ignore
                ]
            )
            .flatten()
        )
        return plain.chain(from_module)


def _free_names(node: ast.expr) -> Arr[SymbolName]:
    return (
        Arr(list(ast.walk(node)))
        .filter(lambda inner: isinstance(inner, ast.Name))
        .map(lambda inner: SymbolName(inner.id))  # pyrefly: ignore
        .filter(lambda name: not hasattr(builtins, name.root))
        .unique()
    )


def _resolve(parsed: ParsedModule, owner: ModelName, name: SymbolName) -> Import:
    if name in parsed.type_parameters():
        raise UnboundTypeParameterError(owner, name)
    return parsed.import_of(name)


def _imports_for(
    node: ast.expr, parsed: ParsedModule, owner: ModelName
) -> tuple[Import, ...]:
    return tuple(_free_names(node).map(partial(_resolve, parsed, owner)).to_list())


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


def _field(parsed: ParsedModule, owner: ModelName, name: FieldName) -> Field:
    assign = _annotated_assign(parsed, owner, name)
    assigned = assign.value
    return Field(
        name=name,
        annotation=AnnotationText(parsed.segment(assign.annotation).root),
        default=DefaultText(parsed.segment(assigned).root) if assigned else None,
        imports=_imports_for(assign.annotation, parsed, owner)
        + (_imports_for(assigned, parsed, owner) if assigned else ()),
    )


def _model(cls: type[BaseModel]) -> Model:
    parsed = ParsedModule(inspect.getmodule(cls))  # pyrefly: ignore
    owner = ModelName(cls.__name__)
    bases = Arr(parsed.class_bases(owner))
    return Model(
        name=owner,
        bases=tuple(
            bases.map(lambda base: BaseName(parsed.segment(base).root)).to_list()
        ),
        fields=tuple(
            Arr(list(cls.model_fields))
            .map(lambda name: _field(parsed, owner, FieldName(name)))
            .to_list()
        ),
        imports=tuple(
            bases.map(lambda base: _imports_for(base, parsed, owner))
            .flatten()
            .to_list()
        ),
    )


def _reject_unrepresentable(cls: type[BaseModel]) -> None:
    name = ModelName(cls.__name__)
    parameters = cls.__pydantic_generic_metadata__["parameters"]
    if parameters:
        raise UnboundTypeParameterError(name, SymbolName(parameters[0].__name__))
    if issubclass(cls, RootModel):
        raise RootModelSourceError(name)
    decorators = cls.__pydantic_decorators__
    validators = list(decorators.field_validators) + list(decorators.model_validators)
    if validators:
        raise ValidatorError(name, SymbolName(validators[0]))
    computed = list(decorators.computed_fields)
    if computed:
        raise ComputedFieldError(name, FieldName(computed[0]))


def load(target: ModelTarget) -> Arr[Model]:
    module_name, separator, class_name = target.root.partition(":")
    if not separator:
        raise MalformedTargetError(target)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    _reject_unrepresentable(cls)
    return Arr([_model(cls)])
