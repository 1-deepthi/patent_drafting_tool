from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Individual / Startup / Company / University — kept as free string on the
# model (not a DB enum) so new applicant types don't need a migration, but
# validated to this closed set at the API boundary.
APPLICANT_TYPES = ("Individual", "Startup", "Company", "University")


class ApplicantCreate(BaseModel):
    applicant_type: str = Field(pattern="^(" + "|".join(APPLICANT_TYPES) + ")$")
    full_name_or_org_name: str = Field(min_length=1, max_length=300)
    address: str | None = None
    country: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=20)
    is_primary: bool = False


class ApplicantUpdate(BaseModel):
    applicant_type: str = Field(pattern="^(" + "|".join(APPLICANT_TYPES) + ")$")
    full_name_or_org_name: str = Field(min_length=1, max_length=300)
    address: str | None = None
    country: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=20)
    is_primary: bool = False


class ApplicantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patent_application_id: int
    applicant_type: str
    full_name_or_org_name: str
    address: str | None
    country: str | None
    postal_code: str | None
    email: str | None
    phone: str | None
    is_primary: bool
    display_order: int


class InventorCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    address: str | None = None
    country: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=20)
    user_id: int | None = None  # link to a platform account, if the inventor has one


class InventorUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    address: str | None = None
    country: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=20)
    user_id: int | None = None


class InventorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patent_application_id: int
    user_id: int | None
    full_name: str
    address: str | None
    country: str | None
    postal_code: str | None
    email: str | None
    phone: str | None
    inventor_order: int


class ReorderRequest(BaseModel):
    """Full ordered list of IDs — simplest, least error-prone way to express
    a reorder over an API (no partial "move index 2 to index 0" math to get
    wrong client- or server-side)."""

    ordered_ids: list[int] = Field(min_length=1)
