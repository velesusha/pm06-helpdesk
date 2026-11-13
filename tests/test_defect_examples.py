import unittest
from exercises import defect_examples as d


class DefectExamplesTests(unittest.TestCase):
    def test_filter_before_and_after(self):
        rows=[{'status':'new'},{'status':'closed'}]
        self.assertEqual(len(d.filter_before(rows,'new')),2)
        self.assertEqual(len(d.filter_after(rows,'new')),1)

    def test_subject_before_and_after(self):
        self.assertTrue(d.subject_before('   '))
        self.assertFalse(d.subject_after('   '))

    def test_transition_before_and_after(self):
        self.assertTrue(d.transition_before('new','closed'))
        self.assertFalse(d.transition_after('new','closed'))
