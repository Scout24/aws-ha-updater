from unittest import TestCase

from mock import patch, Mock

from aws_updater.stack import StackUpdater


def resource(typ, physical_resource_id):
    actual_resource = Mock()
    actual_resource.physical_resource_id = physical_resource_id
    actual_resource.resource_type = typ
    return actual_resource


class StackUpdaterTests(TestCase):

    def setUp(self):
        self.cfn_patcher = patch("aws_updater.stack.boto.cloudformation.connect_to_region")
        self.asg_patcher = patch("aws_updater.stack.boto.ec2.autoscale.connect_to_region")
        self.ec2_patcher = patch("aws_updater.stack.boto.ec2.connect_to_region")
        self.elb_patcher = patch("aws_updater.stack.boto.ec2.elb.connect_to_region")
        self.cfn_conn = self.cfn_patcher.start()
        self.asg_conn = self.asg_patcher.start()
        self.ec2_conn = self.ec2_patcher.start()
        self.elb_conn = self.elb_patcher.start()

    def tearDown(self):
        patch.stopall()

    @patch("aws_updater.stack.describe_stack")
    def test_should_error_when_describing_stack_yields_nothing(self, describe_stack):
        describe_stack.return_value = None

        stack_updater = StackUpdater("any-stack-name", "any-aws-region")

        self.assertRaises(Exception, stack_updater.get_all_asgs_from_stack)

    @patch("aws_updater.stack.describe_stack")
    def test_should_fetch_groups_with_asg_resource_ids(self, describe_stack):
        described_resources = [resource("AWS::AutoScaling::AutoScalingGroup", 1),
                               resource("AWS::AnyNonASGResource", 2),
                               resource("AWS::AutoScaling::AutoScalingGroup", 4)]
        describe_stack.return_value.describe_resources.return_value = described_resources

        stack_updater = StackUpdater("any-stack-name", "any-aws-region")
        stack_updater.get_all_asgs_from_stack()

        self.asg_conn.return_value.get_all_groups.assert_called_with([1, 4])
