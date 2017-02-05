#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest

from cron_status import *

class TestChangeDetection(unittest.TestCase):
    """Test if the change detection is operational."""

    # Please note that status_history_list is backwards,
    # i.e., newest entry first.

    def test_all_okay(self):
        status_history_list = [
            {'foo': (ContainerStatus.OKAY, 'no msg')}
        ] * (STATUS_HISTORY_LENGTH + 1)
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertFalse(changed)
        self.assertEqual(changed, status[0].changed)  # because there is only 1 container
        self.assertEqual(status[0].overall_status, ContainerStatus.OKAY)
        self.assertEqual(status[0].current_status, ContainerStatus.OKAY)
        self.assertTrue(status[0].container_name in status_history_list[0])
        self.assertEqual(status[0].current_msg, status_history_list[0][status[0].container_name][1])

    def test_all_failed(self):
        status_history_list = [
            {'foo': (ContainerStatus.FAILED, 'no msg')}
        ] * (STATUS_HISTORY_LENGTH + 1)
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertFalse(changed)
        self.assertEqual(changed, status[0].changed)  # because there is only 1 container
        self.assertEqual(status[0].overall_status, ContainerStatus.FAILED)
        self.assertEqual(status[0].current_status, ContainerStatus.FAILED)

    def test_failed_after_starting_short(self):
        status_history_list = [{'foo': (ContainerStatus.FAILED, 'no msg')}]
        status_history_list += [
            {'foo': (ContainerStatus.STARTING, 'no msg')}
        ] * (STATUS_HISTORY_LENGTH - 1)
        status_history_list += [{'foo': (ContainerStatus.OKAY, 'no msg')}]
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertTrue(changed)
        self.assertEqual(status[0].overall_status, ContainerStatus.FAILED)

    def test_failed_after_starting_very_long(self):
        status_history_list = [{'foo': (ContainerStatus.FAILED, 'no msg')}]
        status_history_list += [
            {'foo': (ContainerStatus.STARTING, 'no msg')}
        ] * STATUS_HISTORY_LENGTH
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertTrue(changed)
        self.assertEqual(status[0].overall_status, ContainerStatus.FAILED)

    def test_okay_after_failed(self):
        status_history_list = [
            {'foo': (ContainerStatus.OKAY, 'no msg')}
        ]
        status_history_list += [
            {'foo': (ContainerStatus.FAILED, 'no msg')}
        ] * STATUS_HISTORY_LENGTH
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertTrue(changed)
        self.assertEqual(status[0].overall_status, ContainerStatus.OKAY)

    def test_failed_after_okay(self):
        status_history_list = [
            {'foo': (ContainerStatus.FAILED, 'no msg')}
        ]
        status_history_list += [
            {'foo': (ContainerStatus.OKAY, 'no msg')}
        ] * STATUS_HISTORY_LENGTH
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertTrue(changed)
        self.assertEqual(status[0].overall_status, ContainerStatus.FAILED)

    def test_missing_data(self):
        status_history_list = [
            {'foo': (ContainerStatus.FAILED, 'no msg')}
        ] * (STATUS_HISTORY_LENGTH - 1)
        status_history_list += [{'foo': (ContainerStatus.OKAY, 'no msg')}]
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertFalse(changed)
        self.assertEqual(status[0].overall_status, ContainerStatus.FAILED)

    def test_too_much_data(self):
        status_history_list = [
            {'foo': (ContainerStatus.OKAY, 'no msg')}
        ] * (STATUS_HISTORY_LENGTH + 1)
        status_history_list += [{'foo': (ContainerStatus.FAILED, 'no msg')}]
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertFalse(changed)
        self.assertEqual(status[0].overall_status, ContainerStatus.OKAY)


if __name__ == '__main__':
    unittest.main()
