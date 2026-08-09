import importlib.util
import subprocess
import sys
from pathlib import Path

RECIPE = """
from pydantic_codegen import (
    File,
    add_field,
    load,
    omit,
    partial_sentinel,
    pipe,
    rename_model,
    set_bases,
    write,
)

payload = pipe(
    load("pydantic_codegen.test_corpus_subfolder:Subfolder"),
    omit("parent_folder_id"),
)

create = pipe(
    payload,
    add_field(
        "kind: Literal[SubfolderKind.SUBFOLDER] = SubfolderKind.SUBFOLDER",
        "typing:Literal",
        "pydantic_codegen.test_corpus_kinds:SubfolderKind",
    ),
    set_bases("pydantic_codegen.test_corpus_payload_base:PayloadModel"),
    rename_model(lambda name: f"Create{name}Payload"),
)

update = pipe(
    payload,
    partial_sentinel(),
    set_bases("pydantic_codegen.test_corpus_payload_base:PatchPayloadModel"),
    rename_model(lambda name: f"Update{name}Payload"),
)

write([File("generated/payloads.py", create, update)])
"""


def _generated(root: Path) -> Path:
    (root / ".git").mkdir()
    recipe = root / "codegen.py"
    _ = recipe.write_text(RECIPE)
    _ = subprocess.run([sys.executable, str(recipe)], cwd=root, check=True)
    return root / "generated" / "payloads.py"


def test_the_recipe_surface_generates_the_payload_pair(tmp_path: Path) -> None:
    generated = _generated(tmp_path)

    golden = Path(__file__).parent / "test_corpus_payloads.golden"
    assert generated.read_text() == golden.read_text()


def test_the_generated_patch_payload_omits_an_unset_field(tmp_path: Path) -> None:
    generated = _generated(tmp_path)

    spec = importlib.util.spec_from_file_location("generated_payloads", generated)
    module = importlib.util.module_from_spec(spec)  # pyrefly: ignore
    spec.loader.exec_module(module)  # pyrefly: ignore

    assert module.UpdateSubfolderPayload().model_dump() == {}
