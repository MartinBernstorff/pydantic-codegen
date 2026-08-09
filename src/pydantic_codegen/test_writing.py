import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from pydantic_codegen.test_corpus_subfolder import Subfolder

RECIPE = """
from pydantic_codegen.loader import ModelTarget, load
from pydantic_codegen.writing import File, OutputPath, write

write(
    [
        File(
            OutputPath("generated/subfolder.py"),
            load(ModelTarget("pydantic_codegen.test_corpus_subfolder:Subfolder")),
        )
    ]
)
"""


def _recipe_repo(root: Path) -> Path:
    (root / ".git").mkdir()
    recipe = root / "codegen.py"
    _ = recipe.write_text(RECIPE)
    return recipe


def _run(recipe: Path, working_directory: Path) -> None:
    _ = subprocess.run([sys.executable, str(recipe)], cwd=working_directory, check=True)


def test_output_is_independent_of_working_directory(tmp_path: Path) -> None:
    recipe = _recipe_repo(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    generated = tmp_path / "generated" / "subfolder.py"

    _run(recipe, tmp_path)
    from_root = generated.read_bytes()
    generated.unlink()
    _run(recipe, elsewhere)

    assert generated.read_bytes() == from_root


def test_generated_file_matches_golden(tmp_path: Path) -> None:
    recipe = _recipe_repo(tmp_path)

    _run(recipe, tmp_path)

    golden = Path(__file__).parent / "test_corpus_subfolder.golden"
    assert (tmp_path / "generated" / "subfolder.py").read_text() == golden.read_text()


def test_generated_model_matches_the_source_model(tmp_path: Path) -> None:
    recipe = _recipe_repo(tmp_path)

    _run(recipe, tmp_path)

    spec = importlib.util.spec_from_file_location(
        "generated_subfolder", tmp_path / "generated" / "subfolder.py"
    )
    module = importlib.util.module_from_spec(spec)  # pyrefly: ignore
    spec.loader.exec_module(module)  # pyrefly: ignore

    assert {
        name: field.annotation for name, field in module.Subfolder.model_fields.items()
    } == {name: field.annotation for name, field in Subfolder.model_fields.items()}


def test_missing_repo_root_is_an_error(tmp_path: Path) -> None:
    recipe = tmp_path / "codegen.py"
    _ = recipe.write_text(RECIPE)

    with pytest.raises(subprocess.CalledProcessError):
        _run(recipe, tmp_path)


def test_ruff_missing_from_path_raises_instead_of_writing(tmp_path: Path) -> None:
    recipe = _recipe_repo(tmp_path)

    with pytest.raises(subprocess.CalledProcessError):
        _ = subprocess.run(
            [sys.executable, str(recipe)],
            cwd=tmp_path,
            check=True,
            env={"PATH": str(tmp_path / "empty-bin")},
        )

    assert not (tmp_path / "generated").exists()
