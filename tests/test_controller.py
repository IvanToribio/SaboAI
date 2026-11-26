import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest

from saboteurai.controller import ModelReply, ModelServiceError, ModelSettings, run_game
from saboteurai.records import replay_record, save_episode


class ControllerTests(unittest.TestCase):
    def test_complete_game_uses_public_conversation_and_each_miners_own_hand(self):
        queries = []

        def model(query):
            queries.append(query)
            if query['phase'] == 'speak':
                return ModelReply(f"Habla el minero {query['observation']['miner_id']}")
            legal = query['observation']['legal_actions']
            return ModelReply(str(next(i for i, action in enumerate(legal, 1)
                                       if action['kind'] == 'discard')))

        episode = run_game(model, seed=11, conversation_seed=21, episode='discard-game')
        game = episode['game']
        self.assertEqual(game['closure']['status'], 'finished')
        self.assertEqual(game['closure']['result']['reason'], 'empty')
        self.assertEqual(replay_record(game), {'matches': True, 'entries': 47})
        self.assertEqual(len(queries), 47 * 6)
        self.assertIn('stone-a NW', queries[0]['instructions'])
        self.assertIn('stone-b SW', queries[0]['instructions'])

        speakers = episode['turns'][0]['speaker_order']
        self.assertEqual(sorted(speakers), list(range(5)))
        published = []
        for query, speaker in zip(queries[:5], speakers):
            view = query['observation']
            self.assertEqual(view['miner_id'], speaker)
            self.assertEqual(view['hand'], game['initial_state']['players'][speaker]['hand'])
            self.assertEqual(view['public_messages'], published)
            self.assertNotIn('seed', view)
            self.assertTrue(all('type' not in tile for tile in view['board'] if tile.get('hidden')))
            published.append({'turn': 1, 'speaker': speaker, 'text': f'Habla el minero {speaker}'})
        self.assertEqual(queries[5]['observation']['public_messages'], published)
        self.assertEqual(queries[-1]['observation']['public_actions'][0]['turn'], 1)
        self.assertEqual(len(queries[-1]['observation']['public_messages']), 47 * 5)

    def test_applies_a_clear_choice_in_different_reply_formats(self):
        replies = (
            ' 1\n',
            '1.',
            'Elijo la opción 1.',
            'La respuesta correcta es 1.',
            'Respuesta: 1\nColocaré el túnel largo.',
            '2. place\nRespuesta: 1',
            'La elección de acción legal es:\n\n1. place\n\n'
            'Colocaré el túnel largo "c012" en la posición (x, y) = (-1, 0), '
            'con una rotación de 180°.\n\nRespuesta: 1',
        )
        for reply in replies:
            with self.subTest(reply=reply):
                def model(query):
                    if query['observation']['turn'] == 2:
                        raise KeyboardInterrupt
                    if query['phase'] == 'speak':
                        return ModelReply('SILENCIO')
                    return ModelReply(reply)

                episode = run_game(model, seed=11, conversation_seed=21, episode='reply-formats')
                action = episode['turns'][0]['action']
                self.assertEqual([call['reply']['text'] for call in action['calls']], [reply])
                self.assertTrue(action['validations'][0]['accepted'])
                self.assertEqual(episode['game']['attempts'][0]['request'],
                                 {'kind': 'place', 'card_id': 'c012', 'x': -1, 'y': 0, 'rotation': 180})

    def test_requests_correction_when_the_reply_does_not_identify_a_legal_choice(self):
        replies = (
            'Puedo ir a (1, 0) con giro de 180°.',
            'Elijo la opción 1 o 2.',
            'Elijo la opción 2.\nRespuesta: 1',
            'Elijo la opción 2, porque encaja.\nRespuesta: 1',
            '**Respuesta: 2**\nRespuesta: 1',
            'Puedo elegir varias opciones.\n1.',
            'Respuesta: 1.2',
            'Respuesta: 21',
        )
        for reply in replies:
            with self.subTest(reply=reply):
                def model(query):
                    if query['observation']['turn'] == 2:
                        raise KeyboardInterrupt
                    if query['phase'] == 'speak':
                        return ModelReply('SILENCIO')
                    if query['phase'] == 'act':
                        return ModelReply(reply)
                    self.assertEqual(query['previous_response'], reply)
                    self.assertTrue(query['feedback'])
                    return ModelReply('La respuesta correcta es 1.')

                episode = run_game(model, seed=11, conversation_seed=21, episode='reply-retry')
                action = episode['turns'][0]['action']
                self.assertEqual([item['accepted'] for item in action['validations']], [False, True])
                self.assertEqual(episode['game']['attempts'][0]['request']['kind'], 'place')

    def test_revises_long_messages_and_discards_first_card_after_two_invalid_actions(self):
        long_message = ' '.join(f'palabra{i}' for i in range(1, 82))
        queries = []

        def model(query):
            queries.append(query)
            phase = query['phase']
            if query['observation']['turn'] == 2:
                raise ModelServiceError('timeout')
            if phase == 'speak':
                return ModelReply(long_message if len(queries) == 1 else 'SILENCIO')
            if phase == 'shorten':
                return ModelReply(long_message, metrics={'prompt_tokens': 0})
            return ModelReply('una jugada' if phase == 'act' else '99999')

        events = []
        episode = run_game(model, seed=11, conversation_seed=21, episode='retries',
                           notify=events.append)
        turn = episode['turns'][0]
        speech = turn['speeches'][0]
        self.assertEqual([call['reply']['text'] for call in speech['calls']], [long_message] * 2)
        self.assertEqual(speech['calls'][1]['reply']['metrics'], {'prompt_tokens': 0})
        self.assertIsNone(speech['calls'][0]['reply']['metrics'])
        self.assertTrue(speech['truncated'])
        self.assertEqual(speech['published'].split(), long_message.split()[:80])
        self.assertEqual(queries[2]['observation']['public_messages'][0]['text'], speech['published'])
        self.assertTrue(all(item['published'] is None for item in turn['speeches'][1:]))

        decision = turn['action']
        self.assertEqual([item['accepted'] for item in decision['validations']], [False, False])
        self.assertEqual(decision['calls'][1]['query']['previous_response'], 'una jugada')
        self.assertIn('entero positivo', decision['calls'][1]['query']['feedback'])
        game = episode['game']
        first_card = game['initial_state']['players'][turn['active']]['hand'][0]['id']
        self.assertEqual(decision['automatic_discard']['card_id'], first_card)
        self.assertEqual(game['attempts'][0]['request'], {'kind': 'discard', 'card_id': first_card})
        self.assertNotIn(first_card, str(events))

        failed_calls = episode['turns'][1]['speeches'][0]['calls']
        self.assertEqual([call['error'] for call in failed_calls], ['timeout', 'timeout'])
        self.assertEqual(failed_calls[0]['query'], failed_calls[1]['query'])
        self.assertIsNone(episode['turns'][1]['action'])
        self.assertEqual(game['closure'], {'status': 'interrupted', 'result': None,
                                          'interruption': 'technical-failure'})
        self.assertTrue(replay_record(game)['matches'])

    def test_manual_stop_preserves_the_partial_conversation_in_a_private_file(self):
        def model(query):
            if query['observation']['public_messages']:
                raise KeyboardInterrupt
            return ModelReply('Mensaje publicado')

        episode = run_game(model, seed=11, conversation_seed=21, episode='manual')
        with TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'episode.json'
            save_episode(episode, path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), episode)
            with self.assertRaises(FileExistsError):
                save_episode(episode, path)

        game = episode['game']
        self.assertEqual(game['closure']['interruption'], 'manual-stop')
        self.assertTrue(replay_record(game)['matches'])
        turn = episode['turns'][0]
        self.assertEqual(turn['speeches'][0]['published'], 'Mensaje publicado')
        self.assertEqual(turn['speeches'][1]['calls'][0]['error'], 'manual-stop')
        self.assertIsNone(turn['action'])

    def test_model_metadata_rejects_fields_outside_generation_settings(self):
        def model(_query):
            self.fail('El modelo no debe consultarse con metadatos inválidos')

        with self.assertRaisesRegex(ValueError, 'Parámetro de generación'):
            run_game(model, seed=11, conversation_seed=21, episode='invalid-metadata',
                     model_settings=ModelSettings('simulation', 'test', {'pin': 1234}))
