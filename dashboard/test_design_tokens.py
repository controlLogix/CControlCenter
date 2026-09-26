"""The design system's invariants, enforced rather than intended.

WHAT THIS IS FOR. design/tokens.css claims that every colour, curve and
duration is decided in one place, and that all motion can be switched off from
one block. Both claims are worth exactly as much as the thing that checks them,
because the failure mode is silent: one hex literal in a component, and the
light theme has an invisible label that nobody sees until an operator opens it
in a lit room. One duration literal, and prefers-reduced-motion stops meaning
what it says for a person who needs it to.

The specific lies this suite is here to prevent, each of which is a real
instance of the general one this project keeps finding:

  - A VALUE THAT ANIMATES displays numbers that were never true for the length
    of the tween. On a live tag table that is a false reading, not a polish
    detail. .is-value must opt out of transitions and animations, and it must
    do so with !important, or a more specific component rule silently wins.
  - A PULSE MEANING "LIVE" is a freshness claim made by CSS rather than by
    measurement. It must be gated on data-live, which only the freshness logic
    sets - the same argument as the un-aged value TM-025 was about.
  - A REVEAL THAT NEVER FIRES is a blank product. The hiding must apply only
    after the script has claimed the document.

PARSED, NOT GREPPED. Three times in this project a check grepped source and
tripped on the prose explaining why the thing it looked for was absent -
docstrings saying "no generic_message passthrough", a .gitignore comment naming
the path it pins. So every check below strips comments first and reads
declarations, not lines.
"""
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DESIGN = HERE.parent / 'design'

TOKENS = DESIGN / 'tokens.css'
MOTION = DESIGN / 'motion.css'
MOTION_JS = DESIGN / 'motion.js'
FIELD_JS = DESIGN / 'field.js'


def strip_css_comments(text):
    """Remove /* ... */ so prose can never satisfy or trip a check."""
    return re.sub(r'/\*.*?\*/', '', text, flags=re.S)


def strip_js_comments(text):
    """Remove /* ... */ and // ... . Crude on purpose: it over-removes inside a
    string literal, which is the safe direction - it can only cause a check to
    look at less, never at prose."""
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'(?m)//.*$', '', text)


def declarations(text):
    """Every `prop: value` pair in a stylesheet, comments already gone."""
    out = []
    for raw in re.findall(r'([-a-zA-Z]+)\s*:\s*([^;{}]+)', strip_css_comments(text)):
        out.append((raw[0].strip(), raw[1].strip()))
    return out


def _body_at(text, open_index):
    """The text between the brace at `open_index` and its match. Brace-counting,
    because a regex cannot do this and the naive version silently returns the
    WRONG body for anything nested - which is how the first run of this suite
    reported 'there is no prefers-reduced-motion block' about a file that has
    one. A check that reports something untrue is the defect this whole project
    keeps finding; it does not get an exception for being a test."""
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[open_index + 1:i]
    return ''


def blocks(text, selector):
    """The body of every block whose selector text contains `selector`, and of
    every block nested inside one - so a `:root` inside an `@media` is found by
    searching for either."""
    clean = strip_css_comments(text)
    found = []
    for match in re.finditer(r'([^{}]+)\{', clean):
        if selector not in match.group(1):
            continue
        body = _body_at(clean, match.end() - 1)
        if '{' in body:
            # A wrapper such as @media: take every block inside it, since the
            # declarations live in the children rather than here.
            for inner in re.finditer(r'[^{}]+\{', body):
                found.append(_body_at(body, inner.end() - 1))
        else:
            found.append(body)
    return found


def custom_properties(text):
    """Every --name defined anywhere, mapped to its last value."""
    props = {}
    for name, value in declarations(text):
        if name.startswith('--'):
            props[name] = value
    return props


def properties_in_block(body):
    return {n: v for n, v in declarations(body) if n.startswith('--')}


class FilesExist(unittest.TestCase):
    def test_the_four_design_files_are_present(self):
        for path in (TOKENS, MOTION, MOTION_JS, FIELD_JS):
            self.assertTrue(path.is_file(), f'{path} is missing')


class TokensAreTheOnlyPlaceAColourIsDecided(unittest.TestCase):
    """A hex literal outside tokens.css is a colour that cannot be rethemed."""

    def test_motion_css_contains_no_colour_literal_outside_a_keyframe(self):
        # Keyframes legitimately carry an rgb() for a flash, and that one is
        # allowed because it is a transient overlay rather than a surface. Any
        # OTHER literal is a second source of truth for the palette.
        clean = strip_css_comments(MOTION.read_text(encoding='utf-8'))
        # Drop keyframe bodies before looking.
        without_keyframes = re.sub(r'@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}',
                                   '', clean, flags=re.S)
        hexes = re.findall(r'#[0-9a-fA-F]{3,8}\b', without_keyframes)
        self.assertEqual(hexes, [], f'hex literals outside keyframes: {hexes}')

    def test_field_js_reads_its_palette_from_the_tokens(self):
        # A shader with its own hex literals is the one copy of the palette
        # nobody remembers to update when the theme changes.
        src = strip_js_comments(FIELD_JS.read_text(encoding='utf-8'))
        self.assertIn('getPropertyValue', src,
                      'the field must read colours from the document, not hold them')
        for token in ('--cool-deep', '--accent', '--surface-void'):
            self.assertIn(token, src, f'the field never reads {token}')


