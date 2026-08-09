from pydantic import BaseModel, ConfigDict, RootModel


class Frozen(RootModel[str]):
    model_config = ConfigDict(frozen=True)


class ModuleName(Frozen): ...


class SymbolName(Frozen): ...


class FieldName(Frozen): ...


class AnnotationText(Frozen): ...


class DefaultText(Frozen): ...


class ModelName(Frozen): ...


class BaseName(Frozen): ...


class Import(BaseModel):
    model_config = ConfigDict(frozen=True)

    module: ModuleName
    name: SymbolName | None = None
    alias: SymbolName | None = None

    def bound_name(self) -> SymbolName:
        if self.alias is not None:
            return self.alias
        if self.name is not None:
            return self.name
        return SymbolName(self.module.root.split(".")[0])


class Field(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: FieldName
    annotation: AnnotationText
    default: DefaultText | None = None
    imports: tuple[Import, ...] = ()


class Model(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: ModelName
    bases: tuple[BaseName, ...] = ()
    fields: tuple[Field, ...] = ()
    imports: tuple[Import, ...] = ()
