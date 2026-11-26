"""Схемы сообщений WebSocket-протокола.

Клиент -> сервер валидируются pydantic-моделями (античит: никаких доверенных полей).
Сервер -> клиент собираются функцией build().

Клиент -> сервер:
  create_lobby {name}                    join_lobby {name, code}
  reconnect {code, token}                start_game
  place_ship {x,y,size,orientation}      ready
  shoot {x,y}                            buy_gadget {kind,size}
  use_gadget {item_id,x,y}               place_purchased_ship {item_id,x,y,orientation}
  leave

Сервер -> клиент:
  lobby_created {code, token, state}     lobby_joined {code, token, state}
  opponent_joined {name, state}          state_update {state}
  shot_result {by, cells, hit, sunk, gained}
  game_over {winner, reason}             error {message, code}
"""
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from game.constants import BOARD_SIZE, MAX_NAME_LEN

Coord = Annotated[int, Field(strict=True, ge=0, lt=BOARD_SIZE)]
Size = Annotated[int, Field(strict=True, ge=1, le=20)]
ItemId = Annotated[int, Field(strict=True, ge=1)]
Orientation = Literal["h", "v"]


class _Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")   # лишние поля = ошибка


class CreateLobby(_Msg):
    type: Literal["create_lobby"]
    name: str = Field(min_length=1, max_length=MAX_NAME_LEN * 3)


class JoinLobby(_Msg):
    type: Literal["join_lobby"]
    name: str = Field(min_length=1, max_length=MAX_NAME_LEN * 3)
    code: str = Field(min_length=1, max_length=16)


class Reconnect(_Msg):
    type: Literal["reconnect"]
    code: str = Field(max_length=16)
    token: str = Field(max_length=128)


class StartGame(_Msg):
    type: Literal["start_game"]


class PlaceShip(_Msg):
    type: Literal["place_ship"]
    x: Coord
    y: Coord
    thick: Size      # толщина корабля
    length: Size     # длина корабля
    orientation: Orientation

class Ready(_Msg):
    type: Literal["ready"]


class Shoot(_Msg):
    type: Literal["shoot"]
    x: Coord
    y: Coord


class BuyGadget(_Msg):
    type: Literal["buy_gadget"]
    kind: Literal["scan", "area_shot", "ship"]
    w: Annotated[int, Field(strict=True, ge=1, le=BOARD_SIZE)]   # ширина области / длина корабля
    h: Annotated[int, Field(strict=True, ge=1, le=BOARD_SIZE)]   # высота области (для корабля 1)

class UseGadget(_Msg):
    type: Literal["use_gadget"]
    item_id: ItemId
    x: Coord
    y: Coord
    rotated: bool = False   # область повёрнута (ширина и высота меняются местами)


class PlacePurchasedShip(_Msg):
    type: Literal["place_purchased_ship"]
    item_id: ItemId
    x: Coord
    y: Coord
    orientation: Orientation


class LeaveLobby(_Msg):
    type: Literal["leave"]


ClientMessage = Annotated[
    Union[CreateLobby, JoinLobby, Reconnect, StartGame, PlaceShip, Ready, Shoot,
          BuyGadget, UseGadget, PlacePurchasedShip, LeaveLobby],
    Field(discriminator="type"),
]
_adapter = TypeAdapter(ClientMessage)


def parse_client_message(data: Any) -> BaseModel:
    """Бросает ValueError (pydantic.ValidationError — его наследник) при любой ошибке."""
    return _adapter.validate_python(data)


# ---- типы сообщений сервера ----
S_LOBBY_CREATED = "lobby_created"
S_LOBBY_JOINED = "lobby_joined"
S_OPPONENT_JOINED = "opponent_joined"
S_STATE = "state_update"
S_SHOT_RESULT = "shot_result"
S_GAME_OVER = "game_over"
S_ERROR = "error"


def build(type_: str, **payload: Any) -> dict:
    return {"type": type_, **payload}
