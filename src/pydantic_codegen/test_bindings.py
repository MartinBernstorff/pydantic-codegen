import pytest

from pydantic_codegen.bindings import Bindings
from pydantic_codegen.ir import (
    AnnotationText,
    BaseName,
    DefaultText,
    FrozenText,
    Import,
    ModelName,
    ModuleName,
    SymbolName,
)
from pydantic_codegen.module_source import ModuleSource
from pydantic_codegen.python_source import PythonSource
from pydantic_codegen.rejections import (
    TypeParameterAnnotationError,
    UnresolvableNameError,
)

DECLARING = PythonSource("""
from typing import TYPE_CHECKING

from decimal import Decimal as Money
from pydantic import BaseModel, Field

from .test_corpus_stamping import Stamped

if TYPE_CHECKING:
    from pydantic_codegen.test_corpus_tagging import Tag


class Local(BaseModel): ...


Alias = int


class Example(BaseModel): ...
""")


def _bindings(parameters: frozenset[SymbolName] = frozenset()) -> Bindings:
    return Bindings(
        module=ModuleSource(
            name=ModuleName("pydantic_codegen.declaring"),
            package=ModuleName("pydantic_codegen"),
            source=DECLARING,
            type_parameters=parameters,
        ),
        model=ModelName("Example"),
    )


def _own(name: SymbolName) -> Import:
    return Import(module=ModuleName("pydantic_codegen.declaring"), name=name)


FIELD = Import(module=ModuleName("pydantic"), name=SymbolName("Field"))
TAG = Import(
    module=ModuleName("pydantic_codegen.test_corpus_tagging"), name=SymbolName("Tag")
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (AnnotationText("int"), set()),
        (AnnotationText("Tag"), {TAG}),
        (AnnotationText('"Tag | None"'), {TAG}),
        (AnnotationText("list[Tag]"), {TAG}),
        (
            AnnotationText("Money"),
            {
                Import(
                    module=ModuleName("decimal"),
                    name=SymbolName("Decimal"),
                    alias=SymbolName("Money"),
                )
            },
        ),
        (AnnotationText("Local"), {_own(SymbolName("Local"))}),
        (AnnotationText("Alias"), {_own(SymbolName("Alias"))}),
        (DefaultText("Field(default_factory=list)"), {FIELD}),
        (DefaultText('Field(description="Tag")'), {FIELD}),
        (DefaultText("Tag"), {TAG}),
        (DefaultText('"Tag"'), set()),
        (
            DefaultText("Field(default_factory=lambda: [Tag(word) for word in ()])"),
            {FIELD, TAG},
        ),
        (
            DefaultText("Field(default_factory=lambda: sorted([Tag('a')], key=len))"),
            {FIELD, TAG},
        ),
        (BaseName("Local"), {_own(SymbolName("Local"))}),
        (
            BaseName("Stamped"),
            {
                Import(
                    module=ModuleName("pydantic_codegen.test_corpus_stamping"),
                    name=SymbolName("Stamped"),
                )
            },
        ),
    ],
    ids=lambda case: (
        f"{type(case).__name__} {case.root}" if isinstance(case, FrozenText) else None
    ),
)
def test_imports_a_source_expression_needs(
    source: AnnotationText | DefaultText | BaseName, expected: set[Import]
) -> None:
    assert set(_bindings().imports_for(source)) == expected


def test_a_type_parameter_stands_for_no_importable_name() -> None:
    with pytest.raises(TypeParameterAnnotationError, match="Example"):
        _ = _bindings(frozenset({SymbolName("Id")})).imports_for(AnnotationText("Id"))


def test_a_name_the_module_neither_imports_nor_defines_is_unresolvable() -> None:
    with pytest.raises(UnresolvableNameError, match="Absent"):
        _ = _bindings().imports_for(AnnotationText("Absent"))
