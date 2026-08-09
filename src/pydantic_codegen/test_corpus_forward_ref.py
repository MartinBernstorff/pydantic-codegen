from pydantic import BaseModel

from pydantic_codegen.test_corpus_tagging import Tag


class Memo(BaseModel):
    note: "Tag | None" = None
