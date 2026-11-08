"""Datos privados del motor y preparación versionada setup-v1."""

from dataclasses import dataclass, field
import platform
import random

from .cards import Card, create_deck

GOALS = ((8, -2), (8, 0), (8, 2))
ENGINE_VERSION = 'development-on-c4f0f9a-uncommitted'


@dataclass
class Tile:
    card: Card
    x: int
    y: int
    rotation: int = 0
    revealed: bool = True


@dataclass
class PlayerState:
    id: int
    role: str
    hand: list[Card] = field(default_factory=list)
    pick_ok: bool = True
    inspections: dict[tuple[int, int], str] = field(default_factory=dict)


@dataclass
class GameState:
    players: list[PlayerState]
    board: dict[tuple[int, int], Tile]
    deck: list[Card] = field(default_factory=list)
    retired: list[Card] = field(default_factory=list)
    active: int = 0
    turn: int = 1
    status: str = 'playing'
    result: dict | None = None
    interruption: str | None = None
    setup: dict = field(default_factory=lambda: {'procedure': 'explicit-test'})


def new_game(saboteurs, seed):
    if type(saboteurs) is not int or saboteurs not in (0, 1):
        raise ValueError('saboteurs debe ser el entero 0 o 1')
    if type(seed) is not int:
        raise ValueError('seed debe ser entero')
    rng = random.Random(seed)
    roles = ['miner'] * (5 - saboteurs) + ['saboteur'] * saboteurs
    rng.shuffle(roles)
    destinations = ['gold', 'stone-a', 'stone-b']
    rng.shuffle(destinations)
    starter = rng.randrange(5)
    deck = create_deck()
    rng.shuffle(deck)
    players = [PlayerState(i, role) for i, role in enumerate(roles)]
    for _ in range(6):
        for j in range(5):
            players[(starter + j) % 5].hand.append(deck.pop())
    board = {(0, 0): Tile(Card('start', 'start'), 0, 0)}
    for i, ((x, y), type_) in enumerate(zip(GOALS, destinations)):
        board[x, y] = Tile(Card(f'goal-{i}', type_), x, y, revealed=False)
    return GameState(players, board, deck, active=starter, setup={
        'procedure': 'setup-v1', 'seed': seed, 'saboteurs': saboteurs,
        'rules': 'experimental-v1', 'deck': 'pilot-47-v1',
        'engine': ENGINE_VERSION, 'code_reference': ENGINE_VERSION,
        'run_kind': 'development', 'python': platform.python_version(),
        'implementation': platform.python_implementation(),
    })
