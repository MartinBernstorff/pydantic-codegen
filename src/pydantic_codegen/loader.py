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
        super().__init__(f"{model.root} does not declare {field.root} itself")


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
    if name in parsed.type_parameters:
        raise TypeParameterAnnotationError(owner, name)
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


def _fields_of(module: ModuleType, path: SymbolName) -> tuple[FieldName, ...]:
    referenced: object = module
    for step in path.root.split("."):
        referenced = getattr(referenced, step, None)
    if not (isinstance(referenced, type) and issubclass(referenced, BaseModel)):
        return ()
    return tuple(Arr(list(referenced.model_fields)).map(FieldName).to_list())


def _base(parsed: ParsedModule, module: ModuleType, node: ast.expr) -> Base:
    root = node.value if isinstance(node, ast.Subscript) else node
    return Base(
        name=BaseName(parsed.segment(node).root),
        fields=_fields_of(module, SymbolName(parsed.segment(root).root)),
    )


def base_of(target: ModelTarget) -> Base:
    statement = imported(target)
    module = importlib.import_module(statement.module.root)
    return Base(
        name=BaseName(statement.bound_name().root),
        fields=_fields_of(module, statement.bound_name()),
    )


def _model(cls: type[BaseModel]) -> Model:
    module: ModuleType = inspect.getmodule(cls)  # pyrefly: ignore
    parsed = ParsedModule(module)
    owner = ModelName(cls.__name__)
    # Fields before bases: an undeclared field is the more precise rejection, and
    # reading the bases of a model with no class statement is what raises otherwise.
    fields = (
        Arr(list(cls.model_fields))
        .map(lambda name: _field(parsed, owner, FieldName(name)))
        .to_list()
    )
    bases = Arr(parsed.class_bases(owner))
    return Model(
        name=owner,
        bases=tuple(bases.map(partial(_base, parsed, module)).to_list()),
        fields=tuple(fields),
        imports=tuple(
            bases.map(lambda base: _imports_for(base, parsed, owner))
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
