"""Actual JS collector -> working-tree CaptureSource -> import, offline only."""
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import sync
from source import CaptureSource, SourceError
from test_sync import NOW, SCOPE, fixture

ROOT = Path(__file__).resolve().parent
CONFIG = {key: SCOPE[key] for key in ('semester', 'start', 'end_exclusive')}
FIELDS = ('MCSID', 'CSID', 'CurriculumID', 'XXKMID', 'CurriculumType')
# Expectations are explicit; no Python truthiness conversion builds requests.
CASES = [('missing', None, ''), ('null', None, ''), ('empty', '', ''),
         ('number-zero', 0, '0'), ('string-zero', '0', '0'),
         ('number-one', 1, '1'), ('string-one', '1', '1')]


def collect(items_list):
    node = shutil.which('node')
    if node is None:
        raise unittest.SkipTest('Node.js is required for the real cross-language regression')
    result = subprocess.run([node, str(ROOT / 'capture_contract_fixture.mjs')],
        input=json.dumps([{'config': CONFIG, 'items': items} for items in items_list]),
        encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT,
        timeout=30, check=True)
    return json.loads(result.stdout)


def save_capture(root, capture):
    capture = {**capture, 'fetched_at': NOW}
    path = root / 'synthetic-capture.json'
    path.write_text(json.dumps(capture), encoding='utf-8')
    return path


class CaptureContractTests(unittest.TestCase):
    def test_real_js_requests_are_readable_for_all_five_parameters(self):
        scenarios = []
        for field in FIELDS:
            for name, value, expected in CASES:
                sample = fixture()
                if name == 'missing':
                    sample['event'].pop(field, None)
                else:
                    sample['event'][field] = value
                scenarios.append((field, name, expected, sample))
        captures = collect([[sample] for _, _, _, sample in scenarios])
        for (field, name, expected, sample), result in zip(scenarios, captures):
            with self.subTest(field=field, value=name), tempfile.TemporaryDirectory() as temp:
                capture = result['capture']
                request = capture['responses'][-1]
                self.assertEqual(request['params'][field], expected)
                source = CaptureSource(save_capture(Path(temp), capture), CONFIG)
                self.assertEqual(source.details(sample['event']), sample['details'])

    def test_real_js_optional_parameter_imports_all_seven_cases(self):
        samples = []
        for name, value, _ in CASES:
            sample = fixture()
            if name == 'missing':
                sample['event'].pop('XXKMID', None)
            else:
                sample['event']['XXKMID'] = value
            samples.append(sample)
        for (name, _, _), result in zip(CASES, collect([[s] for s in samples])):
            with self.subTest(value=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path = save_capture(root, result['capture'])
                with sync.exclusive_sync(root):
                    imported = sync.import_capture_unlocked(root, CONFIG, path, progress=lambda _: None)
                self.assertEqual(len(imported.snapshot['events']), 1)
                self.assertEqual(sync.load_current(root), imported.snapshot)

    def test_zero_and_empty_have_distinct_detail_cache_entries(self):
        first, second = fixture(), fixture()
        first['event']['XXKMID'] = 0
        second['event'].pop('XXKMID', None)
        second['details'][0]['Teacher'] = 'Second synthetic teacher'
        capture = collect([[first, second]])[0]['capture']
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = CaptureSource(save_capture(root, capture), CONFIG)
            bundle = sync.fetch_complete(source, CONFIG, root / 'run', progress=lambda _: None)
            self.assertEqual([item['details'] for item in bundle['items']],
                             [first['details'], second['details']])
            self.assertEqual(bundle['request_count'], len(capture['responses']))

    def test_legacy_string_requests_and_integral_json_numbers(self):
        sample = fixture()
        sample['event']['XXKMID'] = 0
        original = collect([[sample]])[0]['capture']
        for value in ('0', 0, 0.0):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp:
                capture = copy.deepcopy(original)
                capture['responses'][-1]['params']['XXKMID'] = value
                source = CaptureSource(save_capture(Path(temp), capture), CONFIG)
                self.assertEqual(source.details(sample['event']), sample['details'])

    def test_invalid_parameter_types_rejected_by_both_languages(self):
        invalid = (False, True, [], {}, 1.5, 9007199254740992)
        samples = []
        for value in invalid:
            sample = fixture()
            sample['event']['XXKMID'] = value
            samples.append(sample)
        valid_capture = collect([[fixture()]])[0]['capture']
        for value, sample, result in zip(invalid, samples, collect([[s] for s in samples])):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp:
                self.assertEqual(result.get('code'), 'DATA_VALIDATION')
                root = Path(temp)
                source = CaptureSource(save_capture(root, valid_capture), CONFIG)
                with self.assertRaises(SourceError):
                    source.details(sample['event'])
                malformed = copy.deepcopy(valid_capture)
                malformed['responses'][-1]['params']['XXKMID'] = value
                with self.assertRaises(SourceError):
                    CaptureSource(save_capture(root, malformed), CONFIG)


if __name__ == '__main__':
    unittest.main()