class EveryDurationIsSwitchable(unittest.TestCase):
    """The whole argument for duration tokens is that one block turns them off."""

    def setUp(self):
        self.text = TOKENS.read_text(encoding='utf-8')
        self.props = custom_properties(self.text)

    def test_motion_css_declares_no_literal_duration(self):
        # A literal here is a duration prefers-reduced-motion cannot reach.
        clean = strip_css_comments(MOTION.read_text(encoding='utf-8'))
        offenders = []
        for name, value in declarations(clean):
            if name in ('transition', 'transition-duration', 'transition-delay',
                        'animation-duration', 'animation-delay'):
                for literal in re.findall(r'(?<![\w-])(\d+(?:\.\d+)?)(ms|s)\b', value):
                    if literal[0] not in ('0',):
                        offenders.append(f'{name}: {value}')
        self.assertEqual(offenders, [],
                         f'literal durations that reduced-motion cannot reach: {offenders}')

    def test_reduced_motion_zeroes_every_duration_token(self):
        durations = [n for n in self.props if n.startswith('--dur-') or n == '--dur']
        self.assertTrue(durations, 'no duration tokens found at all')
        bodies = blocks(self.text, 'prefers-reduced-motion')
        self.assertTrue(bodies, 'there is no prefers-reduced-motion block')
        zeroed = {}
        for body in bodies:
            zeroed.update(properties_in_block(body))
        # The invariant is that the EFFECTIVE value is zero, not that every
        # token is restated in the override block. --dur-instant is already
        # 0ms, and demanding it be overridden would be the test asking for
        # something the rule does not require - which is how a correct file
        # gets edited to satisfy a wrong check.
        for token in durations:
            effective = zeroed.get(token, self.props.get(token, ''))
            self.assertEqual(effective.rstrip(';').strip(), '0ms',
                             f'{token} is {effective!r} under reduced motion, not 0ms')

    def test_reduced_motion_also_zeroes_the_stagger_and_the_field(self):
        # A staggered reveal with zero duration still arrives in sequence,
        # which is the same problem more slowly. And the animated field is
        # motion too, whatever else it is.
        bodies = blocks(self.text, 'prefers-reduced-motion')
        zeroed = {}
        for body in bodies:
            zeroed.update(properties_in_block(body))
        self.assertEqual(zeroed.get('--stagger', '').strip(), '0ms')
        self.assertIn('--field-opacity', zeroed)

    def test_there_is_an_operator_switch_independent_of_the_os(self):
        # A plant-floor machine may need motion off without changing Windows.
        bodies = blocks(self.text, 'data-motion="off"')
        self.assertTrue(bodies, 'no explicit data-motion=off switch')
        off = {}
        for body in bodies:
            off.update(properties_in_block(body))
        for token in ('--dur', '--stagger', '--field-opacity', '--grain-opacity'):
            self.assertIn(token, off, f'data-motion=off does not reach {token}')


class BothThemesDefineTheSameTokens(unittest.TestCase):
    """A token missing from a theme is an invisible label in that theme."""

    def test_the_light_theme_overrides_every_colour_the_dark_one_defines(self):
        text = TOKENS.read_text(encoding='utf-8')
        light = {}
        for body in blocks(text, 'data-theme="light"'):
            light.update(properties_in_block(body))
        self.assertTrue(light, 'there is no light theme block')

        # The root block is the first :root that is not a theme or a media query.
        root = {}
        for body in blocks(text, ':root'):
            props = properties_in_block(body)
            if '--surface-base' in props:
                root = props
                break
        self.assertTrue(root, 'could not find the base :root token block')

        # Only the tokens that ARE colours. --text-md is a type size and has no
        # business differing between themes; --text-muted is a colour and must.
        # The first version of this matched on the --text- prefix and reported
        # the size scale as missing, which is a check that would have been
        # deleted for crying wolf rather than fixed.
        colourish = re.compile(
            r'^--(surface|line|cool|ok|warn|bad|unknown)'
            r'|^--accent(-|$)'
            r'|^--text-(primary|secondary|muted|faint|on-accent)$')
        missing = sorted(n for n in root if colourish.match(n) and n not in light)
        self.assertEqual(missing, [],
                         f'defined for dark but not for light: {missing}')

    def test_the_accent_ramp_does_not_invert_into_illegibility(self):
        # Orange on white at the hot end is unreadable, so the light theme
        # DARKENS the ramp rather than flipping it. Assert it actually differs,
        # because a copy-paste of the dark values would look like an override.
        text = TOKENS.read_text(encoding='utf-8')
        light = {}
        for body in blocks(text, 'data-theme="light"'):
            light.update(properties_in_block(body))
        root = {}
        for body in blocks(text, ':root'):
            props = properties_in_block(body)
            if '--surface-base' in props:
                root = props
                break
        self.assertNotEqual(root.get('--accent-hot'), light.get('--accent-hot'),
                            'the light theme reuses the dark hot accent verbatim')
        self.assertNotEqual(root.get('--text-on-accent'), light.get('--text-on-accent'))


