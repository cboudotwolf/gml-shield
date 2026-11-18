from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=14, max_length=200)


class MissionInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=500)
    secret_code: str = Field(min_length=1, max_length=200)
    driver_id: int = Field(gt=0)


class StatusInput(BaseModel):
    status: str


class DriverMessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=2000)


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str


class MissionView(BaseModel):
    id: int
    title: str
    destination: str
    secret_code: str
    status: str
    driver_id: int
    dispatcher_id: int
    created_at: datetime
    documents: list[str] = Field(default_factory=list)


class DriverMessageView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    driver_id: int
    content: str
    created_at: datetime
