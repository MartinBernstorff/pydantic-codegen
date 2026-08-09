from pydantic_codegen import test_corpus_identified as ident
from pydantic_codegen.test_corpus_asset_location import FolderId


class Attributed(ident.Identified):
    id: FolderId
