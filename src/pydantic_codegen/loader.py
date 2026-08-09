import ast
import builtins
import importlib
import inspect
from types import ModuleType

from iterpy import Arr
from pydantic import BaseModel, ConfigDict, RootModel

from pydantic_codegen.ir import (
    AnnotationText,
    BaseName,
    DefaultText,
    Field,
    FieldName,
    Import,
    Model,
    ModelName,
    ModuleName,
    SymbolName,
)
from pydantic_codegen.python_source import PythonSource


class ModelTarget(RootModel[str]):
    model_config = ConfigDict(frozen=True)


class UnrepresentableError(Exception): ...


class UndeclaredFieldError(UnrepresentableError):
    def __init__(self, model: ModelName, field: FieldName) -> None:
        super().__init__(
            f"{model.root}.{field.root} is declared by no class in the MRO"
        )


class ParsedModule:
    def __init__(self, module: ModuleType) -> None:
        self.name = ModuleName(module.__name__)
        self.source = PythonSource(inspect.getsource(module))
        self.tree = ast.parse(self.source.root)

    def segment(self, node: ast.expr) -> PythonSource:
        return PythonSource(ast.get_source_segment(self.source.root, node) or "")

    def class_def(self, name: ModelName) -> ast.ClassDef:
        return next(
            node
            for node in self.tree.body
            if isinstance(node, ast.ClassDef) and node.name == name.root
        )

    def import_of(self, name: SymbolName) -> Import | None:
        bound = {
            statement.bound_name(): statement for statement in self._imports().to_list()
        }
        if name in bound:
            return bound[name]
        defined_here = any(
            isinstance(node, ast.ClassDef | ast.FunctionDef) and node.name == name.root
            for node in self.tree.body
        )
        return Import(module=self.name, name=name) if defined_here else None

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


def _imports_for(node: ast.expr, parsed: ParsedModule) -> tuple[Import, ...]:
    resolved = _free_names(node).map(parsed.import_of).to_list()
    return tuple(statement for statement in resolved if statement is not None)


def _declaring_class(cls: type[BaseModel], name: FieldName) -> type:
    declaring = next(
        (
            ancestor
            for ancestor in cls.__mro__
            if name.root in inspect.get_annotations(ancestor)
        ),
        None,
    )
    if declaring is None:
        raise UndeclaredFieldError(ModelName(cls.__name__), name)
    return declaring


def _annotated_assign(
    parsed: ParsedModule, owner: ModelName, name: FieldName
) -> ast.AnnAssign:
    return next(
        node
        for node in parsed.class_def(owner).body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == name.root
    )


def _field(cls: type[BaseModel], name: FieldName) -> Field:
    declaring = _declaring_class(cls, name)
    parsed = ParsedModule(inspect.getmodule(declaring))  # pyrefly: ignore
    assign = _annotated_assign(parsed, ModelName(declaring.__name__), name)
    assigned = assign.value
    return Field(
        name=name,
        annotation=AnnotationText(parsed.segment(assign.annotation).root),
        default=DefaultText(parsed.segment(assigned).root) if assigned else None,
        imports=_imports_for(assign.annotation, parsed)
        + (_imports_for(assigned, parsed) if assigned else ()),
    )


def _model(cls: type[BaseModel]) -> Model:
    parsed = ParsedModule(inspect.getmodule(cls))  # pyrefly: ignore
    definition = parsed.class_def(ModelName(cls.__name__))
    bases = Arr(definition.bases)
    return Model(
        name=ModelName(cls.__name__),
        bases=tuple(
            bases.map(lambda base: BaseName(parsed.segment(base).root)).to_list()
        ),
        fields=tuple(
            Arr(list(cls.model_fields))
            .map(lambda name: _field(cls, FieldName(name)))
            .to_list()
        ),
        imports=tuple(
            bases.map(lambda base: _imports_for(base, parsed)).flatten().to_list()
        ),
    )


def load(target: ModelTarget) -> Arr[Model]:
    module_name, _, class_name = target.root.partition(":")
    module = importlib.import_module(module_name)
    return Arr([_model(getattr(module, class_name))])
