import json
import unittest

import httpx

from saboteurai.controller import run_game
from saboteurai.ollama_model import OllamaModel


class OllamaModelTests(unittest.TestCase):
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
