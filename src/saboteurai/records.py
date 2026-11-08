"""Registro exclusivo del evaluador. No es un contexto para jugadores."""

from copy import deepcopy
import json
import os
from pathlib import Path
import platform
import stat
import tempfile

from .cards import Card, CARDS
from .state import GameState, PlayerState, Tile, ENGINE_VERSION
from .board import hidden, reachable_ports
from .engine import apply_action, interrupt_game, is_json, INTERRUPTION_CODES


def _copy_json(value):
    """Copia contenedores JSON sin deepcopy recursivo ni alias de entrada."""
    if not is_json(value):
        raise ValueError('Valor no JSON')
    root = [None]
    pending = [(value, root, 0)]
    while pending:
        source, parent, key = pending.pop()
        if type(source) is dict:
            target = {}
            pending.extend((v, target, k) for k, v in source.items())
        elif type(source) is list:
            target = [None] * len(source)
            pending.extend((v, target, i) for i, v in enumerate(source))
        else:
            target = source
        parent[key] = target
    return root[0]


def _json_text(value):
    """JSON canónico: pila explícita para contenedores, stdlib para escalares.

    No cambia record-v1 ni resume solicitudes profundas. También evita que
    comparar/guardar el registro vuelva a introducir el fallo de recursión.
    """
    if not is_json(value):
        raise ValueError('Valor no JSON')
    pieces = []
    pending = [(value, False)]
    while pending:
        item, literal = pending.pop()
        if literal:
            pieces.append(item)
        elif type(item) in (dict, list):
            is_object = type(item) is dict
            pieces.append('{' if is_object else '[')
            pending.append(('}' if is_object else ']', True))
            entries = sorted(item.items()) if is_object else list(enumerate(item))
            for i in range(len(entries) - 1, -1, -1):
                key, child = entries[i]
                if i < len(entries) - 1:
                    pending.append((',', True))
                pending.append((child, False))
                if is_object:
                    pending.append((':', True))
                    pending.append((key, False))
        else:
            pieces.append(json.dumps(item, ensure_ascii=False, allow_nan=False))
    return ''.join(pieces)


def _parse_json(text):
    """Lee contenedores con pila explícita; raw_decode lee solo escalares.

    Estados pequeños comprueban separadores, claves duplicadas y cierre;
    escapes, números y literales siguen siendo responsabilidad de json.
    """
    def nonfinite(_):
        raise ValueError('No finito')

    decoder = json.JSONDecoder(parse_constant=nonfinite)
    root = [None]
    stack = [[root, 'root-value', None]]
    pos = 0
    while stack:
        while pos < len(text) and text[pos] in ' \t\r\n':
            pos += 1
        frame = stack[-1]
        container, mode, key = frame
        token = text[pos:pos + 1]
        if mode == 'done':
            if pos != len(text):
                raise ValueError('Datos después de JSON')
            return root[0]
        if not token:
            raise ValueError('JSON incompleto')
        if mode in ('object-first', 'object-key'):
            if mode == 'object-first' and token == '}':
                stack.pop()
                pos += 1
                continue
            if token != '"':
                raise ValueError('Clave JSON debe ser texto')
            key, pos = decoder.raw_decode(text, pos)
            if key in container:
                raise ValueError('Clave JSON duplicada')
            frame[1:3] = ['colon', key]
            continue
        if mode == 'colon':
            if token != ':':
                raise ValueError('Falta dos puntos JSON')
            pos += 1
            frame[1] = 'object-value'
            continue
        if mode in ('object-comma', 'array-comma'):
            if token == ('}' if mode == 'object-comma' else ']'):
                stack.pop()
                pos += 1
            elif token == ',':
                frame[1] = 'object-key' if mode == 'object-comma' else 'array-value'
                pos += 1
            else:
                raise ValueError('Falta separador JSON')
            continue
        if mode == 'array-first' and token == ']':
            stack.pop()
            pos += 1
            continue
        if token in ('{', '['):
            value = {} if token == '{' else []
            pos += 1
            child = [value, 'object-first' if token == '{' else 'array-first', None]
        else:
            value, pos = decoder.raw_decode(text, pos)
            child = None
        if mode == 'root-value':
            container[0] = value
            frame[1] = 'done'
        elif mode == 'object-value':
            container[key] = value
            frame[1] = 'object-comma'
        else:
            container.append(value)
            frame[1] = 'array-comma'
        if child is not None:
            stack.append(child)
    raise ValueError('JSON incompleto')


