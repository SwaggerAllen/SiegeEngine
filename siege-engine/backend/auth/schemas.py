from pydantic import BaseModel


class RegisterRequest(BaseModel):
    username: str
    password: str
    invite_token: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token: str
    user: dict


class UserResponse(BaseModel):
    id: str
    username: str
    role: str


class CreateInviteRequest(BaseModel):
    role: str = "member"


class InviteResponse(BaseModel):
    id: str
    token: str
    url: str
    expires_at: str
    used: bool
    created_at: str
    role: str
