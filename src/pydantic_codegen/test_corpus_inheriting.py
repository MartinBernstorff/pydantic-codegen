from pydantic import RootModel

# A relative import, banned everywhere else in this repo, because a source model the
# loader reads is someone else's code: the generated file must absolutise it.
from .test_corpus_stamping import Stamped


class RecordLabel(RootModel[str]): ...


class Record(Stamped):
    label: RecordLabel
