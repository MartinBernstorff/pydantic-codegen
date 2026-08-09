import importlib.util
import subprocess
import sys
from pathlib import Path

from pydantic_codegen.loader import load
from pydantic_codegen.test_corpus_subfolder import Subfolder
from pydantic_codegen.writing import File, generated

SUBFOLDER = "pydantic_codegen.test_corpus_subfolder:Subfolder"

RECIPE = """
from pydantic_codegen.loader import load
from pydantic_codegen.writing import File, write

write(
    [
        File(
            "generated/subfolder.py",
            load("pydantic_codegen.test_corpus_subfolder:Subfolder"),
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


def test_generated_pairs_the_output_path_with_its_source(tmp_path: Path) -> None:
    destination = tmp_path / "subfolder.py"

    only = generated([File(str(destination), load(SUBFOLDER))])[0]

    assert only.path == destination
    assert "class Subfolder(BaseModel):" in only.source.root
    assert not destination.exists()


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

    failed = subprocess.run(
        [sys.executable, str(recipe)], cwd=tmp_path, capture_output=True, check=False
    )

    assert failed.returncode != 0
    assert b"RepoRootNotFoundError" in failed.stderr


def test_ruff_missing_from_path_raises_instead_of_writing(tmp_path: Path) -> None:
    recipe = _recipe_repo(tmp_path)

    failed = subprocess.run(
        [sys.executable, str(recipe)],
        cwd=tmp_path,
        env={"PATH": str(tmp_path / "empty-bin")},
        capture_output=True,
        check=False,
    )

    assert b"FormatterNotFoundError" in failed.stderr
    assert not (tmp_path / "generated").exists()
