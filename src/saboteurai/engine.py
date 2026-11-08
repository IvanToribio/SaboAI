"""Validación estricta y transiciones puras. Resolution.state es privado."""

from copy import deepcopy
from dataclasses import dataclass, field
import math

from .cards import CARDS, ENABLED_TYPES
from .state import GameState, Tile
from .board import (candidate_cells, hidden, placement_error, reveal_goals)

SCHEMAS = {
    'place': {'x': int, 'y': int, 'rotation': int},
    'inspect': {'x': int, 'y': int},
    'rockfall': {'x': int, 'y': int},
    'break': {'target': int, 'tool': str},
    'repair': {'target': int, 'tool': str},
    'discard': {},
}
INTERRUPTION_CODES = ('technical-failure', 'io-failure', 'manual-stop', 'test-stop')


@dataclass(frozen=True)
class Action:
    kind: str
    actor: int
    card_id: str
    arguments: dict


@dataclass(frozen=True)
class ActionError:
    code: str


@dataclass
class Resolution:
    accepted: bool
    error: str | None
    state: GameState
    public_events: list = field(default_factory=list)
    private_events: dict = field(default_factory=dict)


def is_json(value):
    """Solo valores JSON exactos; también rechaza ciclos y NaN sin repr."""
    # La profundidad de una solicitud inválida no debe consumir la pila Python.
    ancestors = set()
    pending = [(value, False)]
    while pending:
        item, leaving = pending.pop()
        if leaving:
            ancestors.remove(id(item))
            continue
        if item is None or type(item) in (str, bool, int):
            continue
        if type(item) is float:
            if not math.isfinite(item):
                return False
            continue
        if type(item) not in (list, dict) or id(item) in ancestors:
            return False
        if type(item) is dict and any(type(k) is not str for k in item):
            return False
        ancestors.add(id(item))
        pending.append((item, True))
        children = item.values() if type(item) is dict else item
        pending.extend((child, False) for child in children)
    return True


def validate_action(state, actor, request):
    if not is_json(request):
        return ActionError('format')
    if type(actor) is not int or actor not in range(5):
        return ActionError('actor')
    if state.status != 'playing':
        return ActionError('not-playing')
    if actor != state.active:
        return ActionError('out-of-turn')
    if type(request) is not dict:
        return ActionError('schema')
    kind = request.get('kind')
    if type(kind) is not str or kind not in SCHEMAS:
        return ActionError('kind')
    schema = {'kind': str, 'card_id': str, **SCHEMAS[kind]}
    if set(request) != set(schema) or any(type(request[k]) is not t for k, t in schema.items()):
        return ActionError('schema')
    player = state.players[actor]
    card = next((c for c in player.hand if c.id == request['card_id']), None)
    if card is None:
        return ActionError('card-unavailable')
    if kind != 'discard':
        if card.type not in ENABLED_TYPES:
            return ActionError('card-effect')
        expected = {'place': 'path', 'inspect': 'map'}.get(kind, kind)
        if CARDS[card.type].kind != expected:
            return ActionError('card-effect')
    if kind == 'place':
        if not player.pick_ok:
            return ActionError('pick-broken')
        error = placement_error(state, card, request['x'], request['y'], request['rotation'])
        if error:
            return ActionError(error)
    elif kind in ('inspect', 'rockfall'):
        target = state.board.get((request['x'], request['y']))
        if kind == 'inspect' and (target is None or not hidden(target)):
            return ActionError('hidden-goal-required')
        if kind == 'rockfall' and (target is None or CARDS[target.card.type].kind != 'path'):
            return ActionError('path-required')
    elif kind in ('break', 'repair'):
        target = request['target']
        if target not in range(5):
            return ActionError('target')
        if request['tool'] != 'pick':
            return ActionError('tool')
        if kind == 'break' and (target == actor or not state.players[target].pick_ok):
            return ActionError('damage-target')
        if kind == 'repair' and state.players[target].pick_ok:
            return ActionError('repair-target')
    return Action(kind, actor, card.id,
                  {k: request[k] for k in SCHEMAS[kind]})


def legal_actions(state, actor):
    if type(actor) is not int or actor not in range(5) or actor != state.active or state.status != 'playing':
        return []
    result = []
    for card in state.players[actor].hand:
        for kind in SCHEMAS:
            arguments = []
            if kind == 'place':
                arguments = [dict(x=x, y=y, rotation=r)
                             for x, y in candidate_cells(state) for r in (0, 180)]
            elif kind in ('inspect', 'rockfall'):
                arguments = [dict(x=x, y=y) for x, y in sorted(state.board)]
            elif kind in ('break', 'repair'):
                arguments = [dict(target=t, tool='pick') for t in range(5)]
            else:
                arguments = [{}]
            for args in arguments:
                request = dict(kind=kind, card_id=card.id, **args)
                if isinstance(validate_action(state, actor, request), Action):
                    result.append(request)
    return result


def _finish(state, gold, events):
    state.status = 'finished'
    state.result = {'miners_success': gold, 'reason': 'gold' if gold else 'empty',
                    'saboteur_wins': not gold and any(p.role == 'saboteur' for p in state.players)}
    events.append({'kind': 'result', 'miners_success': gold,
                   'reason': state.result['reason']})


def apply_action(state, actor, request):
    action = validate_action(state, actor, request)
    if isinstance(action, ActionError):
        return Resolution(False, action.code, deepcopy(state))
    s = deepcopy(state)
    player = s.players[actor]
    card = next(c for c in player.hand if c.id == action.card_id)
    player.hand.remove(card)
    args = action.arguments
    kind = action.kind
    event = {'kind': kind, 'actor': actor}
    public = [event]
    private = {}
    gold = False
    if kind == 'place':
        x, y, rotation = args['x'], args['y'], args['rotation']
        s.board[x, y] = Tile(card, x, y, rotation)
        event.update(x=x, y=y, rotation=rotation, type=card.type)
        gold, reveals = reveal_goals(s)
        public.extend(reveals)
    else:
        s.retired.append(card)
        if kind == 'inspect':
            pos = args['x'], args['y']
            type_ = s.board[pos].card.type
            player.inspections[pos] = type_
            event.update(x=pos[0], y=pos[1])
            private[actor] = [{'kind': 'inspection', 'x': pos[0], 'y': pos[1], 'type': type_}]
        elif kind == 'rockfall':
            pos = args['x'], args['y']
            s.retired.append(s.board.pop(pos).card)
            event.update(x=pos[0], y=pos[1])
        elif kind in ('break', 'repair'):
            s.players[args['target']].pick_ok = kind == 'repair'
            event.update(target=args['target'], tool='pick')
    if gold:
        _finish(s, True, public)
    else:
        if s.deck:
            drawn = s.deck.pop()
            player.hand.append(drawn)
            public.append({'kind': 'draw', 'actor': actor})
            private.setdefault(actor, []).append({'kind': 'draw', 'card': {'id': drawn.id, 'type': drawn.type}})
        if not any(p.hand for p in s.players):
            _finish(s, False, public)
        else:
            s.active = next((actor + j) % 5 for j in range(1, 6)
                            if s.players[(actor + j) % 5].hand)
            s.turn += 1
    return Resolution(True, None, s, public, private)


def interrupt_game(state, code):
    if state.status != 'playing':
        raise ValueError('Solo se interrumpe una ronda en curso')
    # Código técnico, no texto arbitrario que pueda contener credenciales.
    if type(code) is not str or code not in INTERRUPTION_CODES:
        raise ValueError('Código de interrupción desconocido')
    s = deepcopy(state)
    s.status = 'interrupted'
    s.interruption = code
    s.result = None
    return s
