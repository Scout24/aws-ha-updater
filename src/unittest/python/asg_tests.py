from unittest import TestCase

from mock import Mock, patch
from boto.ec2.elb import ELBConnection
from boto.ec2 import EC2Connection
from boto.ec2.autoscale import AutoScalingGroup, AutoScaleConnection

from aws_updater.asg import ASGUpdater


class ASGUpdaterTests(TestCase):

    def setUp(self):
        self.asg = Mock(AutoScalingGroup, max_size=None, min_size=None, desired_capacity=None, launch_config_name="any-lc")
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

        self.ec2_conn.terminate_instances.assert_called_with(["any-machine-id", "any-other-machine-id"])

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
        self.asg.instances = []
        self.asg_updater.commit_update()

        self.asg.resume_processes.assert_called_with()

    def test_should_not_resume_processes_when_rolling_back_update(self):
        self.asg.instances = []
        self.asg_updater.rollback()

        self.assertFalse(self.asg.resume_processes.called)
