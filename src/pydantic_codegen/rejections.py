from pydantic_codegen.ir import FieldName, ModelName, ModuleName, SymbolName
from pydantic_codegen.python_source import PythonSource


class UnrepresentableError(Exception): ...


class UnboundTypeParameterError(UnrepresentableError): ...


class UnparametrisedModelError(UnboundTypeParameterError):
    def __init__(self, model: ModelName, parameter: SymbolName) -> None:
        super().__init__(
            f"{model.root} leaves the type parameter {parameter.root} unbound; "
            f"load a parametrised alias or a concrete subclass instead"
        )


class TypeParameterAnnotationError(UnboundTypeParameterError):
    def __init__(self, model: ModelName, parameter: SymbolName) -> None:
        super().__init__(
            f"{model.root} annotates a field with the type parameter "
            f"{parameter.root}, which stands for no concrete type"
        )


class RootModelSourceError(UnrepresentableError):
    def __init__(self, model: ModelName) -> None:
        super().__init__(
            f"{model.root} is a RootModel, which has a root rather than fields"
        )


class ValidatorError(UnrepresentableError):
    def __init__(self, model: ModelName, validator: SymbolName) -> None:
        super().__init__(f"{model.root} validates through {validator.root}")


class ComputedFieldError(UnrepresentableError):
    def __init__(self, model: ModelName, field: FieldName) -> None:
        super().__init__(f"{model.root} computes {field.root} rather than declaring it")


class UndeclaredFieldError(UnrepresentableError):
    def __init__(self, model: ModelName, field: FieldName) -> None:
        super().__init__(f"no class in the MRO of {model.root} declares {field.root}")


class UndeclaredModelError(UnrepresentableError):
    def __init__(self, module: ModuleName, model: ModelName) -> None:
        super().__init__(
            f"{module.root} holds no class statement for {model.root}, "
            f"so there is no source to read its bases and fields from"
        )


class UnresolvableNameError(UnrepresentableError):
    def __init__(self, module: ModuleName, name: SymbolName) -> None:
        super().__init__(f"{module.root} neither imports nor defines {name.root}")


class UnreadableExpressionError(UnrepresentableError):
    def __init__(self, source: PythonSource) -> None:
        super().__init__(f"{source.root!r} is not an expression this loader can read")
