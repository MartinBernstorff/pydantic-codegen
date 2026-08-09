from typing import Annotated

from pydantic import BaseModel, StringConstraints


class Note(BaseModel):
    body: Annotated[str, StringConstraints(min_length=1)]
