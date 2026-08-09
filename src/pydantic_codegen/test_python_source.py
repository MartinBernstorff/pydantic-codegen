from iterpy import Arr

from pydantic_codegen.python_source import PythonSource, concatenated


def test_followed_by_separates_with_a_newline() -> None:
    joined = PythonSource("import os").followed_by(PythonSource("import sys"))

    assert joined == PythonSource("import os\nimport sys")


def test_concatenated_preserves_order() -> None:
    sources = Arr([PythonSource("a"), PythonSource("b"), PythonSource("c")])

    assert concatenated(sources) == PythonSource("a\nb\nc")
