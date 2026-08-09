from pydantic import BaseModel


class Identified[ID](BaseModel):
    id: ID
