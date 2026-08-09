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
    # File.label() walks up for a .git directory, so the recipe needs a repo to sit in.
    (root / ".git").mkdir()
    recipe = root / "codegen.py"
    _ = recipe.write_text(RECIPE.format(target=target.root))
    _ = subprocess.run([sys.executable, str(recipe)], cwd=root, check=True)
    return root / "generated" / "model.py"


def _golden(target: ModelTarget) -> Path:
    module = target.module().root.rpartition(".")[2]
    return Path(__file__).parent / f"{module}.{target.model().root}.golden"


def _source_model(target: ModelTarget) -> type[BaseModel]:
    module = importlib.import_module(target.module().root)
    source: type[BaseModel] = getattr(module, target.model().root)
    return source


def _imported_model(target: ModelTarget, generated: Path) -> type[BaseModel]:
    model = target.model().root
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
