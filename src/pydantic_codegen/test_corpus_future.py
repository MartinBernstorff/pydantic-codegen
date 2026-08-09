from __future__ import annotations

from pydantic import BaseModel

from pydantic_codegen.test_corpus_asset_location import FolderId


class Deferred(BaseModel):
    folder_id: FolderId
