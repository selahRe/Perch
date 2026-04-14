from typing import Literal

from pydantic import BaseModel


class PetState(BaseModel):
    visible: bool = True
    emotion: Literal["happy", "eat", "play"] = "happy"
    speak: str = ""
