from pathlib import Path

import pytest

from pydantic_codegen.ir import (
    AnnotationText,
    Base,
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
from pydantic_codegen.loader import MalformedTargetError
from pydantic_codegen.python_source import PythonSource
from pydantic_codegen.test_corpus_builder import SourceModule, corpus
from pydantic_codegen.transformers import (
    AmbiguousRenameError,
    UnknownFieldError,
    each,
    each_field,
    omit,
    partial_none,
    partial_sentinel,
    pick,
    pipe,
    rename_model,
    set_bases,
)


def _model(*field_names: FieldName) -> Model:
    return Model(
        name=ModelName("Subfolder"),
        fields=tuple(
            Field(name=name, annotation=AnnotationText("str")) for name in field_names
        ),
    )


def test_pipe_applies_transformers_left_to_right() -> None:
    suffix = each(
        lambda model: [
            model.model_copy(update={"name": ModelName(model.name.root + "!")})
        ]
    )

    assert pipe([_model()], suffix, suffix) == [
        _model().model_copy(update={"name": ModelName("Subfolder!!")})
    ]


def test_omit_drops_the_named_fields() -> None:
    assert pipe([_model(FieldName("id"), FieldName("name"))], omit("id")) == [
        _model(FieldName("name"))
    ]


def test_omit_of_an_unknown_field_lists_the_actual_fields() -> None:
    with pytest.raises(UnknownFieldError) as raised:
        _ = pipe([_model(FieldName("id"), FieldName("name"))], omit("identifier"))

    assert "id, name" in str(raised.value)


def test_pick_keeps_only_the_named_fields_in_declaration_order() -> None:
    assert pipe(
        [_model(FieldName("id"), FieldName("name"), FieldName("parent"))],
        pick("parent", "id"),
    ) == [_model(FieldName("id"), FieldName("parent"))]


def test_pick_of_an_unknown_field_lists_the_actual_fields() -> None:
    with pytest.raises(UnknownFieldError) as raised:
        _ = pipe([_model(FieldName("id"), FieldName("name"))], pick("identifier"))

    assert "id, name" in str(raised.value)


def _annotated(annotation: AnnotationText, default: DefaultText | None = None) -> Model:
    return Model(
        name=ModelName("Subfolder"),
        fields=(
            Field(
                name=FieldName("name"),
                annotation=annotation,
                default=default,
                imports=(Import(module=ModuleName("domain"), name=SymbolName("Name")),),
            ),
        ),
    )


def test_partial_sentinel_appends_the_token_replaces_the_default_and_imports_it() -> (
    None
):
    [transformed] = pipe(
        [_annotated(AnnotationText("Name"), DefaultText("Name('x')"))],
        partial_sentinel(),
    )

    assert transformed.fields[0].annotation == AnnotationText("Name | MISSING")
    assert transformed.fields[0].default == DefaultText("MISSING")
    assert (
        Import(
            module=ModuleName("pydantic.experimental.missing_sentinel"),
            name=SymbolName("MISSING"),
        )
        in transformed.fields[0].imports
    )


def test_partial_sentinel_leaves_an_already_sentinel_field_alone() -> None:
    once = pipe([_annotated(AnnotationText("Name"))], partial_sentinel())

    assert pipe(once, partial_sentinel()) == once


def test_partial_none_widens_the_annotation_and_defaults_it() -> None:
    [transformed] = pipe(
        [_annotated(AnnotationText("Name"), DefaultText("Name('x')"))], partial_none()
    )

    assert transformed.fields[0].annotation == AnnotationText("Name | None")
    assert transformed.fields[0].default == DefaultText("None")


def test_partial_none_adds_the_default_to_an_already_optional_annotation() -> None:
    [transformed] = pipe([_annotated(AnnotationText("Name | None"))], partial_none())

    assert transformed.fields[0].annotation == AnnotationText("Name | None")
    assert transformed.fields[0].default == DefaultText("None")


def test_partial_none_is_idempotent() -> None:
    once = pipe([_annotated(AnnotationText("Name"))], partial_none())

    assert pipe(once, partial_none()) == once


PAYLOAD_BASE = SourceModule(
    name=ModuleName("payload_base"),
    source=PythonSource("""
from pydantic import BaseModel


class PayloadModel(BaseModel): ...
"""),
)


def test_set_bases_replaces_the_bases_and_carries_their_import(
    tmp_path: Path,
) -> None:
    with corpus(tmp_path, [PAYLOAD_BASE]):
        [transformed] = pipe(
            [_annotated(AnnotationText("Name"))],
            set_bases("payload_base:PayloadModel"),
        )

    assert transformed.bases == (Base(name=BaseName("PayloadModel")),)
    assert transformed.imports == (
        Import(module=ModuleName("payload_base"), name=SymbolName("PayloadModel")),
    )


def test_set_bases_takes_several_bases(tmp_path: Path) -> None:
    with corpus(tmp_path, [PAYLOAD_BASE]):
        [transformed] = pipe(
            [_annotated(AnnotationText("Name"))],
            set_bases("payload_base:PayloadModel", "abc:ABC"),
        )

    assert transformed.bases == (
        Base(name=BaseName("PayloadModel")),
        Base(name=BaseName("ABC")),
    )


def test_set_bases_rejects_a_bare_class_name() -> None:
    with pytest.raises(MalformedTargetError):
        _ = pipe(
            [_annotated(AnnotationText("Name"))], set_bases("FlowbasePayloadModel")
        )


def test_rename_model_applies_a_callable_to_every_model() -> None:
    folder = _model().model_copy(update={"name": ModelName("Folder")})

    renamed = pipe(
        [_model(), folder], rename_model(lambda name: f"Create{name}Payload")
    )

    assert [model.name for model in renamed] == [
        ModelName("CreateSubfolderPayload"),
        ModelName("CreateFolderPayload"),
    ]


def test_rename_model_applies_a_literal_name_to_a_lone_model() -> None:
    [renamed] = pipe([_model()], rename_model("CreateSubfolderPayload"))

    assert renamed.name == ModelName("CreateSubfolderPayload")


def test_a_literal_rename_of_several_models_is_ambiguous() -> None:
    with pytest.raises(AmbiguousRenameError):
        _ = pipe([_model(), _model()], rename_model("CreateSubfolderPayload"))


def test_each_field_lifts_a_field_level_fan_out() -> None:
    bounded = each_field(
        lambda field: [
            field.model_copy(update={"name": FieldName(f"{field.name.root}_{bound}")})
            for bound in ("gte", "lte")
        ]
    )

    [transformed] = pipe([_model(FieldName("price"))], bounded)

    assert [field.name for field in transformed.fields] == [
        FieldName("price_gte"),
        FieldName("price_lte"),
    ]


def test_partial_none_widens_an_annotation_whose_none_is_nested() -> None:
    [transformed] = pipe(
        [_annotated(AnnotationText("Callable[[int], None]"))], partial_none()
    )

    assert transformed.fields[0].annotation == AnnotationText(
        "Callable[[int], None] | None"
    )