def public_board(state):
    result = []
    for (x, y), tile in sorted(state.board.items()):
        if hidden(tile):
            result.append({'x': x, 'y': y, 'hidden': True})
        else:
            result.append({'x': x, 'y': y, 'type': tile.card.type,
                           'rotation': tile.rotation})
    return result


def _card(card):
    return {'id': card.id, 'type': card.type}


def state_data(state):
    return {
        'players': [dict(id=p.id, role=p.role, hand=[_card(c) for c in p.hand],
                         pick_ok=p.pick_ok,
                         inspections=[{'x': x, 'y': y, 'type': t}
                                      for (x, y), t in sorted(p.inspections.items())])
                    for p in state.players],
        'board': [dict(card=_card(t.card), x=x, y=y, rotation=t.rotation,
                       revealed=t.revealed) for (x, y), t in sorted(state.board.items())],
        'deck': [_card(c) for c in state.deck],
        'retired': [_card(c) for c in state.retired],
        'active': state.active, 'turn': state.turn, 'status': state.status,
        'result': deepcopy(state.result), 'interruption': state.interruption,
        'setup': deepcopy(state.setup),
    }


def _keys(value, keys):
    if type(value) is not dict or set(value) != set(keys.split()):
        raise ValueError('Esquema de registro inválido')


def _read_card(data):
    _keys(data, 'id type')
    if type(data['id']) is not str or type(data['type']) is not str or data['type'] not in CARDS:
        raise ValueError('Carta inválida')
    return Card(data['id'], data['type'])


def _validate_state_closure(state):
    """Esquema exacto y coherencia reglamentaria básica, no autenticación."""
    if state.status == 'interrupted':
        if (state.result is not None or type(state.interruption) is not str
                or state.interruption not in INTERRUPTION_CODES):
            raise ValueError('Interrupción inconsistente')
        return
    if state.interruption is not None:
        raise ValueError('Interrupción incompatible con el estado')
    if state.status == 'playing':
        if state.result is not None:
            raise ValueError('Ronda en curso con resultado')
        return
    result = state.result
    _keys(result, 'miners_success reason saboteur_wins')
    if (type(result['miners_success']) is not bool
            or type(result['saboteur_wins']) is not bool
            or type(result['reason']) is not str or result['reason'] not in ('gold', 'empty')):
        raise ValueError('Resultado inválido')
    gold = result['reason'] == 'gold'
    saboteur_wins = not gold and any(p.role == 'saboteur' for p in state.players)
    if result['miners_success'] != gold or result['saboteur_wins'] != saboteur_wins:
        raise ValueError('Resultado incompatible con la causa o los roles')
    revealed_gold = [pos for pos, t in state.board.items()
                     if CARDS[t.card.type].gold and t.revealed]
    if gold:
        ports = reachable_ports(state)
        if not any(pos == reached for pos in revealed_gold for reached, _ in ports):
            raise ValueError('Resultado oro sin oro conectado y descubierto')
    elif revealed_gold or state.deck or any(p.hand for p in state.players):
        raise ValueError('Agotamiento incompatible con los recursos o el oro')


