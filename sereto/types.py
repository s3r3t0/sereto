from typing import Annotated

from pydantic import Field

TypeReportId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9._-]{1,20}$")]
TypePathName = Annotated[str, Field(pattern=r"^[a-zA-Z0-9._-]{1,100}$")]
TypeCategories = set[TypeReportId]
