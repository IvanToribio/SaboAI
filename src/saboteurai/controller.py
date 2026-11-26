"""Dirige una partida experimental mediante un proveedor de respuestas inyectable."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, dataclass
import math
import random
import re
from time import monotonic_ns
from typing import NotRequired, TypedDict

from .board import port_notation
from .cards import CARDS, ENABLED_TYPES
from .records import (
    PublicMessage, miner_view, public_board, record_attempt, record_interruption, start_record,
)
from .state import new_game

WORD_LIMIT = 80
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


class _QueryCall(TypedDict):
    query: ModelQuery
    service_attempt: int
    reply: NotRequired[dict]
    error: NotRequired[str]
    elapsed_ns: NotRequired[int]


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
        for key, value in settings['parameters'].items():
            if (key not in _MODEL_PARAMETERS or type(value) not in (int, float, bool)
                    or (type(value) is float and not math.isfinite(value))):
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


def _query(ask: Callable[[ModelQuery], ModelReply], calls: list[_QueryCall], phase: str,
           observation: dict, *, feedback: str | None = None,
           previous_response: str | None = None) -> str:
    query = ModelQuery(
        instructions=INSTRUCTIONS, phase=phase, task=_TASKS[phase],
        observation=observation, feedback=feedback, previous_response=previous_response,
    )
    for service_attempt in (1, 2):
        call = _QueryCall(query=deepcopy(query), service_attempt=service_attempt)
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


def _conversation(ask, turn, game, messages, notify):
    for speaker in turn['speaker_order']:
        speech = {'speaker': speaker, 'calls': []}
        turn['speeches'].append(speech)
        observation = miner_view(game, speaker, public_messages=messages)
        text = _query(ask, speech['calls'], 'speak', observation)
        words = list(re.finditer(r'\S+', text))
        if len(words) > WORD_LIMIT:
            text = _query(
                ask, speech['calls'], 'shorten', observation,
                feedback=f'Tu mensaje supera el máximo de {WORD_LIMIT} palabras.',
                previous_response=text,
            )
            words = list(re.finditer(r'\S+', text))
        truncated = len(words) > WORD_LIMIT
        published = text[:words[WORD_LIMIT - 1].end()] if truncated else text.strip()
        if not published or published.casefold() == 'silencio':
            published = None
        speech.update(published=published, truncated=truncated)
        if published is not None:
            messages.append(PublicMessage(turn=turn['turn'], speaker=speaker, text=published))
        notify({'kind': 'speech', 'speaker': speaker, 'text': published})


def _choose_action(ask, turn, game, observation):
    actor = observation['miner_id']
    legal = observation['legal_actions']
    choice = {'calls': [], 'validations': []}
    turn['action'] = choice
    feedback = previous = None
    for phase in ('act', 'revise-action'):
        text = _query(ask, choice['calls'], phase, observation,
                      feedback=feedback, previous_response=previous)
        number = text.strip()
        if not re.fullmatch(r'[1-9][0-9]*', number):
            feedback = 'La respuesta debe ser un único entero positivo.'
        elif len(number) > len(str(len(legal))) or int(number) > len(legal):
            feedback = f'El número debe estar entre 1 y {len(legal)}.'
        else:
            resolution = record_attempt(game, actor, legal[int(number) - 1])
            choice['validations'].append({
                'accepted': resolution.accepted, 'error': resolution.error,
                'game_sequence': len(game['attempts']),
            })
            if resolution.accepted:
                return resolution, False
            feedback = f'El motor rechazó esa acción ({resolution.error}).'
            previous = text
            continue
        choice['validations'].append({'accepted': False, 'error': feedback})
        previous = text

    request = {'kind': 'discard', 'card_id': observation['hand'][0]['id']}
    resolution = record_attempt(game, actor, request)
    choice['automatic_discard'] = {'card_id': request['card_id'],
                                   'game_sequence': len(game['attempts'])}
    if not resolution.accepted:
        raise RuntimeError('El motor rechazó el descarte automático')
    return resolution, True


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
    game = start_record(state, {'episode': episode})
    rng = random.Random(conversation_seed)
    messages: list[PublicMessage] = []
    turns: list[dict] = []
    record = {
        'format': 'episode-v1', 'game': game, 'turns': turns,
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
            speakers = [player.id for player in state.players]
            rng.shuffle(speakers)
            turn = {'turn': state.turn, 'active': state.active, 'speaker_order': speakers,
                    'speeches': [], 'action': None}
            turns.append(turn)
            notify({'kind': 'turn', 'turn': state.turn, 'active': state.active,
                    'speaker_order': speakers.copy(), 'board': public_board(state)})
            _conversation(ask, turn, game, messages, notify)
            observation = miner_view(game, state.active, public_messages=messages)
            resolution, automatic = _choose_action(ask, turn, game, observation)
            state = resolution.state
            if automatic:
                notify({'kind': 'automatic-discard', 'actor': observation['miner_id']})
            for event in resolution.public_events:
                notify(event)
    except KeyboardInterrupt:
        interruption = 'manual-stop'
    except _ModelUnavailable:
        interruption = 'technical-failure'
        record['error'] = 'model-unavailable'
    except OSError:
        interruption = 'io-failure'
        record['error'] = 'io-error'
    except Exception as error:
        interruption = 'technical-failure'
        record['error'] = type(error).__name__

    if interruption is not None and game['closure']['status'] == 'playing':
        record_interruption(game, interruption)
    return record


def _ignore_event(_event: dict) -> None:
    pass