def read_state(data):
    _keys(data, 'players board deck retired active turn status result interruption setup')
    if not is_json(data):
        raise ValueError('Estado no JSON')
    players = []
    for p in data['players']:
        _keys(p, 'id role hand pick_ok inspections')
        if (type(p['id']) is not int or p['id'] != len(players)
                or p['role'] not in ('miner', 'saboteur') or type(p['pick_ok']) is not bool):
            raise ValueError('Jugador inválido')
        inspections = {}
        for entry in p['inspections']:
            _keys(entry, 'x y type')
            if type(entry['x']) is not int or type(entry['y']) is not int or entry['type'] not in ('gold', 'stone-a', 'stone-b'):
                raise ValueError('Inspección inválida')
            inspections[entry['x'], entry['y']] = entry['type']
        players.append(PlayerState(p['id'], p['role'], [_read_card(c) for c in p['hand']],
                                   p['pick_ok'], inspections))
    if len(players) != 5:
        raise ValueError('Número de jugadores inválido')
    board = {}
    for t in data['board']:
        _keys(t, 'card x y rotation revealed')
        if (type(t['x']) is not int or type(t['y']) is not int
                or type(t['rotation']) is not int or t['rotation'] not in (0, 180)
                or type(t['revealed']) is not bool):
            raise ValueError('Casilla inválida')
        board[t['x'], t['y']] = Tile(_read_card(t['card']), t['x'], t['y'],
                                     t['rotation'], t['revealed'])
    if (type(data['active']) is not int or data['active'] not in range(5)
            or type(data['turn']) is not int or data['turn'] < 1
            or type(data['status']) is not str or data['status'] not in ('playing', 'finished', 'interrupted')
            or type(data['setup']) is not dict):
        raise ValueError('Estado inválido')
    state = GameState(players, board, [_read_card(c) for c in data['deck']],
                      [_read_card(c) for c in data['retired']], data['active'], data['turn'],
                      data['status'], data['result'], data['interruption'], deepcopy(data['setup']))
    # Rechaza el resultado mal tipado antes de copiarlo: también puede contener
    # contenedores profundos, aunque el resultado válido es siempre plano.
    _validate_state_closure(state)
    state.result = deepcopy(state.result)
    # Exige representación canónica: sin duplicados ni reordenamientos ambiguos.
    if not _same_json(state_data(state), data):
        raise ValueError('Estado no canónico')
    cards = state.deck + state.retired + [c for p in state.players for c in p.hand] + [t.card for t in state.board.values()]
    if len({c.id for c in cards}) != len(cards):
        raise ValueError('Identidad duplicada en el estado')
    return state


def _closure(state):
    return {'status': state.status, 'result': deepcopy(state.result),
            'interruption': state.interruption}


def start_record(state, metadata):
    if type(metadata) is not dict or set(metadata) - {'episode', 'code_reference'}:
        raise ValueError('Metadatos no admitidos; no incluir credenciales')
    if type(metadata.get('episode')) is not str or not metadata['episode']:
        raise ValueError('Identificador de episodio obligatorio')
    reference = metadata.get('code_reference', ENGINE_VERSION)
    if type(reference) is not str:
        raise ValueError('Referencia de código inválida')
    return {'format': 'record-v1', 'header': {
        'episode': metadata['episode'], 'code_reference': reference,
        'run_kind': 'development', 'engine': ENGINE_VERSION,
        'rules': 'experimental-v1', 'deck': 'pilot-47-v1',
        'python': platform.python_version(), 'implementation': platform.python_implementation(),
        'configuration': deepcopy(state.setup)},
        'initial_state': state_data(state), 'attempts': [], 'closure': _closure(state)}


def _last_state(record):
    return read_state(record['attempts'][-1]['state'] if record['attempts'] else record['initial_state'])


def _format_description(value):
    # No repr, nombres de clases externas ni contenido de objetos no JSON.
    if type(value) is dict:
        return {'type': 'dict', 'json': False}
    if type(value) is list:
        return {'type': 'list', 'json': False}
    return {'type': 'non-json', 'json': False}


def record_attempt(record, actor, request):
    if record['closure']['status'] == 'interrupted':
        raise ValueError('Registro interrumpido')
    state = _last_state(record)
    resolution = apply_action(state, actor, request)
    entry = {'sequence': len(record['attempts']) + 1, 'turn': state.turn,
             'operation': 'action',
             'actor': _copy_json(actor) if is_json(actor) else None,
             'actor_format': None if is_json(actor) else _format_description(actor),
             'request': _copy_json(request) if is_json(request) else None,
             'request_format': None if is_json(request) else _format_description(request),
             'accepted': resolution.accepted, 'error': resolution.error,
             'public_events': deepcopy(resolution.public_events),
             'private_events': {str(k): deepcopy(v) for k, v in resolution.private_events.items()},
             'state': state_data(resolution.state)}
    record['attempts'].append(entry)
    record['closure'] = _closure(resolution.state)
    return resolution


