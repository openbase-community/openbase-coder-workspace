import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from network_transition import restoration_program, profile_commands


class NetworkTransitionTests(unittest.TestCase):
    def test_canceled_schedule_cannot_create_a_plotted_outage(self):
        from plot_annotations import loss_intervals
        planned=[dict(event='network_loss_transition_scheduled',capture_relative_s=10),
                 dict(event='network_loss_transition_schedule_canceled',capture_relative_s=11)]
        self.assertEqual(loss_intervals(planned,600),[])
        rows=planned+[dict(event='network_loss_transition_guest_apply_completed',capture_relative_s=170,metadata={'transition_id':'a'}),
                      dict(event='network_loss_transition_guest_restore_started',capture_relative_s=205,metadata={'transition_id':'a','status':'restored_prior_profile'})]
        self.assertEqual(loss_intervals(rows,600),[(170,205,'Injected network loss')])

    def test_loss_transition_explicitly_preserves_bandwidth_and_delay(self):
        profile=dict(up_kbit=768,down_kbit=128,delay_ms_each_way=200,configured_loss=.02)
        commands=profile_commands(profile,.99)
        self.assertEqual([c[5] for c in commands],['768Kbit/s','128Kbit/s'])
        self.assertTrue(all(c[-3:]==['200ms','plr','0.99'] for c in commands))

    def test_delayed_restore_cannot_change_a_new_owners_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            owner,marker=Path(temp,'owner'),Path(temp,'marker')
            owner.write_text('new-owner')
            profile=dict(up_kbit=768,down_kbit=128,delay_ms_each_way=200,configured_loss=.02)
            with patch('subprocess.run') as run:
                exec(restoration_program(str(owner),'old-owner',profile,str(marker),0),{})
                run.assert_not_called()
            self.assertEqual(json.loads(marker.read_text())['status'],'withheld_stale_owner')

    def test_current_owner_restores_both_original_directional_parameters(self):
        with tempfile.TemporaryDirectory() as temp:
            owner,marker=Path(temp,'owner'),Path(temp,'marker')
            owner.write_text('123')
            profile=dict(up_kbit=768,down_kbit=128,delay_ms_each_way=200,configured_loss=.02)
            with patch('subprocess.run') as run:
                exec(restoration_program(str(owner),'123',profile,str(marker),0),{})
            commands=[call.args[0] for call in run.call_args_list]
            self.assertEqual([c[2] for c in commands],['30341','30342'])
            self.assertEqual([c[5] for c in commands],['768Kbit/s','128Kbit/s'])
            self.assertTrue(all(c[-1]=='0.02' for c in commands))
            self.assertEqual(json.loads(marker.read_text())['status'],'restored_prior_profile')
