"""Definiciones inmutables; describir una herramienta no habilita su uso."""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class CardDefinition:
    id: str
    name: str
    kind: str
    groups: tuple[tuple[str, ...], ...] = ()
    tools: tuple[str, ...] = ()
    gold: bool = False


@dataclass(frozen=True)
class Card:
    id: str
    type: str


_PATHS = (
    ('straight-v', 'Recta vertical', 'NS', 3),
    ('straight-h', 'Recta horizontal', 'EW', 2),
    ('bend-se', 'Curva inferior derecha', 'SE', 3),
    ('bend-sw', 'Curva inferior izquierda', 'SW', 4),
    ('tee-e', 'Cruce vertical', 'NSE', 4),
    ('tee-n', 'Cruce horizontal', 'NEW', 4),
    ('cross', 'Cruce completo', 'NESW', 3),
    ('dead-s', 'Fondo de saco vertical', 'S', 1),
    ('dead-w', 'Fondo de saco horizontal', 'W', 1),
    ('dead-v', 'Recta vertical cortada', 'NS', 1),
    ('dead-h', 'Recta horizontal cortada', 'EW', 1),
    ('dead-se', 'Curva derecha cortada', 'SE', 1),
    ('dead-sw', 'Curva izquierda cortada', 'SW', 1),
    ('dead-tee-e', 'Cruce vertical cortado', 'NSE', 1),
    ('dead-tee-n', 'Cruce horizontal cortado', 'NEW', 1),
    ('dead-cross', 'Cruce completo cortado', 'NESW', 1),
)
_definitions = [
    CardDefinition(id, name, 'path',
                   tuple((e,) for e in edges) if id.startswith('dead-')
                   else (tuple(edges),))
    for id, name, edges, _ in _PATHS
]
for _effect in ('break', 'repair'):
    for _tool, _name in (('pick', 'pico'), ('lamp', 'lámpara'), ('cart', 'vagoneta')):
        _definitions.append(CardDefinition(
            f'{_effect}-{_tool}', f'{_effect} {_name}', _effect, tools=(_tool,)))
for _tools in (('pick', 'lamp'), ('pick', 'cart'), ('lamp', 'cart')):
    _definitions.append(CardDefinition('repair-' + '-'.join(_tools),
                                       'Reparación doble', 'repair', tools=_tools))
_definitions.extend((
    CardDefinition('map', 'Mapa', 'map'),
    CardDefinition('rockfall', 'Derrumbe', 'rockfall'),
    CardDefinition('start', 'Entrada', 'start', (tuple('NESW'),)),
    CardDefinition('gold', 'Tesoro', 'goal', (tuple('NESW'),), gold=True),
    CardDefinition('stone-a', 'Piedra curva izquierda', 'goal', (tuple('NW'),)),
    CardDefinition('stone-b', 'Piedra curva derecha', 'goal', (tuple('SW'),)),
))
CARDS = MappingProxyType({c.id: c for c in _definitions})
DECK_COUNTS = tuple((id, n) for id, _, _, n in _PATHS) + (
    ('map', 3), ('rockfall', 3), ('break-pick', 5), ('repair-pick', 4))
ENABLED_TYPES = frozenset(id for id, _ in DECK_COUNTS)


def create_deck():
    types = [id for id, count in DECK_COUNTS for _ in range(count)]
    return [Card(f'c{i:03}', type) for i, type in enumerate(types, 1)]
