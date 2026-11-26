"""Ejecuta una partida de SaboteurAI con Ollama local o respuestas simuladas."""

import argparse
from pathlib import Path
import signal
from tempfile import mkdtemp
from uuid import uuid4

from .console import LEGEND, show_event
from .controller import ModelQuery, ModelReply, ModelSettings, run_game
from .records import save_episode


def _demo_model(query: ModelQuery) -> ModelReply:
    if query['phase'] == 'speak':
        return ModelReply('SILENCIO')
    return ModelReply('1')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--demo', action='store_true', help='usar respuestas simuladas')
    mode.add_argument('--model', metavar='MODELO', default='llama3.1:8b',
                      help='modelo local (por defecto: %(default)s)')
    parser.add_argument('--seed', type=int, default=11, help='semilla de preparación')
    parser.add_argument('--conversation-seed', type=int, default=21,
                        help='semilla de conversación')
    args = parser.parse_args()

    if args.demo:
        ask_model = _demo_model
        settings = ModelSettings('simulation', 'first-legal', {})
        description = 'Partida de demostración con respuestas simuladas.'
    else:
        try:
            from .ollama_model import OllamaModel
        except ModuleNotFoundError as error:
            if error.name not in ('ollama', 'httpx'):
                raise
            parser.error('instala las dependencias con python -m pip install -r requirements.txt')
        ask_model = OllamaModel(args.model)
        settings = ask_model.settings
        description = f'Partida con Ollama local ({settings.name}).'

    directory = Path(mkdtemp(prefix='saboteurai-')).resolve()
    path = directory / 'episode.json'
    print(f'{description} Ctrl+C detiene la ejecución.')
    print(f'Registro privado: {path}')
    print(LEGEND, flush=True)
    stop_requested = False
    querying_model = False

    def request_stop(_signum, _frame):
        nonlocal stop_requested
        stop_requested = True
        if querying_model:
            raise KeyboardInterrupt

    def ask(query: ModelQuery) -> ModelReply:
        nonlocal querying_model
        try:
            querying_model = True
            if stop_requested:
                raise KeyboardInterrupt
            return ask_model(query)
        finally:
            querying_model = False

    # Cancela una consulta en curso; deja terminar las transiciones y el guardado.
    previous_handler = signal.signal(signal.SIGINT, request_stop)
    try:
        record = run_game(
            ask, seed=args.seed, conversation_seed=args.conversation_seed,
            episode=uuid4().hex, model_settings=settings,
            notify=show_event,
        )
        save_episode(record, path)
    finally:
        signal.signal(signal.SIGINT, previous_handler)
    interruption = record['game']['closure']['interruption']
    if interruption == 'manual-stop':
        print('Partida interrumpida manualmente. Se guardó el registro parcial.')
        return 130
    if record['error'] is not None:
        print(f'Fallo de ejecución ({record["error"]}). Se guardó el registro.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
