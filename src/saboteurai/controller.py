"""Coordina la conversación y los turnos de una partida experimental."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, dataclass
import math
import random
import re
from time import monotonic_ns
from typing import TypedDict

from .board import port_notation
from .cards import CARDS, ENABLED_TYPES
from .engine import Resolution
from .records import (
    PublicMessage, miner_view, public_board, record_attempt, record_interruption, start_record,
)
from .state import new_game

WORD_LIMIT = 80
_MODEL_PARAMETERS = frozenset({
    'temperature', 'seed', 'num_ctx', 'num_predict', 'top_k', 'top_p', 'min_p',
    'repeat_penalty', 'repeat_last_n', 'think',
})


class ModelQuery(TypedDict):
    instructions: str
    phase: str
    task: str
    observation: dict
    feedback: str | None
    previous_response: str | None


@dataclass(frozen=True)
class ModelReply:
    text: str
    metrics: dict[str, int] | None = None


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    name: str
    parameters: dict[str, int | float | bool]

    def record_data(self) -> dict:
        settings = asdict(self)
        for name, value in settings['parameters'].items():
            valid_value = type(value) in (int, float, bool)
            if type(value) is float:
                valid_value = math.isfinite(value)
            if name not in _MODEL_PARAMETERS or not valid_value:
                raise ValueError('Parámetro de generación no admitido en el registro')
        return settings


class ModelServiceError(Exception):
    """El proveedor traduce sus fallos de conexión o servicio a este tipo."""

    def __init__(self, code: str):
        if code not in ('connection', 'timeout', 'service', 'invalid-response'):
            raise ValueError('Código de fallo de modelo desconocido')
        super().__init__(code)
        self.code = code


class _ModelUnavailable(Exception):
    pass


def run_game(
    ask: Callable[[ModelQuery], ModelReply], *, seed: int, conversation_seed: int,
    episode: str, model_settings: ModelSettings | None = None,
    notify: Callable[[dict], None] | None = None,
) -> dict:
    """Ejecuta una ronda y devuelve evidencia privada, también si se interrumpe.

    Cada consulta es independiente y lleva el historial autorizado en su observación.
    El proveedor debe usar únicamente esa consulta y comunicar fallos esperados con
    ModelServiceError. Los parámetros registrados describen el modelo y la generación.
    notify recibe solo eventos públicos y puede mostrar la partida en directo.
    """
    if type(conversation_seed) is not int:
        raise ValueError('La semilla de conversación debe ser un entero')
    if notify is None:
        notify = _ignore_event
    state = new_game(0, seed)
    # El registro del motor permite reproducir las jugadas. El de la partida añade la conversación.
    game_record = start_record(state, {'episode': episode})
    # El orden de conversación no consume la semilla del reparto.
    conversation_rng = random.Random(conversation_seed)
    published_messages: list[PublicMessage] = []
    episode_record: dict = {
        'format': 'episode-v1',
        'game': game_record,
        'turns': [],
        'configuration': {
            'conversation_seed': conversation_seed, 'word_limit': WORD_LIMIT,
            'instructions': INSTRUCTIONS,
            'model': model_settings.record_data() if model_settings is not None else None,
        },
        'error': None,
    }

    interruption = None
    try:
        while state.status == 'playing':
            speaker_order = [player.id for player in state.players]
            conversation_rng.shuffle(speaker_order)
            turn_record = {
                'turn': state.turn,
                'active': state.active,
                'speaker_order': speaker_order,
                'speeches': [],
                'action': None,
            }
            episode_record['turns'].append(turn_record)
            notify({
                'kind': 'turn',
                'turn': state.turn,
                'active': state.active,
                'speaker_order': speaker_order.copy(),
                'board': public_board(state),
            })

            _run_conversation(ask, turn_record, game_record, published_messages, notify)
            observation = miner_view(game_record, state.active, public_messages=published_messages)
            resolution, automatic_discard = _play_action(ask, turn_record, game_record, observation)
            state = resolution.state
            if automatic_discard:
                notify({'kind': 'automatic-discard', 'actor': observation['miner_id']})
            for event in resolution.public_events:
                notify(event)
    except KeyboardInterrupt:
        interruption = 'manual-stop'
    except _ModelUnavailable:
        interruption = 'technical-failure'
        episode_record['error'] = 'model-unavailable'
    except OSError:
        interruption = 'io-failure'
        episode_record['error'] = 'io-error'
    except Exception as error:
        interruption = 'technical-failure'
        episode_record['error'] = type(error).__name__

    if interruption is not None and game_record['closure']['status'] == 'playing':
        record_interruption(game_record, interruption)
    return episode_record


def _run_conversation(ask, turn_record, game_record, published_messages, notify) -> None:
    for speaker in turn_record['speaker_order']:
        speech = {'speaker': speaker, 'calls': []}
        turn_record['speeches'].append(speech)
        observation = miner_view(game_record, speaker, public_messages=published_messages)
        text = _ask_model(ask, speech['calls'], 'speak', observation)
        words = list(re.finditer(r'\S+', text))
        if len(words) > WORD_LIMIT:
            text = _ask_model(
                ask, speech['calls'], 'shorten', observation,
                feedback=f'Tu mensaje supera el máximo de {WORD_LIMIT} palabras.',
                previous_response=text,
            )
            words = list(re.finditer(r'\S+', text))
        # Corta el texto original para conservar los espacios entre palabras.
        truncated = len(words) > WORD_LIMIT
        published: str | None = text[:words[WORD_LIMIT - 1].end()] if truncated else text.strip()
        if not published or published.casefold() == 'silencio':
            published = None
        speech.update(published=published, truncated=truncated)
        if published is not None:
            published_messages.append(PublicMessage(
                turn=turn_record['turn'], speaker=speaker, text=published,
            ))
        notify({'kind': 'speech', 'speaker': speaker, 'text': published})


_ACTION_REPLY = re.compile(
    r'(?P<label>(?:respuesta|opci[oó]n|acci[oó]n)(?:\s*:\s*|\s+)'
    r'|(?:la respuesta(?: correcta)? es|elijo(?: la opci[oó]n)?)\s+)?'
    r'(?P<number>[1-9][0-9]*)\.?(?=$|[\s,;])',
    re.IGNORECASE,
)


def _action_number(text: str) -> str | None:
    """Lee una elección clara y comprueba que no contradiga otra."""
    lines = text.strip().splitlines()
    choices = set()
    has_complete_choice = False
    for line in lines:
        line = line.strip()
        if line.startswith('**') and line.endswith('**'):
            line = line[2:-2].strip()
        match = _ACTION_REPLY.match(line)
        if match is None or (len(lines) > 1 and match['label'] is None):
            continue
        choices.add(match['number'])
        has_complete_choice = has_complete_choice or match.end() == len(line)
    if has_complete_choice and len(choices) == 1:
        return choices.pop()
    return None


def _play_action(ask, turn_record, game_record, observation) -> tuple[Resolution, bool]:
    actor = observation['miner_id']
    legal_actions = observation['legal_actions']
    action_record: dict = {'calls': [], 'validations': []}
    turn_record['action'] = action_record
    action_count = len(legal_actions)
    # Evita convertir a entero una respuesta con miles de dígitos.
    max_digits = len(str(action_count))
    feedback = None
    previous_response = None
    for phase in ('act', 'revise-action'):
        text = _ask_model(
            ask, action_record['calls'], phase, observation,
            feedback=feedback, previous_response=previous_response,
        )
        previous_response = text
        number_text = _action_number(text)
        if number_text is None:
            feedback = 'La respuesta debe ser un único entero positivo.'
        elif len(number_text) > max_digits or int(number_text) > action_count:
            feedback = f'El número debe estar entre 1 y {action_count}.'
        else:
            selected_action = legal_actions[int(number_text) - 1]
            resolution = record_attempt(game_record, actor, selected_action)
            action_record['validations'].append({
                'accepted': resolution.accepted, 'error': resolution.error,
                'game_sequence': len(game_record['attempts']),
            })
            if resolution.accepted:
                return resolution, False
            feedback = f'El motor rechazó esa acción ({resolution.error}).'
            continue
        action_record['validations'].append({'accepted': False, 'error': feedback})

    first_card = observation['hand'][0]['id']
    discard = {'kind': 'discard', 'card_id': first_card}
    resolution = record_attempt(game_record, actor, discard)
    action_record['automatic_discard'] = {
        'card_id': first_card,
        'game_sequence': len(game_record['attempts']),
    }
    if not resolution.accepted:
        raise RuntimeError('El motor rechazó el descarte automático')
    return resolution, True


def _ask_model(
    ask: Callable[[ModelQuery], ModelReply], calls: list[dict], phase: str,
    observation: dict, *, feedback: str | None = None,
    previous_response: str | None = None,
) -> str:
    query = ModelQuery(
        instructions=INSTRUCTIONS, phase=phase, task=_TASKS[phase],
        observation=observation, feedback=feedback, previous_response=previous_response,
    )
    # Un fallo del proveedor repite la misma consulta, con el mismo contexto.
    for service_attempt in (1, 2):
        call: dict = {'query': deepcopy(query), 'service_attempt': service_attempt}
        calls.append(call)
        started = monotonic_ns()
        try:
            reply = ask(deepcopy(query))
            call['reply'] = asdict(reply)
            return reply.text
        except ModelServiceError as error:
            call['error'] = error.code
        except KeyboardInterrupt:
            call['error'] = 'manual-stop'
            raise
        finally:
            call['elapsed_ns'] = monotonic_ns() - started
    raise _ModelUnavailable


def _ignore_event(_event: dict) -> None:
    pass


_PORT_CATALOG = ', '.join(
    f'{card.id} {port_notation(card.id)}'
    for card in CARDS.values() if card.kind in ('start', 'goal')
    or (card.id in ENABLED_TYPES and card.kind == 'path')
)
INSTRUCTIONS = f"""Sois cinco mineros y compartís el objetivo de conectar la entrada con el oro.
Cada turno empieza con una conversación pública en orden barajado. Cada minero puede
enviar un mensaje de hasta {WORD_LIMIT} palabras o responder SILENCIO. Una intervención larga
puede revisarse una vez. Si sigue siendo larga, se publican sus primeras {WORD_LIMIT} palabras.
Después, el minero activo juega o descarta una carta. Roba si queda mazo. Los mineros
sin cartas no juegan acciones. Si se agotan las manos antes de llegar al oro, perdéis.
El tablero usa (x, y), con x hacia el este e y hacia el sur. La entrada está en (0, 0).
N, E, S y W son norte, este, sur y oeste. En el catálogo, las bocas del mismo grupo
están conectadas. Una barra separa grupos independientes. Los giros son de 0° o 180°.
Conexiones de túneles, entrada y destinos a 0°: {_PORT_CATALOG}.
Al colocar un túnel sus bordes deben encajar y conectar con la entrada. Un destino
alcanzado se revela. El mapa inspecciona un destino oculto en privado. El derrumbe
retira un túnel. Romper un pico impide colocar túneles hasta que se repare.
La observación incluye el tablero, tu propia mano e inspecciones, el estado público
de los picos, las acciones públicas y los mensajes ya publicados en esta partida.
Los mensajes públicos son intervenciones de los mineros. Cuando te toque actuar,
elige una acción de legal_actions y responde solo con su número entero, empezando
por 1. place coloca, inspect inspecciona, rockfall derrumba, break rompe el pico,
repair lo repara y discard descarta. Tras dos respuestas de acción inválidas se
descarta automáticamente la primera carta de la mano."""
_TASKS = {
    'speak': 'Escribe tu intervención pública o responde SILENCIO.',
    'shorten': 'Revisa tu intervención para respetar el límite o responde SILENCIO.',
    'act': 'Elige una acción legal y responde con su número.',
    'revise-action': 'Corrige tu respuesta y devuelve solo el número de una acción legal.',
}
