from pydantic import BaseModel, RootModel


class SubfolderName(RootModel[str]): ...


class Note(BaseModel):
    subfolder_name: SubfolderName
