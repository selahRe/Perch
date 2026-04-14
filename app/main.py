from fastapi import FastAPI

from .models import PetState

app = FastAPI(title="Perch Local API", version="0.1.0")

# In-memory state for local Electron integration.
current_state = PetState()


@app.get("/state", response_model=PetState)
def get_state() -> PetState:
    return current_state
