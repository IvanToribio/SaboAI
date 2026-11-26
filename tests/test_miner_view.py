import json
import unittest

from saboteurai.cards import Card
from saboteurai.records import PublicMessage, miner_view, record_attempt, start_record
from saboteurai.state import GameState, PlayerState, Tile, new_game


def game_record(*extra_cards: Card):
    players = [
        PlayerState(0, 'miner', [Card('map-0', 'map'), *extra_cards]),
        PlayerState(1, 'miner', [Card('path-1', 'cross')]),
        PlayerState(2, 'miner'),
        PlayerState(3, 'miner'),
        PlayerState(4, 'miner'),
    ]
    board = {
        (0, 0): Tile(Card('start', 'start'), 0, 0),
        (8, -2): Tile(Card('goal-0', 'stone-a'), 8, -2, revealed=False),
        (8, 0): Tile(Card('goal-1', 'gold'), 8, 0, revealed=False),
        (8, 2): Tile(Card('goal-2', 'stone-b'), 8, 2, revealed=False),
    }
    state = GameState(players, board)
    return start_record(state, {'episode': 'test'})


class MinerViewTests(unittest.TestCase):
    def test_inspection_result_is_visible_only_to_the_miner_who_inspected(self):
        record = game_record()
        record_attempt(record, 0, {'kind': 'inspect', 'card_id': 'map-0', 'x': 8, 'y': 0})

        inspector = miner_view(record, 0)
        self.assertEqual(inspector['inspections'], [{'turn': 1, 'x': 8, 'y': 0, 'type': 'gold'}])

        for miner in range(1, 5):
            with self.subTest(miner=miner):
                observer = miner_view(record, miner)
                self.assertEqual(observer['inspections'], [])
                self.assertEqual(observer['public_actions'], [
                    {'turn': 1, 'kind': 'inspect', 'actor': 0, 'x': 8, 'y': 0},
                ])
                self.assertNotIn('gold', json.dumps(observer))

    def test_view_keeps_each_private_inspection_with_its_turn(self):
        record = game_record(Card('map-repeat', 'map'))
        record_attempt(record, 0, {'kind': 'inspect', 'card_id': 'map-0', 'x': 8, 'y': 0})
        record_attempt(record, 1, {'kind': 'discard', 'card_id': 'path-1'})
        record_attempt(record, 0, {'kind': 'inspect', 'card_id': 'map-repeat', 'x': 8, 'y': 0})

        self.assertEqual(miner_view(record, 0)['inspections'], [
            {'turn': 1, 'x': 8, 'y': 0, 'type': 'gold'},
            {'turn': 3, 'x': 8, 'y': 0, 'type': 'gold'},
        ])

    def test_view_keeps_inspections_from_before_the_start_of_the_record(self):
        state = new_game(0, 11)
        gold_position = next(pos for pos, tile in state.board.items() if tile.card.type == 'gold')
        state.players[0].inspections[gold_position] = 'gold'
        record = start_record(state, {'episode': 'snapshot'})

        x, y = gold_position
        self.assertEqual(miner_view(record, 0)['inspections'], [
            {'turn': None, 'x': x, 'y': y, 'type': 'gold'},
        ])
        self.assertEqual(miner_view(record, 1)['inspections'], [])

    def test_miner_view_rejects_a_saboteur_id(self):
        state = new_game(1, 11)
        saboteur = next(player.id for player in state.players if player.role == 'saboteur')
        record = start_record(state, {'episode': 'legacy'})

        with self.assertRaises(ValueError):
            miner_view(record, saboteur)

    def test_view_shows_current_public_state_own_hand_and_active_miner_actions(self):
        record = game_record()
        active = miner_view(record, 0)
        waiting = miner_view(record, 1)

        self.assertEqual((active['miner_id'], active['active'], active['turn']), (0, 0, 1))
        self.assertEqual(active['status'], 'playing')
        self.assertEqual(active['hand'], [{'id': 'map-0', 'type': 'map'}])
        self.assertEqual(waiting['hand'], [{'id': 'path-1', 'type': 'cross'}])
        self.assertEqual(active['board'], [
            {'x': 0, 'y': 0, 'type': 'start', 'rotation': 0},
            {'x': 8, 'y': -2, 'hidden': True},
            {'x': 8, 'y': 0, 'hidden': True},
            {'x': 8, 'y': 2, 'hidden': True},
        ])
        self.assertEqual(active['players'], [{'id': i, 'pick_ok': True} for i in range(5)])
        self.assertEqual(waiting['board'], active['board'])
        self.assertEqual(active['legal_actions'], [
            {'kind': 'inspect', 'card_id': 'map-0', 'x': 8, 'y': -2},
            {'kind': 'inspect', 'card_id': 'map-0', 'x': 8, 'y': 0},
            {'kind': 'inspect', 'card_id': 'map-0', 'x': 8, 'y': 2},
            {'kind': 'discard', 'card_id': 'map-0'},
        ])
        self.assertEqual(waiting['legal_actions'], [])
        self.assertNotIn('path-1', json.dumps(active))
        self.assertNotIn('map-0', json.dumps(waiting))

    def test_view_keeps_all_published_messages_in_order_including_public_disclosures(self):
        record = game_record()
        record_attempt(record, 0, {'kind': 'inspect', 'card_id': 'map-0', 'x': 8, 'y': 0})
        messages: list[PublicMessage] = [
            {'turn': 1, 'speaker': 4, 'text': '¿Alguien tiene un mapa?'},
            {'turn': 1, 'speaker': 2, 'text': 'Yo no.'},
            {'turn': 2, 'speaker': 0, 'text': 'He visto oro en (8, 0).'},
        ]

        for miner in range(5):
            with self.subTest(miner=miner):
                view = miner_view(record, miner, public_messages=messages)
                self.assertEqual(view['public_messages'], messages)

        miner_view(record, 0, public_messages=messages)['public_messages'][0]['text'] = 'Texto modificado'
        self.assertEqual(messages[0]['text'], '¿Alguien tiene un mapa?')

    def test_changing_hidden_state_does_not_change_the_active_miners_view(self):
        state = new_game(0, 11)
        miner = state.active
        original = miner_view(start_record(state, {'episode': 'first'}), miner)

        north = state.board[8, -2]
        center = state.board[8, 0]
        north.card, center.card = center.card, north.card
        other_hand = state.players[(miner + 1) % 5].hand
        other_hand[0], state.deck[-1] = state.deck[-1], other_hand[0]
        state.setup['seed'] = 12

        changed = miner_view(start_record(state, {'episode': 'second'}), miner)
        self.assertEqual(changed, original)

    def test_view_keeps_public_events_in_order_and_excludes_rejected_attempts(self):
        record = game_record()
        record_attempt(record, 0, {'kind': 'inspect', 'card_id': 'map-0', 'x': 8, 'y': 0})
        record_attempt(record, 1, {'kind': 'discard', 'card_id': 'unpublished-attempt'})
        record_attempt(record, 1, {'kind': 'discard', 'card_id': 'path-1'})

        view = miner_view(record, 1)
        self.assertEqual(view['status'], 'finished')
        self.assertIsNone(view['active'])
        self.assertEqual(view['legal_actions'], [])
        self.assertEqual(view['public_actions'], [
            {'turn': 1, 'kind': 'inspect', 'actor': 0, 'x': 8, 'y': 0},
            {'turn': 2, 'kind': 'discard', 'actor': 1},
            {'turn': 2, 'kind': 'result', 'miners_success': False, 'reason': 'empty'},
        ])
        self.assertNotIn('unpublished-attempt', json.dumps(view))
