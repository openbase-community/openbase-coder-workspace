import json
import unittest
from backend_tools import tool_events


class BackendToolsTests(unittest.TestCase):
    def test_filesystem_and_dispatch_calls_are_both_retained(self):
        record = {'content': [{'name': name, 'input': {'example': True}, 'id': str(i)}
            for i, name in enumerate(('Bash', 'Read', 'Skill', 'mcp__super-agents__super_agents_start'))]}
        rows = tool_events('[2026-09-18T05:00:00.123Z] '+json.dumps(record), 'dispatcher')
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]['event'], 'observed Bash')
        self.assertEqual(rows[-1]['metadata']['tool_use_id'], '3')
        self.assertAlmostEqual(rows[0]['unix_ms'], 1789707600123)

    def test_tool_results_and_truncated_records_do_not_invent_calls(self):
        records = ['truncated JSON fragment', '[2026-09-18T05:00:00Z] ERROR timeout',
            '[2026-09-18T05:00:00Z] '+json.dumps({'content': [{'text': 'Bash failed'}],
                'tool_use_result': {'name': 'Bash', 'input': {'command': 'not an invocation'}}})]
        self.assertEqual(tool_events('\n'.join(records), 'dispatcher'), [])
