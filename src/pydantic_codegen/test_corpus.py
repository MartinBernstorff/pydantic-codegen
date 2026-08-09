import importlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, RootModel

from pydantic_codegen.ir import ModuleName
from pydantic_codegen.loader import ModelTarget, imported, load
from pydantic_codegen.python_source import PythonSource
from pydantic_codegen.renderer import RecipeLabel
from pydantic_codegen.test_corpus_builder import SourceModule, corpus, executed
from pydantic_codegen.writing import File, generated

RECIPE = RecipeLabel("/codegen.py")

CONSTRAINTS = SourceModule(
    name=ModuleName("constraints"),
    source=PythonSource("""
from typing import Annotated

from pydantic import BaseModel, StringConstraints


class Note(BaseModel):
    body: Annotated[str, StringConstraints(min_length=1)]
"""),
)

TAGGING = SourceModule(
    name=ModuleName("tagging"),
    source=PythonSource("""
from pydantic import BaseModel, Field, RootModel


class Tag(RootModel[str]): ...


class Tagged(BaseModel):
    tags: list[Tag] = Field(default_factory=list)


class Preset(BaseModel):
    tags: list[Tag] = Field(default_factory=lambda: [Tag("new")])
"""),
)

FORWARD_REF = SourceModule(
    name=ModuleName("memo"),
    source=PythonSource("""
from pydantic import BaseModel

from tagging import Tag


class Memo(BaseModel):
    note: "Tag | None" = None
"""),
)

BOUND_NAMES = SourceModule(
    name=ModuleName("bound_names"),
    source=PythonSource("""
from pydantic import BaseModel, Field

from tagging import Tag


class Sorted(BaseModel):
    tags: list[Tag] = Field(
        default_factory=lambda: sorted([Tag("b"), Tag("a")], key=lambda tag: tag.root)
    )


class Comprehended(BaseModel):
    tags: list[Tag] = Field(default_factory=lambda: [Tag(word) for word in ("new",)])
"""),
)

OVERRIDING = SourceModule(
    name=ModuleName("overriding"),
    source=PythonSource("""
from pydantic import BaseModel, RootModel


class LooseSlug(RootModel[str]): ...


class StrictSlug(RootModel[str]): ...


class Loose(BaseModel):
    slug: LooseSlug


class Strict(Loose):
    slug: StrictSlug
"""),
)

LOCATION = SourceModule(
    name=ModuleName("location"),
    source=PythonSource("""
from pydantic import RootModel


class FolderId(RootModel[str]): ...
"""),
)

ALIASING = SourceModule(
    name=ModuleName("aliasing"),
    source=PythonSource("""
from pydantic import BaseModel

from location import FolderId as LocationId


class Located(BaseModel):
    location: LocationId
"""),
)

FUTURE = SourceModule(
    name=ModuleName("future"),
    source=PythonSource("""
from __future__ import annotations

from pydantic import BaseModel

from location import FolderId


class Deferred(BaseModel):
    folder_id: FolderId
"""),
)

GENERIC = SourceModule(
    name=ModuleName("generic"),
    source=PythonSource("""
from pydantic import BaseModel


class Identified[ID](BaseModel):
    id: ID
"""),
)

PARAMETRISED = SourceModule(
    name=ModuleName("parametrised"),
    source=PythonSource("""
from pydantic import RootModel

from generic import Identified


class TicketId(RootModel[str]): ...


class Ticket(Identified[TicketId]): ...
"""),
)

# A relative import, banned everywhere else in this repo, because a source model the
# loader reads is someone else's code: the generated file must absolutise it.
PACKAGED_STAMPING = SourceModule(
    name=ModuleName("packaged.stamping"),
    source=PythonSource("""
import datetime

from pydantic import BaseModel


class Stamped(BaseModel):
    created: datetime.datetime
"""),
)

INHERITING = SourceModule(
    name=ModuleName("packaged.inheriting"),
    source=PythonSource("""
from pydantic import RootModel

from .stamping import Stamped


class RecordLabel(RootModel[str]): ...


class Record(Stamped):
    label: RecordLabel
"""),
)

STAMPING = SourceModule(
    name=ModuleName("stamping"),
    source=PythonSource("""
import datetime

from pydantic import BaseModel


class Stamped(BaseModel):
    created: datetime.datetime
"""),
)


class ModelShape(RootModel[dict[str, str]]): ...


class RoundTrip(BaseModel):
    model_config = ConfigDict(frozen=True)

    body: PythonSource
    generated: ModelShape
    source: ModelShape


def _shape(model: type[BaseModel]) -> ModelShape:
    return ModelShape(
        {
            name: f"{field.annotation}|{field.metadata}|{field.is_required()}"
            for name, field in model.model_fields.items()
        }
    )


def _source_model(target: ModelTarget) -> type[BaseModel]:
    statement = imported(target)
    module = importlib.import_module(statement.module.root)
    model: type[BaseModel] = getattr(module, statement.bound_name().root)
    return model


def _round_trip(root: Path, target: ModelTarget) -> RoundTrip:
    source = generated([File(str(root / "generated.py"), load(target.root))], RECIPE)[
        0
    ].source
    bound = imported(target).bound_name()
    with executed(source, ModuleName(f"generated_{bound.root}")) as module:
        generated_model: type[BaseModel] = getattr(module, bound.root)
        return RoundTrip(
            body=PythonSource(source.root.split("\n", 2)[2]),
            generated=_shape(generated_model),
            source=_shape(_source_model(target)),
        )


def test_the_header_credits_the_recipe_that_generated_the_file(tmp_path: Path) -> None:
    with corpus(tmp_path, [STAMPING]):
        source = generated(
            [File(str(tmp_path / "generated.py"), load("stamping:Stamped"))], RECIPE
        )[0].source

    assert source == PythonSource("""\
# Generated by pydantic-codegen. Do not edit.
# Recipe: /codegen.py
import datetime

from pydantic import BaseModel


class Stamped(BaseModel):
    created: datetime.datetime
""")


