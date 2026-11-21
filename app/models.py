from typing import Optional
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

class Section(BaseModel):
    start_s: float = Field(ge=0)
    mood: str = Field(min_length=1, max_length=160)

class OutputOptions(BaseModel):
    sample_rate: int = 48000
    target_lufs: float = -16.0
    formats: list[str] = ["wav"]

    @field_validator("sample_rate")
    @classmethod
    def supported_rate(cls, v):
        if v != 48000:
            raise ValueError("This prototype currently supports 48000 Hz only")
        return v

class MusicJobRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=1000)
    duration_s: float = Field(ge=5, le=300)
    sections: list[Section] = []
    tempo_bpm: Optional[float] = Field(default=None, ge=40, le=200)
    key: Optional[str] = None
    loopable: bool = False
    narration_url: Optional[HttpUrl] = None
    seed: Optional[int] = 42
    output: OutputOptions = OutputOptions()

    @model_validator(mode="after")
    def check_sections(self):
        starts = [s.start_s for s in self.sections]
        if starts != sorted(starts):
            raise ValueError("sections must be ordered by start_s")
        return self
