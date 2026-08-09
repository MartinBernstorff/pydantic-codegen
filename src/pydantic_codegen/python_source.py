from iterpy import Arr
from pydantic import RootModel


class PythonSource(RootModel[str]):
    def followed_by(self, other: "PythonSource") -> "PythonSource":
        return PythonSource(f"{self.root}\n{other.root}")


def concatenated(sources: Arr[PythonSource]) -> PythonSource:
    return sources.reduce(lambda left, right: left.followed_by(right))
