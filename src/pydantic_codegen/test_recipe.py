import subprocess
import sys
from pathlib import Path
from types import ModuleType

from pydantic import BaseModel

from pydantic_codegen.ir import ModuleName, SymbolName
from pydantic_codegen.python_source import PythonSource
from pydantic_codegen.test_corpus_builder import SourceModule, corpus

RECIPE = """
from pydantic_codegen import (
    File,
    load,
    omit,
    partial_sentinel,
    pipe,
    rename_model,
    set_bases,
    write,
)

payload = pipe(load("subfolder:Subfolder"), omit("parent_folder_id"))

create = pipe(
    payload,
    set_bases("payload_base:PayloadModel"),
    rename_model(lambda name: f"Create{name}Payload"),
)

update = pipe(
    payload,
    partial_sentinel(),
    set_bases("payload_base:PatchPayloadModel"),
    rename_model(lambda name: f"Update{name}Payload"),
)

write([File("generated/payloads.py", create, update)])
"""

SUBFOLDER = SourceModule(
    name=ModuleName("subfolder"),
    source=PythonSource("""
from pydantic import BaseModel, RootModel


class SubfolderName(RootModel[str]): ...


class FolderId(RootModel[str]): ...


class Subfolder(BaseModel):
    name: SubfolderName
    parent_folder_id: FolderId
"""),
)

PAYLOAD_BASE = SourceModule(
    name=ModuleName("payload_base"),
    source=PythonSource("""
from pydantic import BaseModel


class PayloadModel(BaseModel): ...


class PatchPayloadModel(BaseModel): ...
"""),
)


def _executed(source: PythonSource) -> ModuleType:
    module = ModuleType("generated_payloads")
    sys.modules[module.__name__] = module
    exec(source.root, module.__dict__)
    return module


def _model(module: ModuleType, name: SymbolName) -> type[BaseModel]:
    generated: type[BaseModel] = getattr(module, name.root)
    return generated


# The only test that runs a recipe as a recipe: a real repository, a real interpreter,
# and a working directory that is not the recipe's own, so the output path is proven to
# follow the recipe file rather than wherever it was invoked from.
def test_a_recipe_writes_payloads_that_behave_like_the_source(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    _ = (tmp_path / "codegen.py").write_text(RECIPE)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    with corpus(tmp_path, [SUBFOLDER, PAYLOAD_BASE]):
        _ = subprocess.run(
            [sys.executable, str(tmp_path / "codegen.py")],
            cwd=elsewhere,
            env={
                "PATH": str(Path(sys.executable).parent),
                "PYTHONPATH": str(tmp_path),
            },
            check=True,
        )
        written = _executed(
            PythonSource((tmp_path / "generated" / "payloads.py").read_text())
        )

        assert set(
            _model(written, SymbolName("CreateSubfolderPayload")).model_fields
        ) == {"name"}
        assert (
            _model(written, SymbolName("UpdateSubfolderPayload"))().model_dump() == {}
        )
