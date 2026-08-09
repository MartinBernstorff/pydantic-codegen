from pydantic import BaseModel, RootModel


class LooseSlug(RootModel[str]): ...


class StrictSlug(RootModel[str]): ...


class Loose(BaseModel):
    slug: LooseSlug


class Strict(Loose):
    slug: StrictSlug  # pyrefly: ignore
