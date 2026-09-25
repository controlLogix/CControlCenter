"""Installed-plugin launcher tests; set AGENTMUX_PLUGIN_ROOT for external checkout."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

def plugin_location():
    configured = os.environ.get('AGENTMUX_PLUGIN_ROOT')
    if configured:
        return Path(configured)
    config = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude')))
    for base in dict.fromkeys((config, Path.home() / '.claude')):
        registry = base / 'plugins/known_marketplaces.json'
        if registry.is_file():
            entries = json.loads(registry.read_text())
            location = entries.get('adaggroup', {}).get('installLocation')
            if location:
                return Path(location) / 'plugins/agentmux-orchestration'
    return Path(__file__).resolve().parents[2] / 'marketplace/plugins/agentmux-orchestration'

import ninep

PLUGIN = plugin_location()

# reachable(), not is_dir(): the plugin lives on /mnt/c, and is_dir() re-raises
# EIO rather than answering.
@unittest.skipUnless(ninep.reachable(PLUGIN),
                     'external plugin absent or unreadable; set AGENTMUX_PLUGIN_ROOT')
class InstalledLauncher(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.installed = self.root / 'installed copy'
        # 9p can fail mid-copy; that is the subject being unreadable, not a defect.
        ninep.guard(shutil.copytree, PLUGIN, PLUGIN, self.installed)
        self.launcher = self.installed / 'skills/agent-config/scripts/runtime.py'
        self.runtime = self.root / 'runtime with spaces'
        (self.runtime / 'taskmgmt').mkdir(parents=True)
        for filename in ('coordination.py', 'dispatch.py', 'setup_auth.py'):
            (self.runtime / 'taskmgmt' / filename).write_text(
                'import json,sys\nprint(json.dumps(sys.argv[1:]))\n'
                'print("fixture refusal", file=sys.stderr)\nsys.exit(7)\n')

    def invoke(self, *args, binding=None):
        env = dict(os.environ)
        env.pop('AGENTMUX_REPO', None)
        if binding is not None:
            env['AGENTMUX_REPO'] = str(binding)
        return subprocess.run([sys.executable, str(self.launcher), *args],
            cwd=self.root, env=env, capture_output=True, text=True)

    def test_relocated_copy_preserves_arguments_and_refusals(self):
        for command in ('coordination', 'dispatch', 'setup-auth'):
            with self.subTest(command=command):
                args = ['approve', 'TM-058', '--member', 'name with spaces', '$(false)']
                result = self.invoke(command, *args, binding=self.runtime)
                self.assertEqual(result.returncode, 7)
                self.assertEqual(json.loads(result.stdout), args)
                self.assertEqual(result.stderr.strip(), 'fixture refusal')

    def test_missing_and_relative_binding_refuse(self):
        for binding in (None, 'relative/path'):
            result = self.invoke('coordination', binding=binding)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('absolute installed agentmux checkout', result.stderr)

    def test_incomplete_runtime_refuses(self):
        result = self.invoke('coordination', binding=self.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing installed command', result.stderr)

    def test_arbitrary_script_selector_refuses(self):
        result = self.invoke('../../arbitrary', binding=self.runtime)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('expected coordination, dispatch, or setup-auth', result.stderr)

if __name__ == '__main__':
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(InstalledLauncher))
    failed = len(result.failures) + len(result.errors)
    passed = result.testsRun - failed - len(result.skipped)
    print(f'passed {passed}, failed {failed}')
    sys.exit(bool(failed))
