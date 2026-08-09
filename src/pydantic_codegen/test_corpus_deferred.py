from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from pydantic_codegen.test_corpus_asset_location import FolderId


class Deferred(BaseModel):
    folder_id: FolderId
