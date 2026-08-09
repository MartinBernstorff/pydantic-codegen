import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, RootModel

from pydantic_codegen.loader import ModelTarget

CORPUS = [
    ModelTarget("pydantic_codegen.test_corpus_constraints:Note"),
    ModelTarget("pydantic_codegen.test_corpus_tagging:Tagged"),
    ModelTarget("pydantic_codegen.test_corpus_tagging:Preset"),
    ModelTarget("pydantic_codegen.test_corpus_forward_ref:Memo"),
    ModelTarget("pydantic_codegen.test_corpus_inheriting:Record"),
    ModelTarget("pydantic_codegen.test_corpus_overriding:Strict"),
    ModelTarget("pydantic_codegen.test_corpus_parametrised:Ticket"),
    ModelTarget("pydantic_codegen.test_corpus_aliasing:Located"),
    ModelTarget("pydantic_codegen.test_corpus_stamping:Stamped"),
    ModelTarget("pydantic_codegen.test_corpus_future:Deferred"),
    ModelTarget("pydantic_codegen.test_corpus_bound_names:Sorted"),
    ModelTarget("pydantic_codegen.test_corpus_bound_names:Comprehended"),
]

RECIPE = """
from pydantic_codegen.loader import ModelTarget, load
from pydantic_codegen.writing import File, OutputPath, write

write([File(OutputPath("generated/model.py"), load(ModelTarget("{target}")))])
"""


def _generated(target: ModelTarget, root: Path) -> Path:
    (root / ".git").mkdir()
    recipe = root / "codegen.py"
    _ = recipe.write_text(RECIPE.format(target=target.root))
    _ = subprocess.run([sys.executable, str(recipe)], cwd=root, check=True)
    return root / "generated" / "model.py"


def _golden(target: ModelTarget) -> Path:
    module, _, model = target.root.partition(":")
    return Path(__file__).parent / f"{module.rpartition('.')[2]}.{model}.golden"


def _source_model(target: ModelTarget) -> type[BaseModel]:
    module, _, model = target.root.partition(":")
    source: type[BaseModel] = getattr(importlib.import_module(module), model)
    return source


def _imported_model(target: ModelTarget, generated: Path) -> type[BaseModel]:
    _, _, model = target.root.partition(":")
    name = f"generated_{model}"
    spec = importlib.util.spec_from_file_location(name, generated)
    module = importlib.util.module_from_spec(spec)  # pyrefly: ignore
    # Pydantic resolves a forward ref through sys.modules, so a module that is not
    # registered leaves `note: "Tag | None"` an unevaluated ForwardRef.
    sys.modules[name] = module
    spec.loader.exec_module(module)  # pyrefly: ignore
    imported: type[BaseModel] = getattr(module, model)
    return imported


class ModelShape(RootModel[dict[str, str]]): ...


def _shape(model: type[BaseModel]) -> ModelShape:
    return ModelShape(
        {
            name: f"{field.annotation}|{field.metadata}|{field.is_required()}"
            for name, field in model.model_fields.items()
        }
    )


@pytest.mark.parametrize("target", CORPUS, ids=lambda target: target.root)
def test_corpus_case_matches_golden(target: ModelTarget, tmp_path: Path) -> None:
    generated = _generated(target, tmp_path)

    assert generated.read_bytes() == _golden(target).read_bytes()


@pytest.mark.parametrize("target", CORPUS, ids=lambda target: target.root)
def test_corpus_case_round_trips(target: ModelTarget, tmp_path: Path) -> None:
    generated = _generated(target, tmp_path)

    assert _shape(_imported_model(target, generated)) == _shape(_source_model(target))
