"""Muestra en directo la información pública de la partida."""

from .board import port_notation
from .cards import CARDS

LEGEND = (
    'Tablero (x, y). El este está a la derecha y el sur hacia abajo.\n'
    'I entrada, ? destino oculto, $ oro, P piedra, . hueco.\n'
    'La entrada y el oro abren por los cuatro lados. P muestra las bocas de la piedra.\n'
    'N, E, S, W indican bocas. Una barra separa ramales sin conexión.'
)


def _symbol(tile: dict) -> str:
    if tile.get('hidden'):
        return '?'
    card_type = tile['type']
    definition = CARDS[card_type]
    if definition.kind == 'start':
        return 'I'
    ports = port_notation(card_type, tile['rotation'])
    if definition.kind == 'goal':
        return '$' if definition.gold else f'P:{ports}'
    return ports


def _show_board(board: list[dict]) -> None:
    cells = {(tile['x'], tile['y']): _symbol(tile) for tile in board}
    xs, ys = zip(*cells)
    columns = range(min(xs), max(xs) + 1)
    print(' y\\x' + ''.join(f'{x:>8}' for x in columns))
    for y in range(min(ys), max(ys) + 1):
        print(f'{y:>4}' + ''.join(f'{cells.get((x, y), "."):>8}' for x in columns))


def show_event(event: dict) -> None:
    """Recibe solo eventos públicos del controlador."""
    kind = event['kind']
    if kind == 'turn':
        print(f"\nTurno {event['turn']}. Minero activo {event['active']}.")
        print('Orden de conversación ' + ', '.join(map(str, event['speaker_order'])))
        _show_board(event['board'])
        print(flush=True)
        return
    if kind == 'speech':
        text = event['text']
        if text is not None:
            text = ''.join(character if character.isprintable() else ' ' for character in text)
        message = f"Minero {event['speaker']}: {text if text is not None else '(silencio)'}"
    elif kind in ('place', 'reveal'):
        name = CARDS[event['type']].name
        position = (event['x'], event['y'])
        detail = f'{name} en {position} con giro de {event["rotation"]}°.'
        if kind == 'place':
            message = f"Minero {event['actor']} coloca {detail}"
        else:
            message = f'Se revela {detail}'
    elif kind in ('inspect', 'rockfall'):
        effect = 'inspecciona en privado' if kind == 'inspect' else 'retira el túnel de'
        message = f"Minero {event['actor']} {effect} ({event['x']}, {event['y']})."
    elif kind in ('break', 'repair'):
        effect = 'rompe' if kind == 'break' else 'repara'
        message = f"Minero {event['actor']} {effect} el pico del minero {event['target']}."
    elif kind == 'automatic-discard':
        message = 'Se aplica un descarte automático tras dos respuestas inválidas.'
    elif kind == 'discard':
        message = f"Minero {event['actor']} descarta una carta."
    elif kind == 'draw':
        message = f"Minero {event['actor']} roba una carta."
    elif kind == 'result':
        message = ('Victoria. Los mineros conectaron la entrada con el oro.'
                   if event['miners_success'] else
                   'Derrota. Se agotaron las cartas antes de alcanzar el oro.')
    else:
        raise ValueError(f'Evento público desconocido: {kind}')
    print(message, flush=True)
