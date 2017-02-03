#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest

from cron_status import *

class TestFlappingDetection(unittest.TestCase):
    """Test if the flapping detection is operational."""

    def test_all_okay(self):
        status_history_list = [
            {'foo': (ContainerStatus.OKAY, 'no msg')}
        ] * (FLAPPING_HYSTERESIS + 1)
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
        ] * (FLAPPING_HYSTERESIS + 1)
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertFalse(changed)
        self.assertEqual(changed, status[0].changed)  # because there is only 1 container
        self.assertEqual(status[0].overall_status, ContainerStatus.FAILED)
        self.assertEqual(status[0].current_status, ContainerStatus.FAILED)

    def test_failed_after_starting(self):
        status_history_list = [{'foo': (ContainerStatus.FAILED, 'no msg')}]
        status_history_list += [
            {'foo': (ContainerStatus.STARTING, 'no msg')}
        ] * FLAPPING_HYSTERESIS
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertFalse(changed)
        self.assertEqual(status[0].overall_status, ContainerStatus.FAILED)

    def test_okay_after_failed(self):
        status_history_list = [
            {'foo': (ContainerStatus.OKAY, 'no msg')}
        ] * FLAPPING_HYSTERESIS
        status_history_list += [
            {'foo': (ContainerStatus.FAILED, 'no msg')}
        ]
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertTrue(changed)
        self.assertEqual(status[0].overall_status, ContainerStatus.OKAY)

    def test_failed_after_okay(self):
        status_history_list = [
            {'foo': (ContainerStatus.FAILED, 'no msg')}
        ] * FLAPPING_HYSTERESIS
        status_history_list += [
            {'foo': (ContainerStatus.OKAY, 'no msg')}
        ]
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertTrue(changed)
        self.assertEqual(status[0].overall_status, ContainerStatus.FAILED)

    def test_okay_after_failed_flapping(self):
        status_history_list = [
            {'foo': (ContainerStatus.OKAY, 'no msg')}
        ] * (FLAPPING_HYSTERESIS - 1)
        status_history_list += [
            {'foo': (ContainerStatus.FAILED, 'no msg')}
        ] * 2
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertFalse(changed)
        self.assertEqual(status[0].overall_status, ContainerStatus.FLAPPING)

    def test_failed_after_okay_flapping(self):
        status_history_list = [
            {'foo': (ContainerStatus.FAILED, 'no msg')}
        ] * (FLAPPING_HYSTERESIS - 1)
        status_history_list += [
            {'foo': (ContainerStatus.OKAY, 'no msg')}
        ] * 2
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertFalse(changed)
        self.assertEqual(status[0].overall_status, ContainerStatus.FLAPPING)

    def test_missing_data(self):
        status_history_list = [
            {'foo': (ContainerStatus.FAILED, 'no msg')}
        ] * (FLAPPING_HYSTERESIS - 1)
        status_history_list += [{'foo': (ContainerStatus.OKAY, 'no msg')}]
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertFalse(changed)
        self.assertEqual(status[0].overall_status, ContainerStatus.FAILED)

    def test_too_much_data(self):
        status_history_list = [
            {'foo': (ContainerStatus.OKAY, 'no msg')}
        ] * (FLAPPING_HYSTERESIS + 1)
        status_history_list += [{'foo': (ContainerStatus.FAILED, 'no msg')}]
        changed, status = detect_flapping_and_changes(status_history_list)
        self.assertFalse(changed)
        self.assertEqual(status[0].overall_status, ContainerStatus.OKAY)


if __name__ == '__main__':
    unittest.main()