def test_a_constrained_field_keeps_its_annotation(tmp_path: Path) -> None:
    with corpus(tmp_path, [CONSTRAINTS]):
        result = _round_trip(tmp_path, ModelTarget("constraints:Note"))

    assert result.body == PythonSource("""\
from typing import Annotated

from pydantic import BaseModel, StringConstraints


class Note(BaseModel):
    body: Annotated[str, StringConstraints(min_length=1)]
""")
    assert result.generated == result.source


def test_a_default_factory_is_carried_over(tmp_path: Path) -> None:
    with corpus(tmp_path, [TAGGING]):
        result = _round_trip(tmp_path, ModelTarget("tagging:Tagged"))

    assert result.body == PythonSource("""\
from pydantic import BaseModel, Field
from tagging import Tag


class Tagged(BaseModel):
    tags: list[Tag] = Field(default_factory=list)
""")
    assert result.generated == result.source


def test_a_dotted_annotation_imports_its_module(tmp_path: Path) -> None:
    with corpus(tmp_path, [STAMPING]):
        result = _round_trip(tmp_path, ModelTarget("stamping:Stamped"))

    assert result.body == PythonSource("""\
import datetime

from pydantic import BaseModel


class Stamped(BaseModel):
    created: datetime.datetime
""")
    assert result.generated == result.source


def test_a_lambda_default_keeps_the_names_it_calls(tmp_path: Path) -> None:
    with corpus(tmp_path, [TAGGING]):
        result = _round_trip(tmp_path, ModelTarget("tagging:Preset"))

    assert result.body == PythonSource("""\
from pydantic import BaseModel, Field
from tagging import Tag


class Preset(BaseModel):
    tags: list[Tag] = Field(default_factory=lambda: [Tag("new")])
""")
    assert result.generated == result.source


def test_a_forward_ref_becomes_a_real_import(tmp_path: Path) -> None:
    with corpus(tmp_path, [TAGGING, FORWARD_REF]):
        result = _round_trip(tmp_path, ModelTarget("memo:Memo"))

    assert result.body == PythonSource("""\
from pydantic import BaseModel
from tagging import Tag


class Memo(BaseModel):
    note: "Tag | None" = None
""")
    assert result.generated == result.source


def test_a_lambda_argument_is_not_mistaken_for_an_import(tmp_path: Path) -> None:
    with corpus(tmp_path, [TAGGING, BOUND_NAMES]):
        result = _round_trip(tmp_path, ModelTarget("bound_names:Sorted"))

    assert result.body == PythonSource("""\
from pydantic import BaseModel, Field
from tagging import Tag


class Sorted(BaseModel):
    tags: list[Tag] = Field(
        default_factory=lambda: sorted([Tag("b"), Tag("a")], key=lambda tag: tag.root)
    )
""")
    assert result.generated == result.source


def test_a_comprehension_target_is_not_mistaken_for_an_import(tmp_path: Path) -> None:
    with corpus(tmp_path, [TAGGING, BOUND_NAMES]):
        result = _round_trip(tmp_path, ModelTarget("bound_names:Comprehended"))

    assert result.body == PythonSource("""\
from pydantic import BaseModel, Field
from tagging import Tag


class Comprehended(BaseModel):
    tags: list[Tag] = Field(default_factory=lambda: [Tag(word) for word in ("new",)])
""")
    assert result.generated == result.source


def test_an_overridden_field_is_declared_once_by_the_subclass(tmp_path: Path) -> None:
    with corpus(tmp_path, [OVERRIDING]):
        result = _round_trip(tmp_path, ModelTarget("overriding:Strict"))

    assert result.body == PythonSource("""\
from overriding import Loose, StrictSlug


class Strict(Loose):
    slug: StrictSlug
""")
    assert result.generated == result.source


def test_an_aliased_import_keeps_the_alias_the_source_bound(tmp_path: Path) -> None:
    with corpus(tmp_path, [LOCATION, ALIASING]):
        result = _round_trip(tmp_path, ModelTarget("aliasing:Located"))

    assert result.body == PythonSource("""\
from location import FolderId as LocationId
from pydantic import BaseModel


class Located(BaseModel):
    location: LocationId
""")
    assert result.generated == result.source


def test_a_postponed_annotation_resolves_to_a_real_import(tmp_path: Path) -> None:
    with corpus(tmp_path, [LOCATION, FUTURE]):
        result = _round_trip(tmp_path, ModelTarget("future:Deferred"))

    assert result.body == PythonSource("""\
from location import FolderId
from pydantic import BaseModel


class Deferred(BaseModel):
    folder_id: FolderId
""")
    assert result.generated == result.source


def test_a_parametrised_base_keeps_its_type_argument(tmp_path: Path) -> None:
    with corpus(tmp_path, [GENERIC, PARAMETRISED]):
        result = _round_trip(tmp_path, ModelTarget("parametrised:Ticket"))

    assert result.body == PythonSource("""\
from generic import Identified
from parametrised import TicketId


class Ticket(Identified[TicketId]):
    pass
""")
    assert result.generated == result.source


def test_a_relative_source_import_is_absolutised(tmp_path: Path) -> None:
    with corpus(tmp_path, [PACKAGED_STAMPING, INHERITING]):
        result = _round_trip(tmp_path, ModelTarget("packaged.inheriting:Record"))

    assert result.body == PythonSource("""\
from packaged.inheriting import RecordLabel
from packaged.stamping import Stamped


class Record(Stamped):
    label: RecordLabel
""")
    assert result.generated == result.source