class MotionCannotMakeTheProductLie(unittest.TestCase):
    """The three guards, each asserted on the rule rather than on a comment."""

    def setUp(self):
        self.css = MOTION.read_text(encoding='utf-8')

    def test_a_value_opts_out_of_transition_and_animation(self):
        bodies = blocks(self.css, '.is-value')
        self.assertTrue(bodies, '.is-value is not defined at all')
        joined = ' '.join(bodies)
        self.assertRegex(joined, r'transition-property\s*:\s*none\s*!important',
                         'a value can still transition')
        self.assertRegex(joined, r'animation\s*:\s*none\s*!important',
                         'a value can still animate')

    def test_the_value_guard_reaches_descendants(self):
        # The digits are usually a child of the element carrying the class.
        clean = strip_css_comments(self.css)
        self.assertRegex(clean, r'\.is-value\s*,\s*\.is-value\s*\*',
                         'the guard does not reach the element that holds the digits')

    def test_the_live_pulse_is_gated_on_measured_liveness(self):
        # A pulse that any component can switch on is a freshness claim made by
        # CSS. It must require the attribute the freshness logic sets.
        clean = strip_css_comments(self.css)
        for match in re.finditer(r'([^{}]*is-live-pulse[^{}]*)\{', clean):
            selector = match.group(1)
            self.assertIn('data-live="true"', selector,
                          f'ungated liveness animation: {selector.strip()}')

    def test_a_reveal_cannot_blank_the_page(self):
        clean = strip_css_comments(self.css)
        self.assertIn('html:not([data-motion-ready])', clean,
                      'reveals hide before the script claims the document, so a '
                      'script that fails to load leaves an empty product')

    def test_the_overshoot_curve_is_not_used_on_anything_showing_a_value(self):
        # A number that springs past itself and settles has, for two frames,
        # displayed a reading that was never true.
        clean = strip_css_comments(self.css)
        for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', clean):
            if 'ease-spring' in match.group(2):
                self.assertNotIn('value', match.group(1),
                                 f'overshoot on a value: {match.group(1).strip()}')


class TheRuntimeIsHonestAboutFailing(unittest.TestCase):
    """motion.js and field.js must degrade to a working product, not a broken one."""

    def test_the_stagger_is_capped(self):
        src = strip_js_comments(MOTION_JS.read_text(encoding='utf-8'))
        self.assertIn('STAGGER_CAP', src)
        self.assertRegex(src, r'Math\.min\([^)]*STAGGER_CAP',
                         'the stagger index is not actually clamped to the cap')

    def test_there_is_a_backstop_that_reveals_everything(self):
        # Whatever happened - a detached subtree, a container display:none at
        # first paint, an observer that never fired - nothing stays invisible.
        src = strip_js_comments(MOTION_JS.read_text(encoding='utf-8'))
        self.assertIn('SAFETY_MS', src)
        self.assertRegex(src, r'setTimeout\(\s*\(\)\s*=>\s*revealEverything',
                         'there is no timed backstop')

    def test_no_observer_means_visible_not_hidden(self):
        src = strip_js_comments(MOTION_JS.read_text(encoding='utf-8'))
        self.assertIn("typeof IntersectionObserver === 'undefined'", src)
        self.assertIn('revealEverything', src)

    def test_the_field_pauses_when_nobody_is_looking(self):
        # These machines sit on a line for weeks.
        src = strip_js_comments(FIELD_JS.read_text(encoding='utf-8'))
        self.assertIn('visibilitychange', src)
        self.assertIn('document.hidden', src)

    def test_the_field_survives_a_lost_context_by_removing_itself(self):
        src = strip_js_comments(FIELD_JS.read_text(encoding='utf-8'))
        self.assertIn('webglcontextlost', src)

    def test_the_field_never_reports_an_error_to_the_operator(self):
        # It is decoration. A shader that cannot compile on a plant-floor Intel
        # driver must leave the product exactly as it was, not raise a banner.
        src = strip_js_comments(FIELD_JS.read_text(encoding='utf-8'))
        for banned in ('alert(', 'console.error', 'throw new Error'):
            self.assertNotIn(banned, src,
                             f'the field can surface {banned} to a person')

    def test_neither_runtime_uses_a_blocking_dialog(self):
        for path in (MOTION_JS, FIELD_JS):
            src = strip_js_comments(path.read_text(encoding='utf-8'))
            for banned in ('window.confirm', 'window.alert', 'confirm(', 'alert('):
                self.assertNotIn(banned, src, f'{path.name} uses {banned}')


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failed - len(result.skipped)}, failed {failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
