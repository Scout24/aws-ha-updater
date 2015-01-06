from unittest import TestCase

from mock import Mock, patch, call
from boto.ec2.elb import ELBConnection
from boto.ec2 import EC2Connection
from boto.ec2.autoscale import AutoScalingGroup, AutoScaleConnection

from aws_updater.asg import ASGUpdater, RolledBackException, TimeoutException


class ASGUpdaterTests(TestCase):

    def setUp(self):
        self.asg = Mock(AutoScalingGroup, max_size=0, min_size=0, desired_capacity=0, launch_config_name="any-lc")
        self.asg.instances = []
        self.asg.name = "any-asg-name"
        self.asg_conn = Mock(AutoScaleConnection)
        self.ec2_conn = Mock(EC2Connection)
        self.elb_conn = Mock(ELBConnection)
        patch("aws_updater.asg.print", create=True).start()
        self.asg_updater = ASGUpdater(self.asg,
                                      self.asg_conn,
                                      self.ec2_conn,
                                      self.elb_conn)

    def tearDown(self):
        patch.stopall()

    def test_should_terminate_instances(self):
        self.asg_updater._terminate_instances(["any-machine-id", "any-other-machine-id"])

        assert self.asg_conn.terminate_instance.call_count == 2
        self.asg_conn.terminate_instance.assert_any_call("any-machine-id", decrement_capacity=False)
        self.asg_conn.terminate_instance.assert_any_call("any-other-machine-id", decrement_capacity=False)

    def test_should_terminate_old_instances_when_committing_update(self):
        self.asg.instances = [Mock(instance_id="1", launch_config_name="any-lc"),
                              Mock(instance_id="resource_id_of_instance_with_old_lc", launch_config_name="any-old-lc"),
                              Mock(instance_id="3", launch_config_name="any-lc")]

        with patch("aws_updater.asg.ASGUpdater._terminate_instances") as terminate_instances:
            self.asg_updater.commit_update()
            terminate_instances.assert_called_with(["resource_id_of_instance_with_old_lc"])

    def test_should_terminate_new_instances_when_rolling_back_update(self):
        self.asg.instances = [Mock(instance_id="resource_id_of_instance_with_new_lc-1", launch_config_name="any-lc"),
                              Mock(instance_id="2", launch_config_name="any-old-lc"),
                              Mock(instance_id="resource_id_of_instance_with_new_lc-2", launch_config_name="any-lc")]

        with patch("aws_updater.asg.ASGUpdater._terminate_instances") as terminate_instances:
            self.asg_updater.rollback()
            terminate_instances.assert_called_with(['resource_id_of_instance_with_new_lc-1', 'resource_id_of_instance_with_new_lc-2'])

    def test_should_resume_processes_when_committing_update(self):
        self.asg_updater.commit_update()

        self.asg.resume_processes.assert_called_with()

    def test_should_not_resume_processes_when_rolling_back_update(self):
        self.asg_updater.rollback()

        self.assertFalse(self.asg.resume_processes.called)

    def test_should_count_instances_that_might_serve_requests(self):
        self.asg.instances = [Mock(lifecycle_state="Pending"),
                              Mock(lifecycle_state="InService"),
                              Mock(lifecycle_state="Rebooting"),
                              Mock(lifecycle_state="AFKing"),
                              Mock(lifecycle_state="Terminating"),
                              Mock(lifecycle_state="OutOfService")]

        actual_count = self.asg_updater.count_running_instances()

        self.assertEqual(actual_count, 3)

    def test_should_stop_all_processes_except_specified_ones_when_scaling_out(self):
        self.asg_updater.scale_out()

        self.asg.suspend_processes.assert_called_with()
        self.asg.resume_processes.assert_called_with(['Launch', 'Terminate', 'HealthCheck', 'AddToLoadBalancer'])

    def test_should_update_asg_parameters_to_double_running_instances_when_scaling_out(self):
        self.asg.min_size = 3
        self.asg.max_size = 6
        self.asg.desired_capacity = 3
        self.asg.instances = [Mock(lifecycle_state="InService"),
                              Mock(lifecycle_state="InService"),
                              Mock(lifecycle_state="InService")]

        self.asg_updater.scale_out()

        self.assertEqual(self.asg.min_size, 6)
        self.assertEqual(self.asg.max_size, 9)
        self.assertEqual(self.asg.desired_capacity, 6)
        self.asg.update.assert_called_with()

    @patch("aws_updater.asg.ASGUpdater.get_instances_views")
    def test_should_get_nr_of_uptodate_instances(self, views):
        self.asg.launch_config_name = "current-lc"
        views.return_value = {
            u'i-46cd9105': {
                'asg': Mock(launch_config_name="current-lc"),
                'elb': Mock(state="InService")},
            # Does not qualify, out of service
            u'i-46cd9109': {
                'asg': Mock(launch_config_name="current-lc"),
                'elb': Mock(state="OutOfService")},
            # Does not qualify, no elb
            u'i-46cd9108': {
                'asg': Mock(launch_config_name="current-lc")},
            # Does not qualify, other launch config and out of service
            u'i-46cd9107': {
                'asg': Mock(launch_config_name="other-lc"),
                'elb': Mock(state="OutOfService")},
            # Does not qualify, other launch config
            u'i-46cd9145': {
                'asg': Mock(launch_config_name="other-lc"),
                'elb': Mock(state="InService")},
            u'i-46cd9142': {
                'asg': Mock(launch_config_name="current-lc"),
                'elb': Mock(state="InService")},
        }

        self.assertEqual(self.asg_updater.get_nr_of_uptodate_instances(), 2)

    def test_should_commit_after_update(self):
        mock_updater = Mock(ASGUpdater)

        ASGUpdater.update(mock_updater)

        mock_updater.commit_update.assert_called_with()
        self.assertEqual(mock_updater.rollback.called, False)

    def test_should_rollback_after_failed_update(self):
        mock_updater = Mock(ASGUpdater, asg=Mock(name="some-asg"))
        mock_updater.wait_for_scale_out_complete.side_effect = Exception("Timed out while slacking off")

        self.assertRaises(RolledBackException, ASGUpdater.update, mock_updater)

        mock_updater.rollback.assert_called_with()
        self.assertEqual(mock_updater.commit_update.called, False)

    def test_should_rollback_when_ctrl_c_by_user(self):
        mock_updater = Mock(ASGUpdater, asg=Mock(name="some-asg"))
        mock_updater.wait_for_scale_out_complete.side_effect = KeyboardInterrupt()

        self.assertRaises(KeyboardInterrupt, ASGUpdater.update, mock_updater)

        mock_updater.rollback.assert_called_with()
        self.assertEqual(mock_updater.commit_update.called, False)

    @patch("aws_updater.asg.time.sleep")
    @patch("aws_updater.asg.ASGUpdater.get_instances_views")
    @patch("aws_updater.asg.ASGUpdater.count_running_instances")
    def test_should_wait_for_scale_out_completed_when_needing_two_tries(self, running_instances, views, sleep):
        running_instances.return_value = 2
        self.asg_conn.get_all_groups.return_value = (Mock(launch_config_name="current-lc"),)
        two_uptodate_after_two_tries = [
            {  # returned on first call of get_instances_views
                u'i-46cd9105': {
                    'asg': Mock(launch_config_name="current-lc"),
                    'elb': Mock(state="InService")},
                u'i-46cd9109': {
                    'asg': Mock(launch_config_name="current-lc"),
                    'elb': Mock(state="OutOfService")},
            },
            {  # returned on second call
                u'i-46cd9105': {
                    'asg': Mock(launch_config_name="current-lc"),
                    'elb': Mock(state="InService")},
                u'i-46cd9109': {
                    'asg': Mock(launch_config_name="current-lc"),
                    'elb': Mock(state="InService")},
            }]

        views.side_effect = two_uptodate_after_two_tries

        self.asg_updater.wait_for_scale_out_complete()

        self.assertEqual(sleep.call_args_list, [call(1)])

    @patch("aws_updater.asg.time.time")
    @patch("aws_updater.asg.time.sleep")
    @patch("aws_updater.asg.ASGUpdater.get_instances_views")
    @patch("aws_updater.asg.ASGUpdater.count_running_instances")
    def test_should_time_out_when_too_few_instances_become_healthy(self, running_instances, views, sleep, time):
        running_instances.return_value = 2
        self.asg_conn.get_all_groups.return_value = (Mock(launch_config_name="current-lc"),)
        time.side_effect = [0, 1200, 9000]
        views.return_value = {
            u'i-46cd9105': {
                'asg': Mock(launch_config_name="current-lc"),
                'elb': Mock(state="OutOfService")},
            u'i-46cd9109': {
                'asg': Mock(launch_config_name="other-lc"),
                'elb': Mock(state="InService")},
        }

        self.assertRaises(TimeoutException, self.asg_updater.wait_for_scale_out_complete)
