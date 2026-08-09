from pydantic import BaseModel

from pydantic_codegen.test_corpus_asset_location import FolderId


class Pair(BaseModel):
    left: FolderId
    right: FolderId
