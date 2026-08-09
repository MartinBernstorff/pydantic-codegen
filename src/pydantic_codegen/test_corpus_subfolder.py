from pydantic import BaseModel, RootModel

from pydantic_codegen.test_corpus_asset_location import FolderId


class SubfolderName(RootModel[str]): ...


class Subfolder(BaseModel):
    name: SubfolderName
    parent_folder_id: FolderId
