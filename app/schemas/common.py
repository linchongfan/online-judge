from pydantic import AliasGenerator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiSchema(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        alias_generator=AliasGenerator(validation_alias=to_camel, serialization_alias=to_camel),
        use_enum_values=False,
    )


class Page[T](ApiSchema):
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    pages: int = Field(ge=0)


def make_page[T](items: list[T], total: int, page: int, page_size: int) -> Page[T]:
    return Page(items=items, total=total, page=page, page_size=page_size, pages=(total + page_size - 1) // page_size)


class MessageResponse(ApiSchema):
    message: str
