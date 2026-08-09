from pydantic import BaseModel

from pydantic_codegen.test_corpus_asset_location import FolderId as LocationId


class Located(BaseModel):
    location: LocationId
