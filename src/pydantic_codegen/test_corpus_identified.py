from pydantic import BaseModel, RootModel

from pydantic_codegen.test_corpus_asset_location import FolderId


class CommentBody(RootModel[str]): ...


class Identified(BaseModel):
    id: FolderId


class Comment(Identified):
    id: FolderId
    body: CommentBody
