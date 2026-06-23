from typing import Annotated

from pydantic import Field

InstanceName = Annotated[
    str | None,
    Field(
        description=(
            "TB instance key. Required when multiple TimeBase instances are configured."
        )
    ),
]
