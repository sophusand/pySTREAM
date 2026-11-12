"""Tests of the browser version (pySTREAM_web.py): 'Update scenario' there must give the same
results as the model itself, wrong values must be refused, and every page must work.
The checks run in a copy of the program; see web_checks.py."""
import json
import os
import shutil
import subprocess
import sys
import unittest

from tests import helpers


class WebTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        folder = helpers.make_program_copy()
        try:
            output_file = os.path.join(folder, 'web_checks.json')
            completed = subprocess.run([sys.executable, os.path.join(helpers.TESTS_DIR, 'web_checks.py'), folder, output_file],
                                       capture_output=True, text=True, timeout=600)
            if completed.returncode != 0:
                raise RuntimeError(f'The web checks crashed:\n{completed.stderr[-3000:]}')
            with open(output_file, encoding='utf-8') as f:
                cls.results = json.load(f)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_update_scenario_gives_the_model_results(self):
        for scenario, results in self.results['scenarios'].items():
            with self.subTest(scenario=scenario):
                expected = helpers.load_expected(scenario)
                expected.pop('time_series', None)
                differences = helpers.compare(expected, results, rel_tol=1e-6, abs_tol=1e-6)
                self.assertEqual(differences, [], f'{len(differences)} results differ, e.g. {differences[:5]}')

    def test_warning_when_chp_heat_exceeds_demand(self):
        self.assertIn('Surplus district heat', self.results['warnings']['chp_surplus'])
        self.assertEqual(self.results['warnings']['default'], [])

    def test_wrong_values_are_refused_with_an_explanation(self):
        refused = self.results['refused']
        self.assertIn('between 0 % and 100 %', refused['share 120 %'] or '')
        self.assertIn('Heating, Residential', refused['heating sum 120 %'] or '')
        self.assertIn('utilisation', (refused['utilisation 0 %'] or '').lower())
        self.assertIn('0 €/GJ or more', refused['price -3'] or '')
        self.assertIn('CO2 price', refused['co2 price -10'] or '')
        self.assertIn('between 2015 and 2100', refused['year 2010'] or '')
        self.assertTrue(self.results['unchanged after refused input'])

    def test_every_page_works(self):
        for page, result in self.results['pages'].items():
            self.assertEqual(result, 'ok', page)


if __name__ == '__main__':
    unittest.main()
