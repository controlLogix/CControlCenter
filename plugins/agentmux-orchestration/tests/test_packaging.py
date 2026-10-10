"""Packaging checks exercise metadata and the real relocated launcher."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NAMES = {'agent-new','agent-roster','agent-edit','agent-remove','team-compose','team-dispatch','team-merge','agent-config','agent-doctor'}

class Packaging(unittest.TestCase):
    def test_nine_discoverable_guides(self):
        folders = {p.name for p in (ROOT / 'skills').iterdir() if p.is_dir()}
        self.assertEqual(folders, NAMES)
        descriptions = set()
        for name in sorted(NAMES):
            text = (ROOT / 'skills' / name / 'SKILL.md').read_text(encoding='utf-8')
            front, body = text.split('---', 2)[1:]
            fields = dict(line.split(': ', 1) for line in front.strip().splitlines())
            self.assertEqual(fields['name'], name)
            self.assertGreater(len(fields['description']), 40)
            descriptions.add(fields['description'])
            self.assertIn('runtime.py', body)
        self.assertEqual(len(descriptions), 9)

    def test_metadata_registers_real_entrypoints(self):
        manifest = json.loads((ROOT / '.claude-plugin/plugin.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['name'], 'agentmux-orchestration')
        mcp = json.loads((ROOT / '.mcp.json').read_text(encoding='utf-8'))['mcpServers']['agentmux-roster']
        self.assertEqual(mcp['args'][-1], 'mcp')
        entry = mcp['args'][0].replace('${CLAUDE_PLUGIN_ROOT}', str(ROOT))
        self.assertTrue(Path(entry).is_file())
        hooks = json.loads((ROOT / 'hooks/hooks.json').read_text(encoding='utf-8'))['hooks']['PreToolUse']
        self.assertEqual(len(hooks), 2)
        self.assertTrue((ROOT / 'hooks/agentmux-hook.sh').is_file())

    def test_relocated_real_runtime_help_without_provider(self):
        repo = ROOT.parents[1]
        with tempfile.TemporaryDirectory(prefix='agentmux package ') as temp:
            moved = Path(temp) / 'plugin with spaces'
            shutil.copytree(ROOT, moved)
            env = {'PATH': os.defpath, 'HOME': temp, 'AGENTMUX_HOME': str(Path(temp) / 'state'), 'CLAUDE_CONFIG_DIR': str(Path(temp) / 'claude'), 'CODEX_HOME': str(Path(temp) / 'codex'), 'AGENTMUX_REPO': str(repo), 'PYTHONDONTWRITEBYTECODE': '1'}
            for command in ['coordination','dispatch','setup-auth']:
                with self.subTest(command=command):
                    process = subprocess.run([sys.executable, str(moved / 'skills/agent-config/scripts/runtime.py'), command, '--help'], env=env, text=True, capture_output=True, timeout=20)
                    self.assertEqual(process.returncode, 0, process.stderr)
                    self.assertIn('usage:', process.stdout)

if __name__ == '__main__':
    unittest.main()