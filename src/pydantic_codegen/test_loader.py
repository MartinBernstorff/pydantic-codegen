from pydantic_codegen.ir import (
    AnnotationText,
    BaseName,
    Field,
    FieldName,
    Import,
    Model,
    ModelName,
    ModuleName,
    SymbolName,
)
from pydantic_codegen.loader import ModelTarget, load


def test_loads_fields_bases_and_imports() -> None:
    loaded = load(ModelTarget("pydantic_codegen.test_corpus_subfolder:Subfolder"))

    assert loaded.to_list() == [
        Model(
            name=ModelName("Subfolder"),
            bases=(BaseName("BaseModel"),),
            fields=(
                Field(
                    name=FieldName("name"),
                    annotation=AnnotationText("SubfolderName"),
                    imports=(
                        Import(
                            module=ModuleName("pydantic_codegen.test_corpus_subfolder"),
                            name=SymbolName("SubfolderName"),
                        ),
                    ),
                ),
                Field(
                    name=FieldName("parent_folder_id"),
                    annotation=AnnotationText("FolderId"),
                    imports=(
                        Import(
                            module=ModuleName(
                                "pydantic_codegen.test_corpus_asset_location"
                            ),
                            name=SymbolName("FolderId"),
                        ),
                    ),
                ),
            ),
            imports=(
                Import(module=ModuleName("pydantic"), name=SymbolName("BaseModel")),
            ),
        )
    ]
