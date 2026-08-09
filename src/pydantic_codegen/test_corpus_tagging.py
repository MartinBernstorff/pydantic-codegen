from pydantic import BaseModel, Field, RootModel


class Tag(RootModel[str]): ...


class Tagged(BaseModel):
    tags: list[Tag] = Field(default_factory=list)


class Preset(BaseModel):
    tags: list[Tag] = Field(default_factory=lambda: [Tag("new")])
