"""Prototipo descartable de latencia y elección. Ejecutar con PYTHONPATH=src."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter

import httpx

from saboteurai.board import DIRECTIONS, port_notation
from saboteurai.cards import Card
from saboteurai.controller import INSTRUCTIONS, _TASKS, _action_number
from saboteurai.engine import apply_action
from saboteurai.records import miner_view, start_record
from saboteurai.state import Tile, new_game


def near_gold():
    state = new_game(0, 11)
    state.active = 0
    for pos, tile in state.board.items():
        if pos[0] == 8:
            tile.card = Card(tile.card.id, {
                -2: 'stone-a', 0: 'gold', 2: 'stone-b',
            }[pos[1]])
    for x in range(1, 7):
        state.board[x, 0] = Tile(Card(f'test-path-{x}', 'straight-h'), x, 0)
    state.players[0].hand = [
        Card('test-bad', 'dead-w'), Card('test-good', 'straight-h'),
        Card('test-break', 'break-pick'), Card('test-map', 'map'),
    ]
    state.players[0].inspections = {(8, 0): 'gold'}
    return state


def run(client, name, model, query, *, num_predict, allowed=None):
    prompt = {key: value for key, value in query.items() if key != 'instructions'}
    body = {
        'model': model if model.endswith(':local') else f'{model}:local',
        'stream': False, 'truncate': False, 'shift': False, 'think': False,
        'messages': [
            {'role': 'system', 'content': query['instructions']},
            {'role': 'user', 'content': json.dumps(prompt, ensure_ascii=False, separators=(',', ':'))},
        ],
        'options': {'num_ctx': 65536, 'num_predict': num_predict, 'seed': 42, 'temperature': 0},
    }
    if allowed is not None:
        body['format'] = {'type': 'integer', 'enum': allowed}
    started = perf_counter()
    try:
        result = client.post('/api/chat', json=body)
        result.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as error:
        print(json.dumps(dict(case=name, error=type(error).__name__,
                              seconds=round(perf_counter() - started, 3))), flush=True)
        return None
    data = result.json()
    answer = data['message']['content']
    output = {'case': name, 'seconds': round(perf_counter() - started, 3), 'reply': answer}
    for field in ('prompt_eval_count', 'eval_count', 'load_duration',
                  'prompt_eval_duration', 'eval_duration', 'done_reason'):
        output[field] = data.get(field)
    print(json.dumps(output, ensure_ascii=False), flush=True)
    return answer


def compact(query):
    query = deepcopy(query)
    query['observation']['public_messages'] = query['observation']['public_messages'][-5:]
    query['observation']['public_actions'] = query['observation']['public_actions'][-10:]
    return query


def action_sheet(state, view, actions, *, show_links):
    """Presenta hechos observables y el mismo orden de acciones."""
    hand = {card['id']: card['type'] for card in view['hand']}
    board = ', '.join(f'({tile.x},{tile.y}) {port_notation(tile.card.type, tile.rotation)}'
                      for tile in state.board.values() if tile.revealed)
    inspected = {(i['x'], i['y']): i['type'] for i in view['inspections']}
    goals = ', '.join(f'({tile["x"]},{tile["y"]}) '
                      f'{inspected.get((tile["x"], tile["y"]), "desconocido")}'
                      for tile in view['board'] if tile.get('hidden'))
    options = []
    for number, action in enumerate(actions, 1):
        kind = action['kind']
        card_type = hand[action['card_id']]
        if kind == 'place':
            x, y = action['x'], action['y']
            ports = port_notation(card_type, action['rotation'])
            description = f'Colocar {ports} en ({x},{y})'
            if show_links:
                groups = []
                for group in ports.split('/'):
                    neighbors = [(x + DIRECTIONS[port][0], y + DIRECTIONS[port][1])
                                 for port in group]
                    if len(neighbors) > 1:
                        groups.append(' conecta ' + ' con '.join(f'({nx},{ny})' for nx, ny in neighbors))
                description += ','.join(groups) if groups else ' sin paso entre casillas'
        elif kind == 'inspect':
            description = f'Inspeccionar ({action["x"]},{action["y"]})'
        elif kind == 'break':
            description = f'Romper pico del minero {action["target"]}'
        else:
            description = f'Descartar {card_type}'
        options.append(f'{number}. {description}')
    return dict(
        instructions=(
            'Sois cinco mineros. Ganáis al conectar con un túnel continuo '
            'la entrada (0,0) con el destino que contiene oro (gold). '
            'Las coordenadas crecen al este (x) y al sur (y). '
            'N/E/S/W son las bocas de cada túnel. Las bocas del mismo grupo '
            'se conectan entre sí. Una barra separa grupos desconectados. '
            'Elige una de las acciones legales. Devuelve solo su número.'
        ),
        tablero=board, destinos=goals, opciones=options,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('episode', type=Path, nargs='?')
    parser.add_argument('--model', default='llama3.1:8b')
    parser.add_argument('--turn', type=int, default=9)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--representation-only', action='store_true')
    mode.add_argument('--action-sheet-only', action='store_true')
    parser.add_argument('--show-links', action='store_true')
    args = parser.parse_args()
    history_query = None
    if not (args.representation_only or args.action_sheet_only):
        if args.episode is None:
            parser.error('se necesita un episodio para comparar el historial')
        episode = json.loads(args.episode.read_text())
        turn = next(turn for turn in episode['turns'] if turn['turn'] == args.turn)
        history_query = turn['speeches'][1]['calls'][0]['query']

    with httpx.Client(base_url='http://127.0.0.1:11434', timeout=32, trust_env=False) as client:
        warmup = dict(instructions='Responde con 1.', phase='warmup', observation={})
        if run(client, 'calentamiento', args.model, warmup, num_predict=4) is None:
            return 1
        if history_query is not None:
            run(client, 'historial completo', args.model, history_query, num_predict=96)
            run(client, 'ventana 5 mensajes / 10 eventos', args.model, compact(history_query),
                num_predict=96)

        state = near_gold()
        observation = miner_view(start_record(state, {'episode': 'probe'}), state.active)
        actions = observation['legal_actions']
        winning = [i for i, action in enumerate(actions, 1)
                   if (apply_action(state, state.active, action).state.result or {}).get('miners_success')]
        print(json.dumps({'acciones': len(actions), 'indices_de_victoria': winning}), flush=True)
        if args.action_sheet_only:
            winning_actions = [actions[i - 1] for i in winning]
            for variant in (actions, list(reversed(actions))):
                indices = [i for i, action in enumerate(variant, 1) if action in winning_actions]
                answer = run(client, 'ficha de acción', args.model,
                             action_sheet(state, observation, variant, show_links=args.show_links),
                             num_predict=12, allowed=list(range(1, len(variant) + 1)))
                choice = int(answer) if answer and answer.strip().isdigit() else 0
                print(json.dumps({'winning': indices, 'choice': choice,
                                  'victory': choice in indices}), flush=True)
            return 0
        query = dict(instructions=INSTRUCTIONS, phase='act', task=_TASKS['act'],
                     observation=observation, feedback=None, previous_response=None)
        cases = (
            [('esquema y numeración', True, True, False),
             ('esquema y representación explícita', True, True, True)]
            if args.representation_only else
            [('acción actual', False, False, False),
             ('acción numerada', True, False, False),
             ('acción numerada con esquema', True, True, False)]
        )
        for name, explicit, constrained, descriptive in cases:
            probe = deepcopy(query)
            view = probe['observation']
            if explicit:
                view['legal_actions'] = [
                    {'number': number, **action} for number, action in enumerate(actions, 1)
                ]
            if descriptive:
                probe['task'] = (
                    'Elige el número de una acción legal. Los destinos inspeccionados en privado '
                    'aparecen con su contenido conocido. La victoria ocurre al conectar '
                    'la entrada y el destino que contiene oro mediante un túnel continuo.'
                )
                hand = {card['id']: card['type'] for card in view['hand']}
                for action in view['legal_actions']:
                    card_type = hand[action['card_id']]
                    action['card_type'] = card_type
                    if action['kind'] == 'place':
                        action['oriented_ports'] = port_notation(card_type, action['rotation'])
                for tile in view['board']:
                    if not tile.get('hidden'):
                        tile['oriented_ports'] = port_notation(tile['type'], tile['rotation'])
            reply = run(client, name, args.model, probe, num_predict=96 if not constrained else 12,
                        allowed=list(range(1, len(actions) + 1)) if constrained else None)
            number = _action_number(reply or '')
            choice = int(number) if number else 0
            print(json.dumps({'case': name, 'valid': 1 <= choice <= len(actions),
                              'victory': choice in winning}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
