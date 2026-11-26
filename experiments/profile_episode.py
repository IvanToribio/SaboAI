"""Prototipo descartable para desglosar un episodio y reproducirlo sin Ollama."""
import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from saboteurai import controller
from saboteurai.cards import Card
from saboteurai.records import miner_view, replay_record, save_episode
from probe_ollama import near_gold


def calls_in(turn):
    action = [turn['action']] if turn['action'] is not None else []
    return [call for decision in turn['speeches'] + action for call in decision['calls']]


def describe(episode):
    turns = episode['turns']
    calls = [call for turn in turns for call in calls_in(turn)]
    for phase in dict.fromkeys(call['query']['phase'] for call in calls):
        group = [call for call in calls if call['query']['phase'] == phase]
        seconds = [call['elapsed_ns'] / 1e9 for call in group]
        print(phase, dict(calls=len(group), seconds=round(sum(seconds), 2),
                          median_seconds=round(median(seconds), 2),
                          errors=sum('error' in call for call in group)))
    for key in ('load_duration_ns', 'prompt_duration_ns', 'completion_duration_ns'):
        seconds = sum((call.get('reply', {}).get('metrics') or {}).get(key, 0)
                      for call in calls) / 1e9
        print(key, round(seconds, 2))
    for turn in turns[::10] + turns[-1:]:
        group = calls_in(turn)
        tokens = [(call.get('reply', {}).get('metrics') or {}).get('prompt_tokens')
                  for call in group]
        print('turno', turn['turn'], dict(seconds=round(sum(c['elapsed_ns'] for c in group) / 1e9, 2),
                                        max_prompt_tokens=max((x for x in tokens if x is not None),
                                                              default=None)))
    print('cierres y calidad', episode['game']['closure'], dict(
        actions=Counter(entry['request']['kind'] for entry in episode['game']['attempts']
                        if entry['operation'] == 'action' and entry['accepted']),
        revisions=sum(any(c['query']['phase'] == 'shorten' for c in speech['calls'])
                      for turn in turns for speech in turn['speeches']),
        truncated=sum(speech.get('truncated', False) for turn in turns for speech in turn['speeches']),
        invalid_first=sum(not turn['action']['validations'][0]['accepted']
                          for turn in turns if turn['action'] and turn['action']['validations']),
        auto_discards=sum(bool(turn['action'] and 'automatic_discard' in turn['action'])
                          for turn in turns),
    ))


def replay(episode, active_only):
    game = episode['game']
    source_actions = {entry['turn']: entry['request'] for entry in game['attempts']
                      if entry['operation'] == 'action' and entry['accepted']}
    source_speeches = {(turn['turn'], speech['speaker']): speech.get('published')
                       for turn in episode['turns'] for speech in turn['speeches']}
    timing = Counter()
    count = Counter()

    def timed(name, fn):
        def measure(*args, **kwargs):
            start = perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                timing[name] += perf_counter() - start
        return measure

    def model(query):
        view = query['observation']
        count[query['phase']] += 1
        if query['phase'] == 'speak':
            text = source_speeches.get((view['turn'], view['miner_id']))
            return controller.ModelReply(text or 'SILENCIO')
        return controller.ModelReply(str(view['legal_actions'].index(source_actions[view['turn']]) + 1))

    original_conversation = controller._run_conversation

    def conversation(ask, turn, game_record, messages, notify):
        if active_only:
            turn['speaker_order'] = [turn['active']]
        original_conversation(ask, turn, game_record, messages, notify)

    with (
        patch.object(controller, 'miner_view', timed('observations', controller.miner_view)),
        patch.object(controller, 'record_attempt', timed('transitions', controller.record_attempt)),
        patch.object(controller, '_run_conversation', conversation),
    ):
        start = perf_counter()
        result = controller.run_game(
            model, seed=game['header']['configuration']['seed'],
            conversation_seed=episode['configuration']['conversation_seed'],
            episode='local-replay',
        )
        runtime = perf_counter() - start
    assert result['game']['closure'] == game['closure']
    assert [entry['request'] for entry in result['game']['attempts']] == list(source_actions.values())
    assert replay_record(result['game'])['matches']
    with TemporaryDirectory() as folder:
        path = Path(folder).resolve() / 'episode.json'
        start = perf_counter()
        save_episode(result, path)
        save_time = perf_counter() - start
        print('replay', dict(active_only=active_only, calls=dict(count),
                             local_seconds=round(runtime, 4), save_seconds=round(save_time, 4),
                             bytes=path.stat().st_size,
                             **{name: round(seconds, 4) for name, seconds in timing.items()}))


def test_closure(kind):
    state = near_gold()
    if kind == 'stone':
        center = state.board[8, 0]
        top = state.board[8, -2]
        center.card = Card(center.card.id, 'stone-a')
        top.card = Card(top.card.id, 'gold')
        state.players[0].inspections = {}
    if kind == 'empty':
        state.deck.clear()
        for player in state.players:
            player.hand.clear()
        state.players[0].hand = [Card('last-card', 'map')]

    queries = []
    events = []

    def model(query):
        queries.append(query)
        if query['observation']['turn'] == 2:
            raise KeyboardInterrupt
        if query['phase'] == 'speak':
            return controller.ModelReply('SILENCIO')
        actions = query['observation']['legal_actions']
        i = next(i for i, action in enumerate(actions, 1) if (
            action['kind'] == 'discard' if kind == 'empty' else
            action['kind'] == 'place' and action['card_id'] == 'test-good'
            and (action['x'], action['y']) == (7, 0)
        ))
        return controller.ModelReply(str(i))

    with patch.object(controller, 'new_game', return_value=state):
        result = controller.run_game(model, seed=11, conversation_seed=21,
                                     episode='closure-probe', notify=events.append)
    game = result['game']
    public = [event for event in events if event['kind'] in ('result', 'reveal')]
    if kind == 'stone':
        assert [event['kind'] for event in public] == ['reveal']
        assert queries[-1]['observation']['status'] == 'playing'
    else:
        assert game['closure']['result']['reason'] == kind
        assert events[-1]['kind'] == 'result'
        assert len(queries) == 6
        view = miner_view(game, 0)
        assert view['status'] == 'finished' and not view['legal_actions']
        assert view['public_actions'][-1]['reason'] == kind
    assert replay_record(game)['matches']
    print('cierre', kind, dict(queries=len(queries), events=public, closure=game['closure']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('episode', type=Path, nargs='?', help='episodio completo con registro privado')
    args = parser.parse_args()
    if args.episode is not None:
        episode = json.loads(args.episode.read_text())
        assert episode['game']['closure']['status'] == 'finished'
        describe(episode)
        replay(episode, active_only=False)
        replay(episode, active_only=True)
    for case in ('gold', 'stone', 'empty'):
        test_closure(case)


if __name__ == '__main__':
    main()