def record_interruption(record, code):
    state = _last_state(record)
    interrupted = interrupt_game(state, code)
    record['attempts'].append({
        'sequence': len(record['attempts']) + 1, 'turn': state.turn,
        'operation': 'interrupt', 'code': code,
        'events': [{'kind': 'interruption', 'code': code}],
        'state': state_data(interrupted)})
    record['closure'] = _closure(interrupted)
    return interrupted


def replay_record(record):
    """Primera discrepancia, solo para evaluador; no rebaraja ni modifica."""
    index = 0
    try:
        _keys(record, 'format header initial_state attempts closure')
        if record['format'] != 'record-v1' or not is_json(record):
            raise ValueError('Versión o dominio JSON inválido')
        header = record['header']
        _keys(header, 'episode code_reference run_kind engine rules deck python implementation configuration')
        if (header['engine'] != ENGINE_VERSION or header['rules'] != 'experimental-v1'
                or header['deck'] != 'pilot-47-v1' or header['run_kind'] != 'development'
                or any(type(header[k]) is not str for k in ('episode', 'code_reference', 'python', 'implementation'))):
            raise ValueError('Cabecera incompatible')
        state = read_state(record['initial_state'])
        if not _same_json(header['configuration'], state.setup) or type(record['attempts']) is not list:
            raise ValueError('Configuración incompatible')
        expected = _copy_json(record)
        expected['attempts'] = []
        expected['closure'] = _closure(state)
        for index, entry in enumerate(record['attempts'], 1):
            if entry['operation'] == 'action':
                request = entry['request'] if entry['request_format'] is None else object()
                actor = entry['actor'] if entry['actor_format'] is None else object()
                record_attempt(expected, actor, request)
                generated = expected['attempts'][-1]
                for field in ('request_format', 'actor_format'):
                    if entry[field] is not None:
                        if entry[field] not in ({'type': 'dict', 'json': False}, {'type': 'list', 'json': False}, {'type': 'non-json', 'json': False}):
                            raise ValueError('Descripción de formato inválida')
                        generated[field] = entry[field]
            elif entry['operation'] == 'interrupt':
                record_interruption(expected, entry['code'])
            else:
                raise ValueError('Operación desconocida')
            if not _same_json(expected['attempts'][-1], entry):
                return {'matches': False, 'entry': index, 'code': 'transition-mismatch'}
        if not _same_json(expected['closure'], record['closure']):
            return {'matches': False, 'entry': len(record['attempts']) + 1, 'code': 'closure-mismatch'}
        return {'matches': True, 'entries': len(record['attempts'])}
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return {'matches': False, 'entry': index, 'code': 'invalid-record'}


def _same_json(a, b):
    # Python considera True == 1; el formato del registro no los confunde.
    return _json_text(a) == _json_text(b)


def loads_record(text):
    record = _parse_json(text)
    if not replay_record(record)['matches']:
        raise ValueError('Registro incompatible o alterado')
    return record


def _private_path(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('Ruta absoluta explícita obligatoria')
    if '..' in path.parts:
        raise ValueError('Ruta no canónica')
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError('No se admiten enlaces simbólicos')
    repository = Path(__file__).resolve().parents[2]
    if path.is_relative_to(repository):
        raise ValueError('Registro privado fuera del repositorio')
    parent = path.parent.stat()
    if (not stat.S_ISDIR(parent.st_mode) or stat.S_IMODE(parent.st_mode) != 0o700
            or parent.st_uid != os.getuid()):
        raise PermissionError('El directorio no es privado 0700 del evaluador')
    if path.exists():
        info = path.stat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.getuid() or info.st_nlink != 1):
            raise PermissionError('El archivo no es privado 0600')
    return path


def save_record(record, path):
    path = _private_path(path)
    if not replay_record(record)['matches']:
        raise ValueError('No guardar registro incompatible')
    payload = _json_text(record)
    if path.exists():
        previous = loads_record(path.read_text(encoding='utf-8'))
        if not _same_json(previous['header'], record['header']) or not _same_json(previous['initial_state'], record['initial_state']):
            raise ValueError('No sobrescribir otro episodio')
        if not _same_json(previous['attempts'], record['attempts'][:len(previous['attempts'])]):
            raise ValueError('No perder ni sustituir trayectoria confirmada')
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.record-', dir=path.parent)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _private_path(path)
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def load_record(path):
    path = _private_path(path)
    return loads_record(path.read_text(encoding='utf-8'))
