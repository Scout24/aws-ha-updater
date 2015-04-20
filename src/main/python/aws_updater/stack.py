import json
import logging

import boto.cloudformation
import boto.ec2
import boto.exception
import boto.ec2.elb
import boto.ec2.autoscale
import boto.s3.connection
from aws_updater.utils import timed
from aws_updater.asg import ASGUpdater
from aws_updater import describe_stack, get_all_autoscaling_groups, wait_for_action_to_complete


class BucketNotAccessibleException(Exception):
    pass


class TemplateValidationException(Exception):
    pass


class StackUpdater(object):

    def __init__(self, stack_name, region, observer_callback=None, timeout_in_seconds=None):
        self.logger = logging.getLogger(__name__)
        self.stack_name = stack_name
        self.cfn_conn = boto.cloudformation.connect_to_region(region)
        self.as_conn = boto.ec2.autoscale.connect_to_region(region)
        self.ec2_conn = boto.ec2.connect_to_region(region)
        self.elb_conn = boto.ec2.elb.connect_to_region(region)
        self.s3_conn = boto.s3.connection.S3Connection()
        self.timeout_in_seconds = timeout_in_seconds

        dummy_observer_callback = lambda event: None
        self.observer_callback = observer_callback or dummy_observer_callback

    def get_all_asgs_from_stack(self):
        stack = describe_stack(self.cfn_conn, self.stack_name)
        if not stack:
            raise Exception("No stack with name '{0}' found.".format(self.stack_name))

        return get_all_autoscaling_groups(self.as_conn, stack)

    @timed
    def update_asgs(self):
        for asg in self.get_all_asgs_from_stack():
            self.logger.info("Updating ASG '{0}'.".format(asg.name))
            ASGUpdater(asg,
                       self.as_conn,
                       self.ec2_conn,
                       self.elb_conn,
                       self.observer_callback,
                       timeout_in_seconds=self.timeout_in_seconds).update()

    def _get_filecontent_from_bucket(self, bucketname, filename):
        bucket = self.s3_conn.get_bucket(bucketname)
        file_key = bucket.get_key(filename)
        if file_key is None:
            raise BucketNotAccessibleException(
                "Template file: {0} not found in bucket: {1}.".format(filename, bucketname))
        return file_key.get_contents_as_string()

    def _get_template(self, template_filename):
        if template_filename.startswith("s3"):
            urlparts = template_filename.split('/')
            bucketname = urlparts[2]
            filename = '/'.join(urlparts[3:])
            try:
                template = self._get_filecontent_from_bucket(bucketname, filename)
            except boto.exception.BotoServerError, e:
                raise BucketNotAccessibleException(
                    "Unable to get template file: '{0}'. Caused by: {1}.".format(template_filename, e))
        else:
            with open(template_filename) as template_file:
                template = "".join(template_file.readlines())

        try:
            self.logger.info("Start validating template '{0}'.".format(template_filename))
            self.cfn_conn.validate_template(template)
        except boto.exception.BotoServerError, e:
            raise TemplateValidationException(
                "Invalid template '{0}'. Caused by: {1}".format(template_filename, e))
        return template

    def _do_update_or_create(self, action, template, stack_parameters):
        try:
            action(self.stack_name, template_body=template,
                   parameters=stack_parameters.items(),
                   capabilities=['CAPABILITY_IAM'])
        except boto.exception.BotoServerError, e:
            error = json.loads(e.body).get("Error", "{}")
            error_message = error.get("Message")
            if error_message == "No updates are to be performed.":
                self.logger.info("Nothing to do: {0}.".format(error_message))
            else:
                error_code = error.get("Code")
                self.logger.error("Stack '{0}' does not exist.".format(self.stack_name))
                raise Exception("{0}: {1}.".format(error_code, error_message))
        except BaseException, e:
            raise Exception("Something went horribly wrong: {0}.".format(e.message))

    def _get_template_of_running_stack(self, stack):
        return "".join(
            self.cfn_conn.get_template(
                stack.stack_id).get("GetTemplateResponse", {}).get("GetTemplateResult", {}).get("TemplateBody", []))

    def _merge_stack_parameters(self, existing_stack, stack_parameters):
        merged_stack_parameters = {}
        for parameter in existing_stack.parameters:
            merged_stack_parameters[parameter.key] = parameter.value

        merged_stack_parameters.update(stack_parameters)
        self.logger.info(", ".join(
            [" : ".join((key, str(merged_stack_parameters[key]))) for key in merged_stack_parameters]))

        return merged_stack_parameters

    def update_stack(self, stack_parameters, template_filename=None, lenient_lookback=5, action_timeout=300,
                     warmup_seconds=25):
        stack = describe_stack(self.cfn_conn, self.stack_name)

        if stack:
            self.logger.info("Start updating running stack.")

            if template_filename is None:
                template = self._get_template_of_running_stack(stack)
            else:
                template = self._get_template(template_filename)

            updated_stack_parameters = self._merge_stack_parameters(stack, stack_parameters)

            self._do_update_or_create(self.cfn_conn.update_stack, template, updated_stack_parameters)
        else:
            self.logger.info("Start creating stack.")

            template = self._get_template(template_filename)
            self._do_update_or_create(self.cfn_conn.create_stack, template, stack_parameters)

        wait_for_action_to_complete(self.cfn_conn, self.stack_name, warmup_seconds, lenient_lookback, action_timeout)
