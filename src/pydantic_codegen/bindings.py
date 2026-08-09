from iterpy import Arr

from pydantic_codegen.ir import (
    AnnotationText,
    BaseName,
    DefaultText,
    Import,
    ModelName,
    SymbolName,
)
from pydantic_codegen.module_source import (
    ModuleSource,
    annotation_names,
    free_names,
)
from pydantic_codegen.python_source import PythonSource
from pydantic_codegen.rejections import (
    TypeParameterAnnotationError,
    UnresolvableNameError,
)

Expression = AnnotationText | DefaultText | BaseName


# A string is a forward reference where a type is expected and data everywhere else,
# so `x: "Tag"` needs Tag imported and `x: str = "Tag"` needs nothing.
def _names(source: Expression) -> tuple[SymbolName, ...]:
    if isinstance(source, AnnotationText):
        return annotation_names(source)
    return free_names(PythonSource(source.root))


class Bindings:
    def __init__(self, *, module: ModuleSource, model: ModelName) -> None:
        self.module = module
        self.model = model

    def imports_for(self, source: Expression) -> tuple[Import, ...]:
        return tuple(Arr(list(_names(source))).map(self._import_of).to_list())

    def _import_of(self, name: SymbolName) -> Import:
        if name in self.module.type_parameters:
            raise TypeParameterAnnotationError(self.model, name)
        bound = {
            statement.bound_name(): statement for statement in self.module.imports()
        }
        if name in bound:
            return bound[name]
        if name in self.module.defined_names():
            return Import(module=self.module.name, name=name)
        raise UnresolvableNameError(self.module.name, name)
