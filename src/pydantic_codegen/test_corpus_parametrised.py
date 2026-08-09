from pydantic import RootModel

from pydantic_codegen.test_corpus_generic import Identified


class TicketId(RootModel[str]): ...


class Ticket(Identified[TicketId]): ...
