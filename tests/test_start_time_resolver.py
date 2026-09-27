# -*- coding: utf-8 -*-
import unittest
from datetime import datetime, timedelta

from research.forward.start_time_resolver import (
    JST, parse_detail_start_time, parse_list_start_times, resolve_start_time, to_jst,
)

LIST = '''
<a href="payback_list.html?kaisai_date=20260922">払戻</a>
<a href="../race/result.html?race_id=202606040701">1R</a>
<span class="RaceList_Itemtime">09:45 </span>
'''
DETAIL = '<div class="RaceData01">15:40発走 芝1600m</div>'


class StartTimeResolverTests(unittest.TestCase):
    def test_list_time_is_parsed_not_inferred(self):
        got = parse_list_start_times(LIST, '20260922')
        self.assertEqual(got['202606040701']['scheduled_start_time'], '09:45')
        twice = LIST + '<a href="?race_id=202606040701"></a><span class="RaceList_Itemtime">10:20</span>'
        self.assertEqual(parse_list_start_times(twice, '20260922')['202606040701']['scheduled_start_time'], '09:45')
        self.assertEqual(got['202606040701']['confidence'], 'SOURCE_PARSED')
        nar = '<a href="?kaisai_date=20260922&race_id=202630092201"></a><div class="RaceData"><span>14:40</span></div>'
        self.assertEqual(parse_list_start_times(nar, '20260922')['202630092201']['scheduled_start_time'], '14:40')

    def test_list_without_time_is_missing(self):
        html = '<a href="?kaisai_date=20260922&race_id=202606040701">1R</a>'
        resolved = resolve_start_time('202606040701', '20260922', list_html=html)
        self.assertIsNone(resolved['scheduled_start_time'])
        self.assertIn('START_TIME_MISSING', resolved['validation_flags'])

    def test_detail_fallback_and_stale_and_timezone(self):
        resolved = resolve_start_time('202606040702', '20260922', list_html=LIST, detail_html=DETAIL)
        self.assertEqual(resolved['scheduled_start_time'], '15:40')
        self.assertEqual(resolved['source'], 'shutuba.RaceData01')
        stale = parse_list_start_times('<a href="?kaisai_date=20260604">', '20260922')
        self.assertIn('STALE_RACE_LIST', stale['_page']['flags'])
        empty = parse_list_start_times('<html>no meeting</html>', '20260922')
        self.assertIn('NO_JRA_MEETING', empty['_page']['flags'])
        stamp = to_jst('20260922', '09:45')
        self.assertEqual(stamp.tzinfo, JST)
        self.assertEqual(stamp.hour, 9)

    def test_change_keeps_old_value_in_return(self):
        first = resolve_start_time('202606040701', '20260922', list_html=LIST)
        second_html = LIST.replace('09:45', '10:05')
        second = resolve_start_time('202606040701', '20260922', list_html=second_html)
        self.assertEqual(first['scheduled_start_time'], '09:45')
        self.assertEqual(second['scheduled_start_time'], '10:05')
        self.assertNotEqual(first['retrieved_at'], '')


if __name__ == '__main__':
    unittest.main()
