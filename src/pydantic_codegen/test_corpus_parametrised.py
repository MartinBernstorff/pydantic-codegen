from pydantic import RootModel

from pydantic_codegen.test_corpus_generic import Identified
from pydantic_codegen.test_corpus_tagging import Tag


class TicketId(RootModel[str]): ...


class Ticket(Identified[TicketId]): ...


class Listed(Identified[list[Tag]]): ...
