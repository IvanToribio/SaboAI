from collections import Counter
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from saboteurai.cards import CARDS, Card
from saboteurai.engine import apply_action, legal_actions
from saboteurai.records import (loads_record, record_attempt, record_interruption,
                                replay_record, save_record, start_record)
from saboteurai.state import GameState, PlayerState, Tile, new_game


def scenario(*hands):
    """Five miners, explicit hands, empty draw pile and known goal positions."""
    players = [PlayerState(i, 'miner') for i in range(5)]
    for player, types in zip(players, hands):
        player.hand = [Card(f'p{player.id}-{index}', kind) for index, kind in enumerate(types)]
    board = {(0, 0): Tile(Card('start', 'start'), 0, 0)}
    for y, kind in [(-2, 'gold'), (0, 'stone-a'), (2, 'stone-b')]:
        board[8, y] = Tile(Card(kind, kind), 8, y, revealed=False)
    return GameState(players, board)


def place(card_id, x, y=0, rotation=0):
    return dict(kind='place', card_id=card_id, x=x, y=y, rotation=rotation)


class EngineTests(unittest.TestCase):
    def play(self, state, request):
        result = apply_action(state, state.active, request)
        self.assertTrue(result.accepted, result.error)
        return result.state

    def test_seed_repeats_five_miner_deal(self):
        state = new_game(0, 42)
        self.assertEqual(state, new_game(0, 42))
        other_deal = new_game(0, 43)
        self.assertNotEqual([p.hand for p in state.players], [p.hand for p in other_deal.players])
        self.assertEqual([p.role for p in state.players], ['miner'] * 5)
        self.assertEqual([len(p.hand) for p in state.players], [6] * 5)
        self.assertEqual(len(state.deck), 17)
        cards = state.deck + [card for p in state.players for card in p.hand]
        self.assertEqual(len({card.id for card in cards}), 47)
        self.assertEqual(Counter(CARDS[c.type].kind for c in cards),
                         {'path': 32, 'map': 3, 'rockfall': 3, 'repair': 4, 'break': 5})
        self.assertEqual(state.board[0, 0].card.type, 'start')
        self.assertCountEqual([t.card.type for t in state.board.values() if not t.revealed],
                              ['gold', 'stone-a', 'stone-b'])

    def test_rotating_a_bend_changes_which_side_of_the_entrance_fits(self):
        state = scenario(['bend-se'])
        actions = legal_actions(state, 0)
        for x, rotation, fits in [(-1, 0, True), (1, 180, True),
                                  (1, 0, False), (-1, 180, False)]:
            with self.subTest(x=x, rotation=rotation):
                request = place('p0-0', x, rotation=rotation)
                self.assertEqual(request in actions, fits)
                self.assertEqual(apply_action(state, 0, request).accepted, fits)

    def test_reachable_placement_must_match_its_second_neighbor(self):
        state = scenario(['bend-se', 'cross'])
        state.board[0, 1] = Tile(Card('corner', 'bend-sw'), 0, 1, rotation=180)
        state.board[1, 1] = Tile(Card('junction', 'cross'), 1, 1)
        # Both cards open west to the entrance. Only the cross also opens south.
        bend = place('p0-0', 1, rotation=180)
        self.assertNotIn(bend, legal_actions(state, 0))
        self.assertEqual(apply_action(state, 0, bend).error, 'mismatch')
        self.assertIn((1, 0), self.play(state, place('p0-1', 1)).board)

    def test_cut_tunnel_does_not_connect_its_far_end(self):
        state = scenario(['dead-h', 'straight-h'])
        state = self.play(state, place('p0-0', 1))
        extend = place('p0-1', 2)
        self.assertNotIn(extend, legal_actions(state, 0))
        self.assertEqual(apply_action(state, 0, extend).error, 'unreachable')

    def test_rockfall_disconnects_a_branch_until_the_gap_is_filled(self):
        state = scenario(['rockfall', 'straight-h', 'straight-h'])
        for x in (1, 2):
            state.board[x, 0] = Tile(Card(f'tunnel-{x}', 'straight-h'), x, 0)
        extend = place('p0-2', 3)
        self.assertIn(extend, legal_actions(state, 0))
        state = self.play(state, dict(kind='rockfall', card_id='p0-0', x=1, y=0))
        self.assertNotIn((1, 0), state.board)
        self.assertIn((2, 0), state.board)
        self.assertEqual(apply_action(state, 0, extend).error, 'unreachable')
        state = self.play(state, place('p0-1', 1))
        self.assertIn((3, 0), self.play(state, extend).board)

    def test_only_the_inspecting_miner_learns_the_destination(self):
        state = scenario(['map'], ['straight-h'])
        result = apply_action(state, 0, dict(kind='inspect', card_id='p0-0', x=8, y=-2))
        self.assertTrue(result.accepted, result.error)
        self.assertFalse(result.state.board[8, -2].revealed)
        self.assertEqual(result.public_events, [dict(kind='inspect', actor=0, x=8, y=-2)])
        self.assertEqual(result.private_events, {0: [dict(kind='inspection', x=8, y=-2, type='gold')]})
        self.assertEqual([p.inspections for p in result.state.players], [{(8, -2): 'gold'}, {}, {}, {}, {}])

    def test_broken_pick_blocks_placement_until_repaired(self):
        state = scenario(['break-pick'], ['straight-h', 'repair-pick'])
        state = self.play(state, dict(kind='break', card_id='p0-0', target=1, tool='pick'))
        tunnel = place('p1-0', 1)
        self.assertNotIn(tunnel, legal_actions(state, 1))
        self.assertEqual(apply_action(state, 1, tunnel).error, 'pick-broken')
        state = self.play(state, dict(kind='repair', card_id='p1-1', target=1, tool='pick'))
        self.assertIn((1, 0), self.play(state, tunnel).board)

    def test_rejected_requests_preserve_the_entire_state(self):
        state = new_game(0, 42)
        actor = state.active
        other = (actor + 1) % 5
        discard = dict(kind='discard', card_id=state.players[actor].hand[0].id)
        original = deepcopy(state)
        for player, request, error in [
            (other, discard, 'out-of-turn'),
            (actor, dict(kind='discard'), 'schema'),
            (actor, dict(kind='discard', card_id=state.players[other].hand[0].id), 'card-unavailable'),
        ]:
            with self.subTest(error=error):
                result = apply_action(state, player, request)
                self.assertFalse(result.accepted)
                self.assertEqual(result.error, error)
                self.assertEqual(result.state, original)
                self.assertEqual(state, original)

    def test_stone_connects_to_gold_and_saved_win_detects_a_changed_transition(self):
        state = scenario(['straight-h'], ['straight-v'])
        for x in range(1, 7):
            state.board[x, 0] = Tile(Card(f'tunnel-{x}', 'straight-h'), x, 0)
        record = start_record(state, {'episode': 'stone-then-gold'})
        first = record_attempt(record, 0, place('p0-0', 7))
        self.assertTrue(first.accepted, first.error)
        self.assertTrue(first.state.board[8, 0].revealed)
        self.assertEqual(first.state.status, 'playing')
        last = record_attempt(record, 1, place('p1-0', 8, -1))
        self.assertTrue(last.accepted, last.error)
        self.assertTrue(last.state.board[8, -2].revealed)
        self.assertEqual(last.state.status, 'finished')
        self.assertEqual(last.state.result, dict(miners_success=True, reason='gold', saboteur_wins=False))
        with TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'game.json'
            save_record(record, path)
            loaded = loads_record(path.read_text(encoding='utf-8'))
        self.assertEqual(loaded, record)
        self.assertEqual(replay_record(loaded), dict(matches=True, entries=2))
        loaded['attempts'][0]['state']['turn'] += 1
        self.assertEqual(replay_record(loaded), dict(matches=False, entry=1, code='transition-mismatch'))

    def test_last_discard_finishes_only_after_draw_pile_and_hands_are_empty(self):
        state = scenario(['straight-v'])
        state.deck = [Card('last', 'map')]
        record = start_record(state, {'episode': 'last-draw'})
        first = record_attempt(record, 0, dict(kind='discard', card_id='p0-0'))
        self.assertEqual(first.state.players[0].hand, [Card('last', 'map')])
        self.assertEqual(first.state.status, 'playing')
        self.assertEqual(first.public_events, [dict(kind='discard', actor=0), dict(kind='draw', actor=0)])
        last = record_attempt(record, 0, dict(kind='discard', card_id='last'))
        self.assertEqual(last.state.status, 'finished')
        self.assertEqual(last.state.result, dict(miners_success=False, reason='empty', saboteur_wins=False))
        self.assertEqual(replay_record(record), dict(matches=True, entries=2))

    def test_interruption_after_a_rejection_replays_without_a_game_result(self):
        record = start_record(scenario(['map']), {'episode': 'manual-stop'})
        rejected = record_attempt(record, 0, dict(kind='discard', card_id='missing'))
        self.assertFalse(rejected.accepted)
        record_interruption(record, 'manual-stop')
        self.assertEqual(record['closure'], dict(status='interrupted', result=None, interruption='manual-stop'))
        self.assertEqual(replay_record(record), dict(matches=True, entries=2))
