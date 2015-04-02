from unittest import TestCase

from mock import patch, Mock
from aws_updater.stack import StackUpdater
from aws_updater.exception import *
from boto.exception import BotoServerError

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

    @patch("aws_updater.stack.boto.s3.connection.S3Connection.get_bucket")
    def test_get_template_should_error_when_bucket_is_not_accessible(self, get_bucket):
        get_bucket.side_effect = BotoServerError(403, "bang!")

        stack_updater = StackUpdater("any-stack-name", "any-aws-region")

        with self.assertRaises(BucketNotAccessibleException):
            stack_updater.get_template("s3://any-bucket/any-template.json")

    @patch("aws_updater.stack.boto.s3.connection.S3Connection.get_bucket")
    @patch("aws_updater.stack.boto.s3.bucket.Bucket.get_key")
    @patch("aws_updater.stack.boto.s3.key.Key.get_contents_as_string")
    def test_get_template_should_return_template(self, get_contents_as_string, get_key, get_bucket):
        template_contents = "this is no json"
        get_contents_as_string.return_value = template_contents

        stack_updater = StackUpdater("any-stack-name", "any-aws-region")

        self.assertEqual(stack_updater.get_template("s3://any-bucket/any-template.json"), template_contents)
