import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class LoginInput(StrictModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=10, max_length=128)
    @field_validator('email')
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Некорректная почта')
        return value

class RegisterInput(LoginInput):
    display_name: str = Field(min_length=1, max_length=100)
    @field_validator('display_name')
    @classmethod
    def trim_name(cls, value):
        value=value.strip()
        if not value: raise ValueError('Укажите имя')
        return value

class ConsentInput(StrictModel):
    code: Literal['ONBOARDING_PROCESSING','REGISTRY_LOOKUP']
    version: Literal['consent-v2']
    accepted: Literal[True]
    @field_validator('accepted', mode='before')
    @classmethod
    def explicit_true(cls, value):
        if value is not True: raise ValueError('Требуется явное согласие')
        return value

class InnInput(StrictModel):
    inn: StrictStr
    @field_validator('inn')
    @classmethod
    def validate_inn(cls, value):
        if not re.fullmatch(r'(?:[0-9]{10}|[0-9]{12})',value) or len(set(value))==1:
            raise ValueError('Некорректный ИНН')
        d=list(map(int,value))
        def digit(weights): return sum(a*b for a,b in zip(d,weights)) % 11 % 10
        valid = digit([2,4,10,3,5,9,4,6,8])==d[9] if len(d)==10 else digit([7,2,4,10,3,5,9,4,6,8])==d[10] and digit([3,7,2,4,10,3,5,9,4,6,8])==d[11]
        if not valid: raise ValueError('Неверная контрольная сумма ИНН')
        return value

class AuthorityCheckInput(InnInput):
    """The mock Госуслуги check: the ИНН only; the person, role and user come from the fixture and the session."""

class CompanyInput(InnInput):
    consents: list[ConsentInput] = Field(max_length=2)
    # Absent or null is the gate's refusal (403 AUTHORITY_NOT_VERIFIED), like an unknown id.
    authority_verification_id: StrictStr | None = Field(default=None, max_length=36)
    @field_validator('consents')
    @classmethod
    def required_consents(cls, value):
        if {c.code for c in value} != {'ONBOARDING_PROCESSING','REGISTRY_LOOKUP'}:
            raise ValueError('Нужны оба согласия')
        return value

class VersionInput(StrictModel):
    version: int = Field(ge=1, strict=True)
