import ast
import builtins
import importlib.util
import inspect
from functools import cache
from types import ModuleType
from typing import TypeVar

from iterpy import Arr
from pydantic import BaseModel, ConfigDict

from pydantic_codegen.ir import (
    AnnotationText,
    BaseName,
    DefaultText,
    FieldName,
    Import,
    ModelName,
    ModuleName,
    SymbolName,
)
from pydantic_codegen.python_source import PythonSource
from pydantic_codegen.rejections import UnreadableExpressionError


class FieldSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    annotation: AnnotationText
    default: DefaultText | None = None


def _expression(source: PythonSource) -> ast.expr | None:
    try:
        return ast.parse(source.root, mode="eval").body
    except SyntaxError:
        return None


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


def _referenced(node: ast.expr) -> Arr[SymbolName]:
    bound = _bound_names(node)
    return (
        Arr(list(ast.walk(node)))
        .filter(lambda inner: isinstance(inner, ast.Name))
        .map(lambda inner: SymbolName(inner.id))  # pyrefly: ignore
        .filter(lambda name: not hasattr(builtins, name.root))
        .filter(lambda name: name not in bound)
        .unique()
    )


def _forward_refs(node: ast.expr) -> list[ast.expr]:
    # A string inside a call is metadata — Field(description="…") — never a forward ref.
    if isinstance(node, ast.Call):
        return []
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, str):
            return []
        parsed = _expression(PythonSource(node.value))
        return [parsed] if parsed else []
    return [
        reference
        for child in ast.iter_child_nodes(node)
        if isinstance(child, ast.expr)
        for reference in _forward_refs(child)
    ]


def _annotation_references(node: ast.expr) -> Arr[SymbolName]:
    return (
        _referenced(node)
        .chain(Arr(_forward_refs(node)).map(_annotation_references).flatten())
        .unique()
    )


# A string that does not parse is a string, not a forward reference; a whole
# annotation that does not parse is source this loader cannot represent.
def _readable(source: PythonSource) -> ast.expr:
    node = _expression(source)
    if node is None:
        raise UnreadableExpressionError(source)
    return node


def free_names(source: PythonSource) -> tuple[SymbolName, ...]:
    return tuple(_referenced(_readable(source)).to_list())


def annotation_names(annotation: AnnotationText) -> tuple[SymbolName, ...]:
    return tuple(
        _annotation_references(_readable(PythonSource(annotation.root))).to_list()
    )


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


class ModuleSource:
    def __init__(
        self,
        *,
        name: ModuleName,
        package: ModuleName,
        source: PythonSource,
        type_parameters: frozenset[SymbolName],
    ) -> None:
        self.name = name
        self.package = package
        self.type_parameters = type_parameters
        self._source = source
        self._tree = ast.parse(source.root)

    def field_source(self, model: ModelName, field: FieldName) -> FieldSource | None:
        assign = next(
            (
                node
                for node in self._class_body(model)
                if isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == field.root
            ),
            None,
        )
        if assign is None:
            return None
        return FieldSource(
            annotation=AnnotationText(self._segment(assign.annotation).root),
            default=DefaultText(self._segment(assign.value).root)
            if assign.value
            else None,
        )

    def bases_of(self, model: ModelName) -> tuple[BaseName, ...] | None:
        definition = self._class_def(model)
        if definition is None:
            return None
        return tuple(BaseName(self._segment(base).root) for base in definition.bases)

    def imports(self) -> tuple[Import, ...]:
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
        return tuple(plain.chain(from_module).to_list())

    def defined_names(self) -> frozenset[SymbolName]:
        declarations = {
            SymbolName(node.name)
            for node in self._tree.body
            if isinstance(node, ast.ClassDef | ast.FunctionDef)
        }
        assignments = {
            SymbolName(target.id)
            for node in self._tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        return frozenset(declarations | assignments)

    def _segment(self, node: ast.expr) -> PythonSource:
        return PythonSource(ast.get_source_segment(self._source.root, node) or "")

    def _class_def(self, model: ModelName) -> ast.ClassDef | None:
        return next(
            (
                node
                for node in self._tree.body
                if isinstance(node, ast.ClassDef) and node.name == model.root
            ),
            None,
        )

    def _class_body(self, model: ModelName) -> list[ast.stmt]:
        definition = self._class_def(model)
        return definition.body if definition else []

    def _statements(self) -> list[ast.stmt]:
        deferred = Arr(self._tree.body).map(_deferred_imports).flatten().to_list()
        return self._tree.body + deferred

    def _absolute(self, node: ast.ImportFrom) -> ModuleName:
        written = f"{'.' * node.level}{node.module or ''}"
        if node.level == 0:
            return ModuleName(written)
        return ModuleName(importlib.util.resolve_name(written, self.package.root))


@cache
def module_source(module: ModuleType) -> ModuleSource:
    return ModuleSource(
        name=ModuleName(module.__name__),
        package=ModuleName(module.__package__ or ""),
        source=PythonSource(inspect.getsource(module)),
        type_parameters=frozenset(
            SymbolName(bound_name)
            for bound_name, bound in vars(module).items()
            if isinstance(bound, TypeVar)
        ),
    )
