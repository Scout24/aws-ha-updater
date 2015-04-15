from unittest import TestCase

from mock import patch, Mock
from aws_updater.stack import StackUpdater
from aws_updater.exception import BucketNotAccessibleException, TemplateValidationException
from boto.exception import BotoServerError

def resource(typ, physical_resource_id):
    actual_resource = Mock()
    actual_resource.physical_resource_id = physical_resource_id
    actual_resource.resource_type = typ
    return actual_resource


class StackUpdaterTests(TestCase):

    def setUp(self):
        self.s3_conn = patch("aws_updater.stack.boto.s3.connect_to_region").start()
        self.cfn_conn = patch("aws_updater.stack.boto.cloudformation.connect_to_region").start()
        self.asg_conn = patch("aws_updater.stack.boto.ec2.autoscale.connect_to_region").start()
        self.ec2_conn = patch("aws_updater.stack.boto.ec2.connect_to_region").start()
        self.elb_conn = patch("aws_updater.stack.boto.ec2.elb.connect_to_region").start()

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

    def test_get_template_should_error_when_bucket_is_not_accessible(self):
        self.s3_conn.return_value.get_bucket.side_effect = BotoServerError(403, "bang!")

        stack_updater = StackUpdater("any-stack-name", "any-aws-region")

        self.assertRaises(BucketNotAccessibleException,
                          stack_updater._get_template, "s3://any-bucket/any-template.json")

    def test_get_template_should_error_when_template_file_is_missing(self):
        self.s3_conn.return_value.get_bucket.return_value.get_key.return_value = None

        stack_updater = StackUpdater("any-stack-name", "any-aws-region")

        self.assertRaises(BucketNotAccessibleException,
                          stack_updater._get_template, "s3://any-bucket/any-template.json")

    def test_get_template_should_return_valid_template_from_s3(self):
        template_contents = "this is no json"
        get_key = self.s3_conn.return_value.get_bucket.return_value.get_key
        get_key.return_value.get_contents_as_string.return_value = template_contents

        result = StackUpdater("any-stack-name", "any-aws-region")._get_template("s3://any-bucket/any-template.json")

        self.s3_conn.return_value.get_bucket.assert_called_with("any-bucket")
        get_key.assert_called_with("any-template.json")
        self.cfn_conn.return_value.validate_template.assert_called_with(template_contents)

        self.assertEqual(result, template_contents)

    @patch("__builtin__.open")
    def test_get_template_should_return_valid_template_from_filesystem(self, open):
        template_contents = "this is no json"
        open.return_value.__enter__.return_value.readlines.return_value = [template_contents]
        file_name = "/any-dir/any-template.json"

        result = StackUpdater("any-stack-name", "any-aws-region")._get_template(file_name)

        open.assert_called_with(file_name)
        self.cfn_conn.return_value.validate_template.assert_called_with(template_contents)

        self.assertEqual(result, template_contents)

    @patch("__builtin__.open")
    def test_get_template_should_throw_exception_when_template_is_not_valid(self, open):
        template_contents = "this is no json"
        open.return_value.__enter__.return_value.readlines.return_value = [template_contents]
        validate_template = self.cfn_conn.return_value.validate_template
        validate_template.side_effect = BotoServerError(500, "bang!")
        file_name = "/any-dir/any-template.json"

        self.assertRaises(TemplateValidationException,
                          StackUpdater("any-stack-name", "any-aws-region")._get_template, file_name)

        open.assert_called_with(file_name)
        validate_template.assert_called_with(template_contents)
