from pydantic import BaseModel, ConfigDict, RootModel


class FrozenText(RootModel[str]):
    model_config = ConfigDict(frozen=True)


class ModuleName(FrozenText): ...


class SymbolName(FrozenText): ...


class FieldName(FrozenText): ...


class AnnotationText(FrozenText): ...


class DefaultText(FrozenText): ...


class ModelName(FrozenText): ...


class BaseName(FrozenText): ...


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


class Base(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: BaseName
    fields: tuple[FieldName, ...] = ()


class Field(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: FieldName
    annotation: AnnotationText
    default: DefaultText | None = None
    imports: tuple[Import, ...] = ()


class Model(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: ModelName
    bases: tuple[Base, ...] = ()
    fields: tuple[Field, ...] = ()
    imports: tuple[Import, ...] = ()
