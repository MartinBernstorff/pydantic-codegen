import datetime

from pydantic import BaseModel


class Stamped(BaseModel):
    created: datetime.datetime
