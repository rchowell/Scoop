from fastapi import APIRouter

from api.connector import FACTORIES, ConnectorFactory
from models import (
    ConnectorKind,
    ConnectorKindInfo,
    ConnectorKindList,
    ConnectorOption,
    OptionType,
)

router = APIRouter(prefix="/v1/connections", tags=["connectors"])

_OPTION_TYPES = {
    str: OptionType.STRING,
    int: OptionType.INTEGER,
    bool: OptionType.BOOLEAN,
}


def _info(factory: ConnectorFactory) -> ConnectorKindInfo:
    return ConnectorKindInfo(
        kind=ConnectorKind(factory.kind()),
        name=factory.name(),
        options=[
            ConnectorOption(
                name=key,
                type=_OPTION_TYPES[option.type],
                description=option.description,
                required=option.required,
                default=option.default,
                secret=option.secret,
            )
            for key, option in factory.options().items()
        ],
    )


@router.get("")
def list_connector_kinds() -> ConnectorKindList:
    return ConnectorKindList(kinds=[_info(f) for f in FACTORIES.values()])
