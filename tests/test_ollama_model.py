import json
import unittest

import httpx

from saboteurai.controller import run_game
from saboteurai.engine import legal_actions
from saboteurai.ollama_model import OllamaModel
from saboteurai.records import read_state


class OllamaModelTests(unittest.TestCase):
    def test_action_prompt_keeps_legal_choices_and_isolates_memory(self):
        requests = []
        public_message = 'Empecemos por la entrada.'
        rotated_bend = {'kind': 'place', 'card_id': 'c006', 'x': 0, 'y': 1, 'rotation': 180}

        def chat(request: httpx.Request) -> httpx.Response:
            messages = json.loads(request.content)['messages']
            prompt = json.loads(messages[-1]['content'])
            requests.append((messages, prompt))
            view = prompt['observation']
            turn = view['turn']
            if turn == 7 or (starting_new_game and prompt['phase'] == 'act'):
                raise KeyboardInterrupt
            if prompt['phase'] == 'speak':
                text = public_message if not starting_new_game and len(requests) == 1 else 'SILENCIO'
            else:
                options = view['legal_actions']
                if turn in (1, 2):
                    destination_y = 0 if turn == 1 else -2
                    choice = next(i for i, action in enumerate(options, 1)
                                  if action['kind'] == 'inspect' and action['y'] == destination_y)
                elif turn == 6:
                    choice = 3
                else:
                    choice = next(i for i, action in enumerate(options, 1)
                                  if action['kind'] == 'discard')
                text = str(choice)
            return httpx.Response(200, json={
                'message': {'role': 'assistant', 'content': text}, 'done': True,
            })

        starting_new_game = False
        model = OllamaModel('test-model', transport=httpx.MockTransport(chat))
        episode = run_game(model, seed=22, conversation_seed=21, episode='audit-view')
        game = episode['game']
        self.assertEqual(game['closure']['interruption'], 'manual-stop')
        attempts = [entry for entry in game['attempts'] if entry['operation'] == 'action']
        self.assertEqual(len(attempts), 6)
        self.assertTrue(all(entry['accepted'] for entry in attempts))
        self.assertEqual(attempts[5]['request'], rotated_bend)
        self.assertEqual(attempts[5]['public_events'][0],
                         {'kind': 'place', 'actor': 2, 'x': 0, 'y': 1,
                          'rotation': 180, 'type': 'bend-se'})

        before_turn = [read_state(game['initial_state'])] + [
            read_state(entry['state']) for entry in attempts
        ]
        for messages, prompt in requests:
            view = prompt['observation']
            turn, miner = view['turn'], view['miner_id']
            with self.subTest(turn=turn, miner=miner, phase=prompt['phase']):
                state = before_turn[turn - 1]
                self.assertEqual([message['role'] for message in messages], ['system', 'user'])
                self.assertEqual(messages[0]['content'], episode['configuration']['instructions'])
                self.assertEqual(view['hand'], [
                    {'id': card.id, 'type': card.type} for card in state.players[miner].hand
                ])
                for other in state.players:
                    if other.id != miner:
                        for card in other.hand:
                            self.assertNotIn(f'"{card.id}"', messages[-1]['content'])
                self.assertEqual(view['legal_actions'], legal_actions(state, miner))
                expected_inspections = []
                if miner == 2 and turn > 1:
                    expected_inspections = [{'turn': 1, 'x': 8, 'y': 0, 'type': 'stone-b'}]
                elif miner == 3 and turn > 2:
                    expected_inspections = [{'turn': 2, 'x': 8, 'y': -2, 'type': 'stone-a'}]
                self.assertEqual(view['inspections'], expected_inspections)
                known_types = {inspection['type'] for inspection in expected_inspections}
                for hidden_type in {'stone-a', 'stone-b', 'gold'} - known_types:
                    self.assertNotIn(f'"{hidden_type}"', messages[-1]['content'])

        action_prompt = next(prompt for _, prompt in requests
                             if prompt['phase'] == 'act' and prompt['observation']['turn'] == 6)
        view = action_prompt['observation']
        self.assertEqual(view['legal_actions'][2], rotated_bend)
        self.assertNotIn({**rotated_bend, 'rotation': 0}, view['legal_actions'])
        self.assertEqual([msg['text'] for msg in view['public_messages']], [public_message])
        self.assertIn({'turn': 2, 'kind': 'inspect', 'actor': 3, 'x': 8, 'y': -2},
                      view['public_actions'])

        requests.clear()
        starting_new_game = True
        fresh_episode = run_game(model, seed=22, conversation_seed=21, episode='fresh-view')
        self.assertEqual(fresh_episode['game']['closure']['interruption'], 'manual-stop')
        self.assertEqual(len(requests), 6)
        fresh_views = [prompt['observation'] for _, prompt in requests]
        self.assertEqual({view['miner_id'] for view in fresh_views}, set(range(5)))
        for view in fresh_views:
            self.assertEqual(view['turn'], 1)
            for field in ('inspections', 'public_actions', 'public_messages'):
                self.assertEqual(view[field], [])

    def test_five_miners_share_a_model_and_keep_their_inspections_private(self):
        requests = []

        def chat(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, '/api/chat')
            body = json.loads(request.content)
            messages = body['messages']
            prompt = json.loads(messages[-1]['content'])
            view = prompt['observation']
            requests.append((body, prompt))
            if prompt['phase'] == 'act':
                if view['turn'] == 2:
                    raise KeyboardInterrupt
                text = str(next(i for i, action in enumerate(view['legal_actions'], 1)
                                if action['kind'] == 'inspect'))
            else:
                text = 'Seguimos.'
            return httpx.Response(200, json={
                'message': {'role': 'assistant', 'content': text}, 'done': True,
                'prompt_eval_count': 28, 'eval_count': 0, 'total_duration': 10,
            })

        model = OllamaModel('test-model', transport=httpx.MockTransport(chat))
        episode = run_game(model, seed=2, conversation_seed=21, episode='ollama-privacy',
                           model_settings=model.settings)
        game = episode['game']
        self.assertEqual(game['closure']['interruption'], 'manual-stop')
        self.assertEqual(episode['configuration']['model']['name'], 'test-model')
        self.assertEqual(game['attempts'][0]['request']['kind'], 'inspect')
        inspector = episode['turns'][0]['active']
        self.assertEqual({prompt['observation']['miner_id'] for _, prompt in requests[:5]},
                         set(range(5)))
        for body, prompt in requests:
            self.assertEqual(body['model'], 'test-model:local')
            self.assertIs(body['truncate'], False)
            self.assertIs(body['shift'], False)
            self.assertEqual(body['options'], episode['configuration']['model']['parameters'])
            self.assertEqual([message['role'] for message in body['messages']], ['system', 'user'])
            view = prompt['observation']
            player = view['miner_id']
            state = game['initial_state'] if view['turn'] == 1 else game['attempts'][0]['state']
            self.assertEqual(view['hand'], state['players'][player]['hand'])
            self.assertEqual(len(view['inspections']), int(view['turn'] == 2 and player == inspector))
            self.assertNotIn('deck', view)
            self.assertNotIn('seed', view)
            self.assertTrue(all('type' not in tile for tile in view['board'] if tile.get('hidden')))
        self.assertEqual(len(requests[5][1]['observation']['public_messages']), 5)
        reply = episode['turns'][0]['speeches'][0]['calls'][0]['reply']
        self.assertEqual(reply['metrics'], {'prompt_tokens': 28, 'completion_tokens': 0,
                                            'total_duration_ns': 10})

    def test_provider_failures_retry_once_and_interrupt_without_playing(self):
        failures = {
            'connection': 'connection', 'timeout': 'timeout', 'http-error': 'service',
            'bad-json': 'invalid-response', 'bad-gzip': 'invalid-response',
        }
        for failure, code in failures.items():
            with self.subTest(failure=failure):
                requests = []

                def chat(request: httpx.Request) -> httpx.Response:
                    body = json.loads(request.content)
                    if json.loads(body['messages'][-1]['content'])['phase'] == 'speak':
                        return httpx.Response(200, json={
                            'message': {'role': 'assistant', 'content': ''}, 'done': True,
                        })
                    requests.append(body)
                    if failure == 'connection':
                        raise httpx.ConnectError('detalle privado del transporte')
                    if failure == 'timeout':
                        raise httpx.ReadTimeout('detalle privado del transporte')
                    if failure == 'http-error':
                        return httpx.Response(503, json={'error': 'detalle privado del servicio'})
                    if failure == 'bad-gzip':
                        return httpx.Response(200, headers={'Content-Encoding': 'gzip'},
                                              content=b'not-gzip')
                    return httpx.Response(200, content=b'not-json')

                model = OllamaModel('test-model', transport=httpx.MockTransport(chat))
                episode = run_game(model, seed=2, conversation_seed=21, episode='ollama-failure')
                decision = episode['turns'][0]['action']
                self.assertEqual([call['error'] for call in decision['calls']], [code, code])
                self.assertEqual(len(requests), 2)
                self.assertEqual(requests[0], requests[1])
                self.assertNotIn('automatic_discard', decision)
                self.assertEqual(episode['game']['closure']['interruption'], 'technical-failure')
                self.assertIsNone(episode['game']['closure']['result'])
                self.assertNotIn('detalle privado', str(episode))
