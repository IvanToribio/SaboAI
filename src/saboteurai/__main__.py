"""Ejecuta una partida de demostración con respuestas simuladas."""

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
    parser.add_argument('--demo', action='store_true', required=True,
                        help='usar respuestas simuladas')
    parser.add_argument('--seed', type=int, default=11, help='semilla de preparación')
    parser.add_argument('--conversation-seed', type=int, default=21,
                        help='semilla de conversación')
    args = parser.parse_args()

    directory = Path(mkdtemp(prefix='saboteurai-')).resolve()
    path = directory / 'episode.json'
    print('Partida de demostración con respuestas simuladas. Ctrl+C detiene la ejecución.')
    print(f'Registro privado: {path}')
    print(LEGEND, flush=True)
    stop_requested = False

    def request_stop(_signum, _frame):
        nonlocal stop_requested
        stop_requested = True

    def ask(query: ModelQuery) -> ModelReply:
        if stop_requested:
            raise KeyboardInterrupt
        return _demo_model(query)

    # Detiene la demo entre consultas y deja terminar la escritura del registro.
    previous_handler = signal.signal(signal.SIGINT, request_stop)
    try:
        record = run_game(
            ask, seed=args.seed, conversation_seed=args.conversation_seed,
            episode=uuid4().hex, model_settings=ModelSettings('simulation', 'first-legal', {}),
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
