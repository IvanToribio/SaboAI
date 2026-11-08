"""Conectividad por puertos: una casilla cortada no une sus ramales."""

from .cards import CARDS
from .state import GOALS, Tile

DIRECTIONS = {'N': (0, -1), 'E': (1, 0), 'S': (0, 1), 'W': (-1, 0)}
OPPOSITE = {'N': 'S', 'E': 'W', 'S': 'N', 'W': 'E'}


def hidden(tile):
    return CARDS[tile.card.type].kind == 'goal' and not tile.revealed


def groups_for(tile):
    if type(tile.rotation) is not int or tile.rotation not in (0, 180):
        raise ValueError('rotation debe ser 0 o 180')
    return tuple(tuple(OPPOSITE[e] if tile.rotation == 180 else e for e in group)
                 for group in CARDS[tile.card.type].groups)


def edges_for(tile):
    return frozenset(e for group in groups_for(tile) for e in group)


def reachable_ports(state):
    seen = set()
    queue = [((0, 0), 'N')]
    while queue:
        pos, port = queue.pop()
        if (pos, port) in seen:
            continue
        tile = state.board.get(pos)
        if tile is None or hidden(tile):
            continue
        group = next((g for g in groups_for(tile) if port in g), ())
        if not group:
            continue
        seen.add((pos, port))
        for edge in group:
            if (pos, edge) not in seen:
                queue.append((pos, edge))
            dx, dy = DIRECTIONS[edge]
            neighbor_pos = (pos[0] + dx, pos[1] + dy)
            neighbor = state.board.get(neighbor_pos)
            if (neighbor is not None and not hidden(neighbor)
                    and OPPOSITE[edge] in edges_for(neighbor)):
                if (neighbor_pos, OPPOSITE[edge]) not in seen:
                    queue.append((neighbor_pos, OPPOSITE[edge]))
    return seen


def candidate_cells(state):
    return sorted({(x + dx, y + dy) for x, y in state.board
                   for dx, dy in DIRECTIONS.values()
                   if (x + dx, y + dy) not in state.board})


def placement_error(state, card, x, y, rotation):
    if type(x) is not int or type(y) is not int:
        return 'coordinates'
    if type(rotation) is not int or rotation not in (0, 180):
        return 'rotation'
    if CARDS[card.type].kind != 'path':
        return 'card-effect'
    if (x, y) in state.board:
        return 'occupied'
    edges = edges_for(Tile(card, x, y, rotation))
    ports = reachable_ports(state)
    connected = False
    for edge, (dx, dy) in DIRECTIONS.items():
        pos = (x + dx, y + dy)
        neighbor = state.board.get(pos)
        if neighbor is None or hidden(neighbor):
            continue
        opened = edge in edges
        if opened != (OPPOSITE[edge] in edges_for(neighbor)):
            return 'mismatch'
        if opened and (pos, OPPOSITE[edge]) in ports:
            connected = True
    return None if connected else 'unreachable'


def reveal_goals(state):
    """Muta solo la copia de transición; devuelve oro y eventos de revelación."""
    events = []
    changed = True
    while changed:
        changed = False
        # Igual que revealGoals: alcance fijo por pasada, no por destino.
        ports = reachable_ports(state)
        for pos in GOALS:
            tile = state.board.get(pos)
            if tile is None or not hidden(tile):
                continue
            entering = []
            neighbors = []
            for edge, (dx, dy) in DIRECTIONS.items():
                npos = (tile.x + dx, tile.y + dy)
                neighbor = state.board.get(npos)
                if neighbor is not None and not hidden(neighbor):
                    neighbors.append((edge, neighbor))
                    if (npos, OPPOSITE[edge]) in ports:
                        entering.append(edge)
            if not entering:
                continue
            choices = []
            for rotation in (0, 180):
                edges = edges_for(Tile(tile.card, tile.x, tile.y, rotation))
                if any(e in edges for e in entering):
                    matches = sum((e in edges) == (OPPOSITE[e] in edges_for(n))
                                  for e, n in neighbors)
                    choices.append((matches, -rotation, rotation))
            tile.rotation = max(choices)[2]
            tile.revealed = True
            changed = True
            events.append({'kind': 'reveal', 'x': tile.x, 'y': tile.y,
                           'type': tile.card.type, 'rotation': tile.rotation})
            if CARDS[tile.card.type].gold:
                return True, events
    return False, events
